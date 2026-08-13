from datetime import date

from app.services.draft_history_service import session_history
from app.ui.components.orders_component import apply_component_payload
from app.ui.pages.orders_page import reconcile_linked_groups


def event(revision, key, field, before, after, action="cell"):
    return {"client_revision": revision, "row_key": key, "field": field,
            "before": before, "after": after, "action_type": action}


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
    state = {"orders_draft_rows": [{"_draft_id": -1, "Заданная дата отгрузки": date(2026, 8, 14)}]}
    rows = apply_component_payload(state, {"client_revision": 1, "events": [], "flush_ack": "token",
        "snapshot": [{"_draft_id": -1, "Заданная дата отгрузки": "2026-08-12", "Выбран": False, "Тираж": 1000}]})
    assert rows[0]["Заданная дата отгрузки"] == date(2026, 8, 12)
    assert state["orders_component_flush_ack"] == "token"
