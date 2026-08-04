"""Integration coverage for the production Streamlit undo/redo flow."""

from copy import deepcopy

from sqlalchemy import func, select
from streamlit.testing.v1 import AppTest

from app.db.database import SessionLocal
from app.db.models import Order, PlannedOperation, PlanningConflict
from app.services.draft_history_service import DraftAction


def _orders_row(quantity=100.0, priority=1):
    return {
        "Выбран": False, "ID": 901, "Приоритет": priority, "Номер": "T-1",
        "Клиент": "Test", "Продукция": "Box", "Тираж": quantity,
        "Режим планирования": "От даты отгрузки", "Заданная дата запуска": None,
        "Заданная дата отгрузки": None, "Расчётная дата запуска": None,
        "Расчётная дата отгрузки": None, "Группа": "", "Связанные заказы": False,
        "Маршрут": None, "Статус": "Новый", "Запланирован": False,
        "Конфликт планирования": False,
    }


def _app_with_order():
    app = AppTest.from_file("app/main.py", default_timeout=20).run()
    app.session_state["orders_draft_rows"] = [_orders_row()]
    app.session_state["orders_page_editor_source_version"] = 100
    return app.run()


def _history_buttons(app):
    return {button.label: button for button in app.button
            if button.label in {"Назад", "Вперёд"}}


def _db_counts():
    with SessionLocal() as session:
        return tuple(session.scalar(select(func.count()).select_from(model))
                     for model in (Order, PlannedOperation, PlanningConflict))


def _edit(app, row, **values):
    app.session_state["orders_page_editor"] = {
        "edited_rows": {row: values}, "added_rows": [], "deleted_rows": []
    }
    return app.run()


def test_real_editor_cell_undo_redo_updates_draft_and_controls_without_db_write():
    before_db = _db_counts()
    app = _app_with_order()
    assert _history_buttons(app)["Назад"].disabled
    assert _history_buttons(app)["Вперёд"].disabled

    app = _edit(app, 0, Тираж=250.0)
    assert app.session_state["orders_draft_rows"][0]["Тираж"] == 250.0
    assert not _history_buttons(app)["Назад"].disabled
    assert _history_buttons(app)["Вперёд"].disabled

    app = _history_buttons(app)["Назад"].click().run()
    assert app.session_state["orders_draft_rows"][0]["Тираж"] == 100.0
    assert _history_buttons(app)["Назад"].disabled
    assert not _history_buttons(app)["Вперёд"].disabled

    app = _history_buttons(app)["Вперёд"].click().run()
    assert app.session_state["orders_draft_rows"][0]["Тираж"] == 250.0
    assert not _history_buttons(app)["Назад"].disabled
    assert _history_buttons(app)["Вперёд"].disabled
    assert _db_counts() == before_db


def test_sequential_editor_actions_and_new_branch_have_exact_stack_semantics():
    app = _app_with_order()
    app = _edit(app, 0, Тираж=200.0)
    app = _edit(app, 0, Приоритет=2)
    assert len(app.session_state["draft_history"].undo_stack) == 2
    app = _history_buttons(app)["Назад"].click().run()
    assert app.session_state["orders_draft_rows"][0]["Приоритет"] == 1
    assert len(app.session_state["draft_history"].redo_stack) == 1
    app = _edit(app, 0, Клиент="New branch")
    assert app.session_state["orders_draft_rows"][0]["Клиент"] == "New branch"
    assert len(app.session_state["draft_history"].undo_stack) == 2
    assert not app.session_state["draft_history"].redo_stack
    assert _history_buttons(app)["Вперёд"].disabled


def test_cross_section_replay_navigates_and_invalidates_own_editor():
    app = _app_with_order()
    with SessionLocal() as session:
        from app.db.models import Route
        route_id = session.scalar(select(Route.id).order_by(Route.id))
    if route_id is None:
        return
    before = [{"ID": 77, "№": 1, "Участок": "A"}]
    after = [{"ID": 77, "№": 1, "Участок": "B"}]
    app.session_state["route_operations_drafts_by_route_id"] = {route_id: deepcopy(after)}
    app.session_state["draft_history"].record(DraftAction(
        "operations", "cell", before, after, (77,), ("Участок",), route_id=route_id,
        focus={"session_key": "route_operations_drafts_by_route_id"},
    ))
    app = app.run()
    app = _history_buttons(app)["Назад"].click().run()
    assert app.session_state["current_page"] == "Маршруты"
    assert app.session_state["navigation_page"] == "Маршруты"
    assert app.session_state["requested_page"] == "Маршруты"
    assert not app.session_state["pending_navigation"]
    assert app.session_state["routes_page_selected_route_id"] == route_id
    restored = app.session_state["route_operations_drafts_by_route_id"][route_id][0]
    assert restored["ID"] == 77 and restored["Участок"] == "A"
    assert app.session_state[f"routes_page_operation_editor_{route_id}_source_version"] == 1


def test_mass_delete_snapshot_restores_pending_ids_and_temporary_rows_as_one_action():
    app = _app_with_order()
    persisted = _orders_row()
    temporary = {**_orders_row(), "ID": None, "_draft_id": -1, "Номер": "TMP"}
    before = [persisted, temporary]
    action = DraftAction(
        "orders", "delete", before, [], (901, -1), (),
        focus={"session_key": "orders_draft_rows", "pending_delete_key": "orders_pending_delete_ids",
               "pending_delete_before": set(), "pending_delete_after": {901}},
    )
    app.session_state["orders_draft_rows"] = []
    app.session_state["orders_pending_delete_ids"] = {901}
    app.session_state["draft_history"].record(action)
    app = app.run()
    app = _history_buttons(app)["Назад"].click().run()
    assert [row.get("ID") or row.get("_draft_id") for row in app.session_state["orders_draft_rows"]] == [901, -1]
    assert app.session_state["orders_pending_delete_ids"] == set()
    app = _history_buttons(app)["Вперёд"].click().run()
    assert app.session_state["orders_draft_rows"] == []
    assert app.session_state["orders_pending_delete_ids"] == {901}
