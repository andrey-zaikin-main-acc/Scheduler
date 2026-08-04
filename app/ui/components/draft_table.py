"""Single Python adapter for editable draft tables.

The adapter isolates pages from the widget protocol and emits stable, structured
cell/range events.  Visual metadata is retained in session state so reruns can
focus and animate the affected row without invoking business logic.
"""

from dataclasses import dataclass
from numbers import Integral
from typing import Any, Iterable
from copy import deepcopy

import streamlit as st


@dataclass(frozen=True)
class TableEvent:
    kind: str
    row_keys: tuple[object, ...]
    fields: tuple[str, ...]
    before: tuple[dict[str, Any], ...]
    after: tuple[dict[str, Any], ...]
    animation: str = "cell-change"


@dataclass(frozen=True)
class DraftTableResult:
    rows: list[dict[str, Any]]
    events: tuple[TableEvent, ...]


def stable_row_key(row: dict[str, Any]) -> object:
    """Use a persisted ID or a durable temporary ID, never the row index."""
    # data_editor/pandas represents an empty numeric ID as NaN.  It is truthy,
    # so an ``or`` chain would hide the valid negative draft ID behind it.
    candidates = (row.get("ID"), row.get("id"), row.get("_draft_id"))
    value = next((candidate for candidate in candidates
                  if isinstance(candidate, Integral) and not isinstance(candidate, bool)
                  and int(candidate) != 0), None)
    if value is None:
        raise ValueError("Draft table rows require ID or _draft_id")
    return int(value)


def next_draft_id(rows: Iterable[dict[str, Any]]) -> int:
    """Allocate a stable negative id without relying on a mutable row index."""
    used = {int(row["_draft_id"]) for row in rows if isinstance(row.get("_draft_id"), int)}
    return min(used | {0}) - 1


def new_draft_row(rows: Iterable[dict[str, Any]], **values: Any) -> dict[str, Any]:
    return {"_draft_id": next_draft_id(rows), **values}


def replace_table_source(key: str) -> None:
    """Invalidate a widget after a programmatic snapshot replacement."""
    version_key = f"{key}_source_version"
    st.session_state[version_key] = int(st.session_state.get(version_key, 0)) + 1


def draft_table(rows: list[dict[str, Any]], *, key: str, read_only: list[str] | None = None,
                selection_field: str = "Выбран", **kwargs: Any) -> DraftTableResult:
    """Render the editor and translate its protocol into semantic events.

    Pages consume only rows and these events.  In particular, a selection
    checkbox is reported as ``selection`` and never as a business edit.
    """
    postprocess = kwargs.pop("postprocess", None)
    disabled = read_only if read_only is not None else kwargs.pop("disabled", [])
    source_version = int(st.session_state.get(f"{key}_source_version", 0))
    applied_key = f"{key}_applied_source_version"
    if st.session_state.get(applied_key) != source_version:
        st.session_state.pop(key, None)
        st.session_state[applied_key] = source_version
    edited = st.data_editor(rows, key=key, disabled=disabled, **kwargs)
    edited = [dict(row) for row in edited]
    # Underscore-prefixed metadata is not part of data_editor's browser
    # payload. Preserve the durable temporary key for these fixed-row tables.
    if len(edited) == len(rows):
        for original, current in zip(rows, edited, strict=True):
            if isinstance(original.get("_draft_id"), Integral):
                current["_draft_id"] = int(original["_draft_id"])
            for identity_field in ("ID", "id"):
                if (not isinstance(current.get(identity_field), Integral)
                        and isinstance(original.get(identity_field), Integral)):
                    current[identity_field] = int(original[identity_field])
    if postprocess is not None:
        edited = postprocess(rows, edited)
    before_by_key = {stable_row_key(row): row for row in rows}
    after_by_key = {stable_row_key(row): row for row in edited}
    events: list[TableEvent] = []
    removed = tuple(before_by_key.keys() - after_by_key.keys())
    added = tuple(after_by_key.keys() - before_by_key.keys())
    if removed:
        events.append(TableEvent("delete", removed, (), tuple(deepcopy(before_by_key[k]) for k in removed), (), "row-remove"))
    if added:
        kind = "restore" if any(int(k) > 0 for k in added if isinstance(k, int)) else "add"
        events.append(TableEvent(kind, added, (), (), tuple(deepcopy(after_by_key[k]) for k in added), "row-restore" if kind == "restore" else "row-add"))
    changes: list[tuple[object, set[str]]] = []
    for row_key in before_by_key.keys() & after_by_key.keys():
        changed = {name for name in set(before_by_key[row_key]) | set(after_by_key[row_key]) if before_by_key[row_key].get(name) != after_by_key[row_key].get(name)}
        if changed:
            changes.append((row_key, changed))
    selection = [(k, fs) for k, fs in changes if fs == {selection_field}]
    business = [(k, fs - {selection_field}) for k, fs in changes if fs - {selection_field}]
    if selection:
        keys = tuple(k for k, _ in selection)
        events.append(TableEvent("selection", keys, (selection_field,),
                                 tuple(deepcopy(before_by_key[k]) for k in keys),
                                 tuple(deepcopy(after_by_key[k]) for k in keys), "selection"))
    if business:
        keys = tuple(k for k, _ in business)
        fields = tuple(sorted(set().union(*(fs for _, fs in business))))
        kind = "checkbox" if len(fields) == 1 and all(isinstance(after_by_key[k].get(fields[0]), bool) for k in keys) else (
            "cell" if len(keys) == len(fields) == 1 else "range")
        events.append(TableEvent(kind, keys, fields, tuple(deepcopy(before_by_key[k]) for k in keys),
                                 tuple(deepcopy(after_by_key[k]) for k in keys)))
    result_events = tuple(events)
    if result_events:
        st.session_state[f"{key}_visual_event"] = result_events[-1]
        business_events = [event for event in result_events if event.kind != "selection"]
        if business_events and not st.session_state.get("draft_history_replay_in_progress"):
            from app.services.draft_history_service import DraftAction, session_history
            section = ("orders" if key.startswith("orders_page") else
                       "operations" if "operation_editor" in key else
                       "routes" if key.startswith("routes_page") else "work_centers")
            route_id = int(key.rsplit("_", 1)[-1]) if section == "operations" and key.rsplit("_", 1)[-1].isdigit() else None
            event = business_events[-1]
            session_history(st.session_state).record(DraftAction(
                section, event.kind, deepcopy(rows), deepcopy(edited), event.row_keys,
                event.fields, route_id=route_id, focus={"session_key": (
                    "route_operations_drafts_by_route_id" if section == "operations" else
                    f"{section}_draft_rows")},
            ))
    _render_replay_focus(key, edited)
    return DraftTableResult(edited, result_events)


def _render_replay_focus(key: str, rows: list[dict[str, Any]]) -> None:
    """Consume replay metadata and show the affected real rows/cells."""
    if st.session_state.get("draft_history_replay_editor_key") != key:
        return
    event = st.session_state.pop("draft_visual_event", None) or {}
    row_keys = set(event.get("rows", ()))
    fields = list(event.get("fields", ()))
    affected = [row for row in rows if stable_row_key(row) in row_keys]
    if affected:
        visible_fields = [field for field in fields if field in affected[0]]
        columns = visible_fields or list(affected[0])
        st.caption("Результат отмены" if event.get("undo") else "Результат повтора")
        # This is the replay confirmation for the actual affected rows, rather
        # than the former textual animation name.  Styler highlights cells.
        import pandas as pd
        frame = pd.DataFrame(affected)[columns]
        st.dataframe(frame.style.map(lambda _: "background-color: #fff3bf"),
                     use_container_width=True, hide_index=True)
    elif event.get("animation") == "remove":
        st.info("Выбранные строки удалены из черновика.")
    st.session_state.pop("draft_history_replay_editor_key", None)
    st.session_state["draft_history_replay_in_progress"] = False
