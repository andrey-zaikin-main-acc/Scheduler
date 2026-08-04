"""Single Python adapter for editable draft tables.

The adapter isolates pages from the widget protocol and emits stable, structured
cell/range events.  Visual metadata is retained in session state so reruns can
focus and animate the affected row without invoking business logic.
"""

from dataclasses import dataclass
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
    value = row.get("ID") or row.get("id") or row.get("_draft_id")
    if value is None:
        raise ValueError("Draft table rows require ID or _draft_id")
    if not isinstance(value, int) or isinstance(value, bool) or value == 0:
        raise ValueError("Draft table row keys must be non-zero integers")
    return value


def next_draft_id(rows: Iterable[dict[str, Any]]) -> int:
    """Allocate a stable negative id without relying on a mutable row index."""
    used = {int(row["_draft_id"]) for row in rows if isinstance(row.get("_draft_id"), int)}
    return min(used | {0}) - 1


def new_draft_row(rows: Iterable[dict[str, Any]], **values: Any) -> dict[str, Any]:
    return {"_draft_id": next_draft_id(rows), **values}


def draft_table(rows: list[dict[str, Any]], *, key: str, read_only: list[str] | None = None,
                selection_field: str = "Выбран", **kwargs: Any) -> DraftTableResult:
    """Render the editor and translate its protocol into semantic events.

    Pages consume only rows and these events.  In particular, a selection
    checkbox is reported as ``selection`` and never as a business edit.
    """
    disabled = read_only if read_only is not None else kwargs.pop("disabled", [])
    edited = st.data_editor(rows, key=key, disabled=disabled, **kwargs)
    edited = [dict(row) for row in edited]
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
        if business_events:
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
        # A visible, dependency-free animation cue; the widget remains native
        # Streamlit and therefore works in the bundled pywebview application.
        st.markdown("<style>@keyframes draftPulse{0%{background:#fff3bf}100%{background:transparent}}"
                    ".draft-table-event{animation:draftPulse .8s ease-out}</style>"
                    f"<div class='draft-table-event' aria-live='polite'>{result_events[-1].animation}</div>",
                    unsafe_allow_html=True)
    return DraftTableResult(edited, result_events)
