"""Browser-owned editable table used by the routes and work-centres drafts.

Unlike ``st.data_editor``, the component protocol has an explicit flush token.
The browser acknowledges that token only after committing its active input and
returning an authoritative snapshot.
"""

from copy import deepcopy
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Callable

import streamlit as st
import streamlit.components.v1 as components

from app.services.draft_history_service import DraftAction, mark_section_dirty, session_history
from app.ui.components.draft_table import stable_row_key


_component = components.declare_component(
    "drawppt_reference_grid", path=Path(__file__).with_name("orders_grid") / "frontend"
)


def _decode(value: Any, field: str, numeric_fields: set[str], boolean_fields: set[str]) -> Any:
    if field in boolean_fields:
        return bool(value)
    if field in numeric_fields and isinstance(value, Real) and not isinstance(value, bool):
        return int(value) if field in {"ID", "№"} and float(value).is_integer() else float(value)
    return value


def apply_reference_payload(
    state: Any,
    payload: dict[str, Any] | None,
    *,
    rows_key: str,
    editor_key: str,
    section: str,
    numeric_fields: set[str],
    boolean_fields: set[str],
    route_id: int | None = None,
    focus_rows_key: str | None = None,
    postprocess: Callable | None = None,
) -> list[dict[str, Any]]:
    """Apply unseen events and an authoritative flush snapshot exactly once."""
    rows = [dict(row) for row in state.get(rows_key, [])]
    if not payload:
        return rows
    ack_key = f"{editor_key}_component_ack_revision"
    ack = int(state.get(ack_key, 0))
    for raw in sorted(payload.get("events", []), key=lambda item: int(item["client_revision"])):
        revision = int(raw["client_revision"])
        if revision <= ack:
            continue
        row = next((item for item in rows if stable_row_key(item) == raw["row_key"]), None)
        if row is None:
            continue
        before = deepcopy(rows)
        field = str(raw["field"])
        row[field] = _decode(raw.get("after"), field, numeric_fields, boolean_fields)
        if postprocess is not None:
            rows = postprocess(before, rows)
        if raw.get("action_type") != "selection" and not state.get("draft_history_replay_in_progress"):
            session_history(state).record(DraftAction(
                section, str(raw.get("action_type") or "cell"), before, deepcopy(rows),
                (raw["row_key"],), (field,), route_id=route_id,
                focus={"session_key": focus_rows_key or rows_key},
            ))
            mark_section_dirty(state, section)
        ack = revision

    flush_ack = payload.get("flush_ack")
    if flush_ack and payload.get("snapshot") is not None:
        snapshot = [
            {field: _decode(value, field, numeric_fields, boolean_fields)
             for field, value in dict(row).items()}
            for row in payload["snapshot"]
        ]
        # Events already represent the user's business actions.  The snapshot
        # is only a barrier/source of truth and must not add a duplicate action.
        rows = postprocess(rows, snapshot) if postprocess is not None else snapshot
        state[f"{editor_key}_component_flush_ack"] = flush_ack
    state[ack_key] = max(ack, int(payload.get("client_revision", ack)))
    state[rows_key] = rows
    return rows


def reference_table(
    rows: list[dict[str, Any]], *, editor_key: str, rows_key: str, section: str,
    columns: list[str], read_only: list[str], numeric_fields: set[str],
    boolean_fields: set[str], options: dict[str, list[str]] | None = None,
    route_id: int | None = None, postprocess: Callable | None = None,
    focus_rows_key: str | None = None,
) -> list[dict[str, Any]]:
    """Render a reference grid without letting a Python rerun own its input."""
    state = st.session_state
    version = int(state.get(f"{editor_key}_source_version", 0))
    payload = _component(
        rows=[dict(row) for row in rows], source_version=version,
        server_ack_revision=int(state.get(f"{editor_key}_component_ack_revision", 0)),
        flush_token=state.get("reference_tables_flush_request"), columns=columns,
        read_only=read_only, options=options or {}, numeric_fields=list(numeric_fields),
        boolean_fields=list(boolean_fields), key=f"{editor_key}_browser", default=None,
    )
    return apply_reference_payload(
        state, payload, rows_key=rows_key, editor_key=editor_key, section=section,
        numeric_fields=numeric_fields, boolean_fields=boolean_fields,
        route_id=route_id, postprocess=postprocess, focus_rows_key=focus_rows_key,
    )


def request_reference_save(state: Any, *, section: str, editor_keys: list[str], navigation: bool = False) -> str:
    """Start one save barrier; repeated button callbacks keep the same request."""
    from uuid import uuid4

    token = state.get("reference_tables_flush_request") or uuid4().hex
    state["reference_tables_flush_request"] = token
    state["reference_tables_save_requested"] = section
    state["reference_tables_flush_editors"] = list(dict.fromkeys(editor_keys))
    if navigation:
        state["pending_navigation_commit"] = True
    return token


def reference_save_ready(state: Any, section: str) -> bool:
    token = state.get("reference_tables_flush_request")
    return bool(
        token and state.get("reference_tables_save_requested") == section
        and all(state.get(f"{key}_component_flush_ack") == token
                for key in state.get("reference_tables_flush_editors", []))
    )


def clear_reference_save(state: Any) -> None:
    for key in ("reference_tables_flush_request", "reference_tables_save_requested",
                "reference_tables_flush_editors"):
        state.pop(key, None)
