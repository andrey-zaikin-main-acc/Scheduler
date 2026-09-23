import json
from datetime import date, datetime

from app.db.models import Order
from app.services.draft_history_service import session_history
from app.ui.components import orders_component as component_module
from app.ui.components.orders_component import (
    DATE_FIELDS,
    ORDERS_GRID_ID,
    _encode_row,
    apply_component_payload,
    decode_value,
    encode_value,
)
from app.ui.components.tables import order_rows
from app.ui.pages.orders_page import reconcile_linked_groups
from app.ui.pages.common import _has_unsaved_changes


def event(revision, key, field, before, after, action="cell"):
    return {"client_revision": revision, "row_key": key, "field": field,
            "before": before, "after": after, "action_type": action}


def test_foreign_grid_payload_is_ignored_even_with_matching_row_and_version():
    state = {
        "orders_draft_rows": [{"ID": 1, "Клиент": "Заказчик", "Выбран": False}],
        "orders_component_ack_revision": 5,
        "orders_component_flush_request": "orders-flush",
    }
    payload = {
        "grid_id": "routes_page_route_editor", "source_version": 9,
        "client_revision": 6,
        "events": [event(6, 1, "Выбран", False, True, "selection")],
        "flush_ack": "orders-flush",
        "snapshot": [{"ID": 1, "Клиент": "Маршрут", "Выбран": True}],
    }

    rows = apply_component_payload(
        state, payload, source_version=9, grid_id=ORDERS_GRID_ID,
        editable_fields={"Клиент", "Выбран"},
    )

    assert rows == [{"ID": 1, "Клиент": "Заказчик", "Выбран": False}]
    assert state["orders_component_ack_revision"] == 5
    assert "orders_component_flush_ack" not in state
    assert not session_history(state).undo_stack


def test_outbound_encoding_is_json_safe_and_dates_round_trip():
    row = {
        "Заданная дата запуска": date(2026, 8, 13),
        "Заданная дата отгрузки": date(2026, 8, 14),
        "Расчётная дата запуска": date(2026, 8, 15),
        "Расчётная дата отгрузки": date(2026, 8, 16),
        "Пустое": None,
        "Приоритет": 3,
        "Тираж": 12.5,
        "Выбран": True,
        "Клиент": "Заказчик",
        "_draft_id": -8,
        "ID": 42,
    }

    encoded = _encode_row(row)

    assert json.loads(json.dumps(encoded, ensure_ascii=False)) == encoded
    assert {field: encoded[field] for field in DATE_FIELDS} == {
        "Заданная дата запуска": "2026-08-13",
        "Заданная дата отгрузки": "2026-08-14",
        "Расчётная дата запуска": "2026-08-15",
        "Расчётная дата отгрузки": "2026-08-16",
    }
    assert {field: decode_value(field, encoded[field]) for field in DATE_FIELDS} == {
        field: row[field] for field in DATE_FIELDS
    }
    for field in ("Пустое", "Приоритет", "Тираж", "Выбран", "Клиент", "_draft_id", "ID"):
        assert encoded[field] == row[field]
        assert type(encoded[field]) is type(row[field])


def test_encode_value_supports_datetime_without_changing_business_date():
    value = datetime(2026, 8, 13, 9, 30)
    assert encode_value("timestamp", value) == "2026-08-13T09:30:00"
    assert encode_value("Заданная дата запуска", date(2026, 8, 13)) == "2026-08-13"


def test_orders_component_production_args_are_json_safe_without_mutating_draft(monkeypatch):
    row = order_rows([Order(
        id=17, priority=1, order_number="ORD-17", client_name="A",
        product_name="Product", quantity=1000.0, planning_mode="От даты запуска",
        fixed_start_date=date(2026, 8, 13), shipment_date=date(2026, 8, 14),
        calculated_start_date=date(2026, 8, 15),
        calculated_shipment_date=date(2026, 8, 16), status="Новый",
    )])[0]
    state = {"orders_draft_rows": [row]}
    captured = {}

    def component(**kwargs):
        captured.update(kwargs)
        json.dumps(kwargs, ensure_ascii=False)
        return None

    monkeypatch.setattr(component_module.st, "session_state", state)
    monkeypatch.setattr(component_module, "_component", component)
    result = component_module.orders_component(
        state["orders_draft_rows"], source_version=7, columns=list(row),
        read_only=["Расчётная дата запуска", "Расчётная дата отгрузки"], options={},
    )

    assert captured["rows"][0]["Заданная дата запуска"] == "2026-08-13"
    assert captured["rows"][0]["Расчётная дата отгрузки"] == "2026-08-16"
    assert captured["grid_id"] == ORDERS_GRID_ID
    assert result[0]["Заданная дата запуска"] == date(2026, 8, 13)
    assert state["orders_draft_rows"][0]["Расчётная дата отгрузки"] == date(2026, 8, 16)


def test_component_events_preserve_types_ids_and_per_edit_history():
    state = {"orders_draft_rows": [
        {"ID": 7, "_draft_id": -9, "Тираж": 10.0, "Выбран": False,
         "Заданная дата запуска": date(2026, 8, 14), "Клиент": "A"}
    ]}
    payload = {"client_revision": 4, "events": [
        event(1, 7, "Тираж", 10, 15.5),
        event(2, 7, "Клиент", "A", "B"),
        event(3, 7, "Заданная дата запуска", "2026-08-14", "2026-08-12"),
        event(4, 7, "Выбран", False, True, "selection"),
    ]}
    rows = apply_component_payload(state, payload)
    assert rows[0]["ID"] == 7 and rows[0]["_draft_id"] == -9
    assert rows[0]["Тираж"] == 15.5 and isinstance(rows[0]["Тираж"], float)
    assert rows[0]["Заданная дата запуска"] == date(2026, 8, 12)
    assert rows[0]["Выбран"] is True
    assert len(session_history(state).undo_stack) == 3
    assert [a.fields for a in session_history(state).undo_stack] == [("Тираж",), ("Клиент",), ("Заданная дата запуска",)]


def test_old_ack_is_idempotent_and_replay_does_not_record():
    state = {"orders_draft_rows": [{"_draft_id": -1, "Клиент": "A"}]}
    payload = {"client_revision": 1, "events": [event(1, -1, "Клиент", "A", "B")]}
    apply_component_payload(state, payload)
    apply_component_payload(state, payload)
    assert len(session_history(state).undo_stack) == 1
    state["draft_history_replay_in_progress"] = True
    apply_component_payload(state, {"client_revision": 2, "events": [event(2, -1, "Клиент", "B", "C")]})
    assert len(session_history(state).undo_stack) == 1


def test_linked_group_event_remains_one_atomic_action():
    state = {"orders_draft_rows": [
        {"ID": 1, "Группа": "G", "Связанные заказы": False},
        {"ID": 2, "Группа": "G", "Связанные заказы": False},
    ]}
    rows = apply_component_payload(state, {"client_revision": 1, "events": [
        event(1, 2, "Связанные заказы", False, True, "checkbox")
    ]}, postprocess=reconcile_linked_groups)
    assert [row["Связанные заказы"] for row in rows] == [True, True]
    action = session_history(state).undo_stack[0]
    assert [row["Связанные заказы"] for row in action.after] == [True, True]


def test_flush_snapshot_decodes_date_before_bundle_creation():
    state = {"orders_draft_rows": [{"_draft_id": -1, "Заданная дата отгрузки": date(2026, 8, 14)}],
             "orders_component_flush_request": "token"}
    rows = apply_component_payload(state, {"client_revision": 1, "events": [], "flush_ack": "token",
        "snapshot": [{"_draft_id": -1, "Заданная дата отгрузки": "2026-08-12", "Выбран": False, "Тираж": 1000}]})
    assert rows[0]["Заданная дата отгрузки"] == date(2026, 8, 12)
    assert state["orders_component_flush_ack"] == "token"


def test_active_cell_flush_snapshot_is_recorded_as_unsaved_change():
    state = {"orders_draft_rows": [
        {"ID": 7, "Клиент": "До редактирования", "Выбран": False}
    ], "orders_component_flush_request": "export-token"}

    rows = apply_component_payload(state, {
        "client_revision": 0,
        "events": [],
        "flush_ack": "export-token",
        "snapshot": [{"ID": 7, "Клиент": "Активное значение", "Выбран": False}],
    })

    assert rows[0]["Клиент"] == "Активное значение"
    assert state["orders_component_flush_ack"] == "export-token"
    action = session_history(state).undo_stack[-1]
    assert action.section == "orders"
    assert action.action_type == "snapshot"
    assert action.fields == ("Клиент",)


def test_old_generation_payload_cannot_restore_saved_rows_or_ack_new_flush():
    columns = {"Клиент", "Выбран"}
    state = {
        "orders_draft_rows": [{"ID": 7, "Клиент": "До", "Выбран": False}],
        "orders_component_flush_request": "save-1",
    }
    current = {"source_version": 4, "client_revision": 1,
               "events": [event(1, 7, "Клиент", "До", "После")],
               "flush_ack": "save-1",
               "snapshot": [{"ID": 7, "Клиент": "После", "Выбран": False}]}
    apply_component_payload(state, current, source_version=4, editable_fields=columns)
    assert state["orders_draft_rows"][0]["Клиент"] == "После"
    assert state["orders_component_flush_ack"] == "save-1"

    # Model the successful commit/reload performed by commit_all_session_drafts.
    session_history(state).clear_section("orders")
    state["orders_draft_rows"] = [{"ID": 7, "Клиент": "Из базы", "Выбран": False}]
    state.pop("orders_component_ack_revision")
    state.pop("orders_component_flush_ack")
    state["orders_component_flush_request"] = "load-probe"

    apply_component_payload(state, current, source_version=5, editable_fields=columns)

    assert state["orders_draft_rows"][0]["Клиент"] == "Из базы"
    assert not session_history(state).undo_stack
    assert "orders_component_ack_revision" not in state
    assert "orders_component_flush_ack" not in state
    assert not _has_unsaved_changes(state)

    new_payload = {"source_version": 5, "client_revision": 1,
                   "events": [event(1, 7, "Клиент", "Из базы", "Новое")]}
    apply_component_payload(state, new_payload, source_version=5, editable_fields=columns)
    assert state["orders_draft_rows"][0]["Клиент"] == "Новое"
    assert len(session_history(state).undo_stack) == 1


def test_flush_ignores_readonly_snapshot_changes_and_requires_current_token():
    editable = {"Клиент", "Выбран"}
    state = {
        "orders_draft_rows": [{"ID": 7, "Клиент": "A", "Расчёт": 10, "Выбран": False}],
        "orders_component_flush_request": "new-token",
    }
    payload = {"source_version": 2, "client_revision": 0, "events": [],
               "flush_ack": "old-token",
               "snapshot": [{"ID": 7, "Клиент": "A", "Расчёт": 99, "Выбран": False}]}
    apply_component_payload(state, payload, source_version=2, editable_fields=editable)
    assert state["orders_draft_rows"][0]["Расчёт"] == 10
    assert "orders_component_flush_ack" not in state
    assert not session_history(state).undo_stack

    payload["flush_ack"] = "new-token"
    apply_component_payload(state, payload, source_version=2, editable_fields=editable)
    assert state["orders_component_flush_ack"] == "new-token"
    assert state["orders_draft_rows"][0]["Расчёт"] == 10
    assert not session_history(state).undo_stack
