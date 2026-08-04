"""Production draft lifecycle regressions for the common orders table."""
from datetime import date
from types import SimpleNamespace

from app.constants import ORDER_STATUS_NEW, PLANNING_MODE_START
from app.ui.pages import orders_page


class State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


def test_sequential_cell_edits_never_reset_widget_state(monkeypatch):
    state = State()
    monkeypatch.setattr(orders_page, "st", SimpleNamespace(session_state=state))
    row = {"ID": 1, "Тираж": 100, "Маршрут": "A", "Режим планирования": "От даты отгрузки",
           "Заданная дата запуска": None, "Приоритет": 1, "Статус": ORDER_STATUS_NEW}
    state[orders_page.ORDER_EDITOR_KEY] = {"edited_rows": {}}
    orders_page.replace_order_editor_source("database-load")
    orders_page._sync_order_editor_state([row])
    state[orders_page.ORDER_EDITOR_KEY] = {"edited_rows": {0: {"Тираж": 200}}}
    for field, value in (("Тираж", 200), ("Маршрут", "B"), ("Режим планирования", PLANNING_MODE_START),
                         ("Заданная дата запуска", date(2026, 8, 4)), ("Приоритет", 9), ("Статус", "Отменён")):
        row[field] = value
        marker = state[orders_page.ORDER_EDITOR_KEY]
        orders_page._sync_order_editor_state([row])
        assert state[orders_page.ORDER_EDITOR_KEY] is marker
    assert [row[k] for k in ("Тираж", "Маршрут", "Режим планирования", "Заданная дата запуска", "Приоритет", "Статус")] == [200, "B", PLANNING_MODE_START, date(2026, 8, 4), 9, "Отменён"]


def test_explicit_snapshot_replacement_resets_editor(monkeypatch):
    state = State({orders_page.ORDER_EDITOR_KEY: {"edited_rows": {}}})
    monkeypatch.setattr(orders_page, "st", SimpleNamespace(session_state=state))
    orders_page.replace_order_editor_source("undo")
    orders_page._sync_order_editor_state([])
    assert orders_page.ORDER_EDITOR_KEY not in state


def test_linked_group_checkbox_is_atomic_and_single_is_unlinked():
    previous = [{"ID": 1, "Группа": "G", "Связанные заказы": False},
                {"ID": 2, "Группа": "G", "Связанные заказы": False},
                {"ID": 3, "Группа": "", "Связанные заказы": False}]
    edited = [dict(row) for row in previous]
    edited[1]["Связанные заказы"] = True
    edited[2]["Связанные заказы"] = True
    result = orders_page.reconcile_linked_groups(previous, edited)
    assert [row["Связанные заказы"] for row in result] == [True, True, False]
