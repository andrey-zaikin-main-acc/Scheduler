"""Python protocol adapter for the browser-owned orders grid."""

from copy import deepcopy
from datetime import date, datetime
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Callable

import streamlit as st
import streamlit.components.v1 as components

from app.services.draft_history_service import DraftAction, session_history
from app.ui.components.draft_table import stable_row_key

_component = components.declare_component(
    "drawppt_orders_grid", path=Path(__file__).with_name("orders_grid") / "frontend"
)
DATE_FIELDS = {"Заданная дата запуска", "Заданная дата отгрузки", "Расчётная дата запуска", "Расчётная дата отгрузки"}
INTEGER_FIELDS = {"ID", "Приоритет", "_draft_id", "_child_sequence_number"}
NUMBER_FIELDS = {"Тираж"}
BOOLEAN_FIELDS = {"Выбран", "Связанные заказы", "Запланирован", "Конфликт планирования", "_is_child_order"}


def encode_value(field: str, value: Any) -> Any:
    """Convert business-layer values to the component's JSON transport types."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _encode_row(row: dict[str, Any]) -> dict[str, Any]:
    return {field: encode_value(field, value) for field, value in row.items()}


def decode_value(field: str, value: Any) -> Any:
    """Restore JSON values to the types consumed by draft validation."""
    if value is None:
        return None
    if field in DATE_FIELDS:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value))
    if field in BOOLEAN_FIELDS:
        return bool(value)
    if field in INTEGER_FIELDS:
        return int(value) if isinstance(value, Real) and not isinstance(value, bool) else value
    if field in NUMBER_FIELDS:
        return float(value) if isinstance(value, Real) and not isinstance(value, bool) else value
    return value


def _decode_row(row: dict[str, Any]) -> dict[str, Any]:
    return {field: decode_value(field, value) for field, value in row.items()}


def apply_component_payload(state: Any, payload: dict[str, Any] | None, *,
                            source_version: int | None = None,
                            editable_fields: set[str] | None = None,
                            postprocess: Callable | None = None) -> list[dict[str, Any]]:
    """Apply every unseen semantic event and acknowledge its client revision."""
    rows = [dict(row) for row in state.get("orders_draft_rows", [])]
    if not payload:
        return rows
    # Streamlit retains a component's last value under its widget key.  After
    # an authoritative source replacement it can therefore deliver a payload
    # produced by the previous iframe before the new iframe has rendered.
    # Reject it before touching rows, revisions or flush protocol state.
    if source_version is not None and payload.get("source_version") != source_version:
        return rows
    ack = int(state.get("orders_component_ack_revision", 0))
    for raw in sorted(payload.get("events", []), key=lambda event: int(event["client_revision"])):
        revision = int(raw["client_revision"])
        if revision <= ack:
            continue
        before = deepcopy(rows)
        key = raw["row_key"]
        row = next((item for item in rows if stable_row_key(item) == key), None)
        if row is None:
            continue
        field = str(raw["field"])
        if editable_fields is not None and field not in editable_fields:
            continue
        row[field] = decode_value(field, raw.get("after"))
        if postprocess is not None:
            rows = postprocess(before, rows)
        if raw.get("action_type") != "selection" and not state.get("draft_history_replay_in_progress"):
            session_history(state).record(DraftAction(
                "orders", str(raw.get("action_type") or "cell"), before, deepcopy(rows),
                (key,), (field,), focus={"session_key": "orders_draft_rows"},
            ))
        ack = revision
    # A flush snapshot is authoritative for edits already made in the iframe,
    # including a change event delivered in the same browser turn as the click.
    flush_ack = payload.get("flush_ack")
    expected_flush = state.get("orders_component_flush_request")
    if flush_ack and flush_ack == expected_flush and payload.get("snapshot") is not None:
        snapshot = [_decode_row(dict(row)) for row in payload["snapshot"]]
        if editable_fields is not None:
            snapshot_by_key = {stable_row_key(row): row for row in snapshot}
            snapshot = [
                {
                    **row,
                    **{
                        field: incoming[field]
                        for field in editable_fields
                        if field in incoming
                    },
                }
                for row in rows
                if (incoming := snapshot_by_key.get(stable_row_key(row))) is not None
            ]
        reconciled = postprocess(rows, snapshot) if postprocess is not None else snapshot
        # The browser snapshot is authoritative at a flush barrier.  Normally
        # the matching change event was handled above, but an input that is
        # still active when the export/recalculation button is clicked can
        # arrive only in this snapshot.  Record that business difference so a
        # database transfer cannot silently export the older SQLite value.
        business_fields: set[str] = set()
        old_by_key = {stable_row_key(row): row for row in rows}
        for row in reconciled:
            old = old_by_key.get(stable_row_key(row), {})
            business_fields.update(
                field for field, value in row.items()
                if (editable_fields is None or field in editable_fields)
                and field != "Выбран" and old.get(field) != value
            )
        if business_fields and not state.get("draft_history_replay_in_progress"):
            session_history(state).record(DraftAction(
                "orders", "snapshot", deepcopy(rows), deepcopy(reconciled),
                tuple(stable_row_key(row) for row in reconciled),
                tuple(sorted(business_fields)),
                focus={"session_key": "orders_draft_rows"},
            ))
        rows = reconciled
        state["orders_component_flush_ack"] = flush_ack
    state["orders_component_ack_revision"] = max(ack, int(payload.get("client_revision", ack)))
    state["orders_draft_rows"] = rows
    return rows


def orders_component(rows: list[dict[str, Any]], *, source_version: int, columns: list[str],
                     read_only: list[str], options: dict[str, list[str]], postprocess=None) -> list[dict[str, Any]]:
    """Render the bundled component; same-source arguments never replace browser rows."""
    # One-run migration bridge for sessions (and extensions) that still carry
    # the former data_editor delta.  No data_editor is rendered or owns state.
    legacy = st.session_state.pop("orders_page_editor", None)
    if isinstance(legacy, dict) and legacy.get("edited_rows"):
        revision = int(st.session_state.get("orders_component_ack_revision", 0))
        events = []
        for index, changes in legacy["edited_rows"].items():
            index = int(index)
            if index >= len(rows):
                continue
            key = stable_row_key(rows[index])
            for field, after in changes.items():
                revision += 1
                events.append({"row_key": key, "field": field,
                               "before": rows[index].get(field), "after": after,
                               "client_revision": revision,
                               "action_type": "selection" if field == "Выбран" else "cell"})
        rows = apply_component_payload(st.session_state, {
            "client_revision": revision, "events": events,
        }, editable_fields=set(columns) - set(read_only), postprocess=postprocess)
    flush_token = st.session_state.get("orders_component_flush_request")
    component_rows = [_encode_row(dict(row)) for row in rows]
    payload = _component(
        rows=component_rows, source_version=source_version,
        server_ack_revision=int(st.session_state.get("orders_component_ack_revision", 0)),
        flush_token=flush_token, columns=columns, read_only=read_only, options=options,
        key="orders_browser_grid", default=None,
    )
    return apply_component_payload(
        st.session_state, payload, source_version=source_version,
        editable_fields=set(columns) - set(read_only), postprocess=postprocess,
    )
