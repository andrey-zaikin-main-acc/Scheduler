"""Single Python adapter for editable draft tables.

The adapter isolates pages from the widget protocol and emits stable, structured
cell/range events.  Visual metadata is retained in session state so reruns can
focus and animate the affected row without invoking business logic.
"""

from dataclasses import dataclass
from typing import Any

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
    value = row.get("ID", row.get("_draft_id"))
    if value is None:
        raise ValueError("Draft table rows require ID or _draft_id")
    return value


def draft_table(rows: list[dict[str, Any]], *, key: str, read_only: list[str], **kwargs: Any) -> DraftTableResult:
    """Render a fixed-row editor and translate its value into one range event."""
    edited = st.data_editor(rows, key=key, disabled=read_only, num_rows="fixed", **kwargs)
    before_by_key = {stable_row_key(row): row for row in rows}
    after_by_key = {stable_row_key(row): row for row in edited}
    changed_keys: list[object] = []
    fields: set[str] = set()
    for row_key in before_by_key.keys() & after_by_key.keys():
        changed = {name for name in set(before_by_key[row_key]) | set(after_by_key[row_key]) if before_by_key[row_key].get(name) != after_by_key[row_key].get(name)}
        if changed:
            changed_keys.append(row_key); fields.update(changed)
    events: tuple[TableEvent, ...] = ()
    if changed_keys:
        events = (TableEvent("range" if len(changed_keys) > 1 or len(fields) > 1 else "cell", tuple(changed_keys), tuple(sorted(fields)), tuple(before_by_key[k] for k in changed_keys), tuple(after_by_key[k] for k in changed_keys)),)
        st.session_state[f"{key}_visual_event"] = events[0]
    return DraftTableResult(list(edited), events)
