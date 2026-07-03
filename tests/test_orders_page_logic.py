from datetime import date

import pytest

pytest.importorskip("streamlit")
from app.constants import ORDER_STATUS_NEW, ORDER_STATUS_PLANNED
from app.db.models import Order, Route
from app.ui.pages.orders_page import build_order_editor_rows, validate_order_editor_row


def test_order_editor_rows_include_selection_and_editable_fields() -> None:
    route = Route(id=1, name="наша сборка")
    order = Order(
        id=10,
        order_number="O-10",
        client_name="Клиент",
        product_name="Продукт",
        quantity=1000,
        shipment_date=date(2026, 7, 10),
        route_id=1,
        route=route,
        status=ORDER_STATUS_NEW,
    )

    rows = build_order_editor_rows([order], selected_order_id=10, include_draft=True)

    assert rows[0] == {
        "Выбран": True,
        "ID": 10,
        "Номер": "O-10",
        "Клиент": "Клиент",
        "Продукция": "Продукт",
        "Тираж": 1000,
        "Срок отгрузки": date(2026, 7, 10),
        "Маршрут": "наша сборка",
        "Статус": ORDER_STATUS_NEW,
        "Дата запуска": None,
        "Конфликт": False,
    }
    assert rows[1]["ID"] is None
    assert rows[1]["Статус"] == ORDER_STATUS_NEW


def test_validate_order_editor_row_rejects_duplicate_order_number() -> None:
    row = {
        "Номер": "DUP-1",
        "Клиент": "Клиент",
        "Продукция": "Продукт",
        "Тираж": 1000,
        "Срок отгрузки": date(2026, 7, 10),
        "Маршрут": "наша сборка",
        "Статус": ORDER_STATUS_NEW,
    }

    errors = validate_order_editor_row(
        row,
        route_names={"наша сборка"},
        existing_numbers={"DUP-1": 1},
        current_order_id=None,
    )

    assert "Заказ с таким номером уже существует." in errors


def test_validate_order_editor_row_accepts_current_order_number_on_update() -> None:
    row = {
        "Номер": "DUP-1",
        "Клиент": "Клиент",
        "Продукция": "Продукт",
        "Тираж": 1000,
        "Срок отгрузки": date(2026, 7, 10),
        "Маршрут": "наша сборка",
        "Статус": ORDER_STATUS_NEW,
    }

    errors = validate_order_editor_row(
        row,
        route_names={"наша сборка"},
        existing_numbers={"DUP-1": 1},
        current_order_id=1,
    )

    assert errors == []

class _RerunRequested(Exception):
    pass


class _FakeStreamlit:
    def __init__(self) -> None:
        self.session_state = {}
        self.warning_messages = []
        self.error_messages = []

    def rerun(self) -> None:
        raise _RerunRequested

    def warning(self, message: str) -> None:
        self.warning_messages.append(message)

    def error(self, message: str) -> None:
        self.error_messages.append(message)


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class _FakeOrdersRepository:
    def __init__(self) -> None:
        self.created = []
        self.updated = []

    def create_order(self, **payload):
        self.created.append(payload)
        return payload

    def update_order(self, order_id: int, **payload):
        self.updated.append((order_id, payload))
        return payload


def _order_row(order: Order, *, selected: bool = False) -> dict:
    return {
        "Выбран": selected,
        "ID": order.id,
        "Номер": order.order_number,
        "Клиент": order.client_name,
        "Продукция": order.product_name,
        "Тираж": float(order.quantity),
        "Срок отгрузки": order.shipment_date,
        "Маршрут": order.route.name,
        "Статус": order.status,
        "Дата запуска": order.calculated_start_date,
        "Конфликт": False,
    }


def _order(route: Route | None = None) -> Order:
    route = route or Route(id=1, name="наша сборка")
    return Order(
        id=10,
        order_number="O-10",
        client_name="Клиент",
        product_name="Продукт",
        quantity=1000,
        shipment_date=date(2026, 7, 10),
        route_id=route.id,
        route=route,
        status=ORDER_STATUS_NEW,
    )


def test_opening_orders_page_does_not_save_or_recalculate(monkeypatch) -> None:
    import app.ui.pages.orders_page as orders_page

    fake_st = _FakeStreamlit()
    repository = _FakeOrdersRepository()
    recalculations = []
    order = _order()

    monkeypatch.setattr(orders_page, "st", fake_st)
    monkeypatch.setattr(
        orders_page, "recalculate_after_save", lambda session: recalculations.append(session)
    )

    orders_page._process_editor_changes(
        _FakeSession(),
        repository,
        [order],
        [_order_row(order)],
        {order.route.name: order.route},
        save_requested=False,
    )

    assert repository.updated == []
    assert recalculations == []


def test_navigation_to_orders_page_with_stale_editor_row_does_not_recalculate(monkeypatch) -> None:
    import app.ui.pages.orders_page as orders_page

    fake_st = _FakeStreamlit()
    repository = _FakeOrdersRepository()
    recalculations = []
    order = _order()
    stale_row = {**_order_row(order), "Тираж": 2000.0}

    monkeypatch.setattr(orders_page, "st", fake_st)
    monkeypatch.setattr(
        orders_page, "recalculate_after_save", lambda session: recalculations.append(session)
    )

    orders_page._process_editor_changes(
        _FakeSession(),
        repository,
        [order],
        [stale_row],
        {order.route.name: order.route},
        save_requested=False,
    )

    assert repository.updated == []
    assert recalculations == []


def test_selecting_and_clearing_checkbox_only_changes_selection(monkeypatch) -> None:
    import app.ui.pages.orders_page as orders_page

    fake_st = _FakeStreamlit()
    repository = _FakeOrdersRepository()
    recalculations = []
    order = _order()

    monkeypatch.setattr(orders_page, "st", fake_st)
    monkeypatch.setattr(
        orders_page, "recalculate_after_save", lambda session: recalculations.append(session)
    )

    with pytest.raises(_RerunRequested):
        orders_page._process_editor_changes(
            _FakeSession(),
            repository,
            [order],
            [_order_row(order, selected=True)],
            {order.route.name: order.route},
            save_requested=False,
        )
    assert fake_st.session_state[orders_page.SELECTED_ORDER_SESSION_KEY] == order.id
    assert repository.updated == []
    assert recalculations == []

    with pytest.raises(_RerunRequested):
        orders_page._process_editor_changes(
            _FakeSession(),
            repository,
            [order],
            [_order_row(order, selected=False)],
            {order.route.name: order.route},
            save_requested=False,
        )
    assert fake_st.session_state[orders_page.SELECTED_ORDER_SESSION_KEY] is None
    assert repository.updated == []
    assert recalculations == []


def test_save_changed_planning_fields_updates_and_recalculates_once(monkeypatch) -> None:
    import app.ui.pages.orders_page as orders_page

    fake_st = _FakeStreamlit()
    repository = _FakeOrdersRepository()
    session = _FakeSession()
    recalculations = []
    route = Route(id=1, name="наша сборка")
    new_route = Route(id=2, name="аутсорс")
    order = _order(route)
    edited_row = {
        **_order_row(order),
        "Тираж": 1500.0,
        "Срок отгрузки": date(2026, 7, 15),
        "Маршрут": new_route.name,
        "Статус": ORDER_STATUS_PLANNED,
    }

    monkeypatch.setattr(orders_page, "st", fake_st)
    monkeypatch.setattr(
        orders_page, "recalculate_after_save", lambda session: recalculations.append(session)
    )

    with pytest.raises(_RerunRequested):
        orders_page._process_editor_changes(
            session,
            repository,
            [order],
            [edited_row],
            {route.name: route, new_route.name: new_route},
            save_requested=True,
        )

    assert len(repository.updated) == 1
    assert repository.updated[0][0] == order.id
    assert repository.updated[0][1]["quantity"] == 1500.0
    assert repository.updated[0][1]["shipment_date"] == date(2026, 7, 15)
    assert repository.updated[0][1]["route_id"] == new_route.id
    assert repository.updated[0][1]["status"] == ORDER_STATUS_PLANNED
    assert session.commits == 1
    assert recalculations == [session]


def test_reopening_after_save_without_save_button_does_not_recalculate(monkeypatch) -> None:
    import app.ui.pages.orders_page as orders_page

    fake_st = _FakeStreamlit()
    repository = _FakeOrdersRepository()
    recalculations = []
    order = _order()
    order.quantity = 1500

    monkeypatch.setattr(orders_page, "st", fake_st)
    monkeypatch.setattr(
        orders_page, "recalculate_after_save", lambda session: recalculations.append(session)
    )

    orders_page._process_editor_changes(
        _FakeSession(),
        repository,
        [order],
        [_order_row(order)],
        {order.route.name: order.route},
        save_requested=False,
    )

    assert repository.updated == []
    assert recalculations == []
