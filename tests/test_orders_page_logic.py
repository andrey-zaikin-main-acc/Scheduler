from datetime import date, timedelta

import pytest

pytest.importorskip("streamlit")
from app.constants import ORDER_STATUS_CANCELLED, ORDER_STATUS_CONFLICT, ORDER_STATUS_NEW, ORDER_STATUS_PLANNED, MANUAL_ORDER_STATUSES
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
        orders_page,
        "recalculate_after_save",
        lambda session: recalculations.append(session),
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


def test_navigation_to_orders_page_with_stale_editor_row_does_not_recalculate(
    monkeypatch,
) -> None:
    import app.ui.pages.orders_page as orders_page

    fake_st = _FakeStreamlit()
    repository = _FakeOrdersRepository()
    recalculations = []
    order = _order()
    stale_row = {**_order_row(order), "Тираж": 2000.0}

    monkeypatch.setattr(orders_page, "st", fake_st)
    monkeypatch.setattr(
        orders_page,
        "recalculate_after_save",
        lambda session: recalculations.append(session),
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
        orders_page,
        "recalculate_after_save",
        lambda session: recalculations.append(session),
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


def test_save_changed_planning_fields_updates_and_recalculates_once(
    monkeypatch,
) -> None:
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
        "Статус": ORDER_STATUS_NEW,
    }

    monkeypatch.setattr(orders_page, "st", fake_st)
    monkeypatch.setattr(
        orders_page,
        "recalculate_after_save",
        lambda session: recalculations.append(session),
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
    assert repository.updated[0][1]["status"] == ORDER_STATUS_NEW
    assert session.commits == 1
    assert recalculations == [session]


def test_reopening_after_save_without_save_button_does_not_recalculate(
    monkeypatch,
) -> None:
    import app.ui.pages.orders_page as orders_page

    fake_st = _FakeStreamlit()
    repository = _FakeOrdersRepository()
    recalculations = []
    order = _order()
    order.quantity = 1500

    monkeypatch.setattr(orders_page, "st", fake_st)
    monkeypatch.setattr(
        orders_page,
        "recalculate_after_save",
        lambda session: recalculations.append(session),
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


class _FakeColumn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def metric(self, *args, **kwargs):
        pass


class _FakeExpander(_FakeColumn):
    pass


class _FakeRouteCapacityStreamlit(_FakeStreamlit):
    def __init__(
        self, *, clicked: set[str] | None = None, quantity: float = 0.0
    ) -> None:
        super().__init__()
        self.clicked = clicked or set()
        self.quantity = quantity
        self.buttons = []
        self.dataframes = []
        self.info_messages = []
        self.write_messages = []

    def subheader(self, message: str) -> None:
        pass

    def caption(self, message: str) -> None:
        pass

    def columns(self, count: int):
        return [_FakeColumn() for _ in range(count)]

    def date_input(self, *args, **kwargs):
        return kwargs["value"]

    def selectbox(self, *args, **kwargs):
        options = kwargs["options"]
        return options[0] if options else None

    def number_input(self, *args, **kwargs):
        return self.quantity

    def button(self, label: str, **kwargs):
        self.buttons.append((label, kwargs))
        return label in self.clicked

    def info(self, message: str) -> None:
        self.info_messages.append(message)

    def write(self, message: str) -> None:
        self.write_messages.append(message)

    def dataframe(self, rows, **kwargs):
        self.dataframes.append(rows)

    def expander(self, label: str):
        return _FakeExpander()


def test_capacity_not_calculated_on_plain_render(monkeypatch) -> None:
    import app.ui.pages.orders_page as orders_page

    fake_st = _FakeRouteCapacityStreamlit()
    route = Route(id=1, name="маршрут")
    calls = []

    class FakeService:
        def __init__(self, session):
            pass

        def calculate_route_capacity(self, *args):
            calls.append(args)
            raise AssertionError("capacity must not be calculated on render")

    monkeypatch.setattr(orders_page, "st", fake_st)
    monkeypatch.setattr(orders_page, "RouteCapacityService", FakeService)

    orders_page._render_route_capacity_check(object(), [route])

    assert calls == []
    assert any(label == "Рассчитать доступный тираж" for label, _ in fake_st.buttons)


def test_capacity_calculated_only_by_calculate_button(monkeypatch) -> None:
    import app.ui.pages.orders_page as orders_page
    from app.services.route_capacity_service import RouteCapacityResult

    fake_st = _FakeRouteCapacityStreamlit(clicked={"Рассчитать доступный тираж"})
    route = Route(id=1, name="маршрут")
    calls = []
    result = RouteCapacityResult(route.id, route.name, 1000, "участок")

    class FakeService:
        def __init__(self, session):
            pass

        def calculate_route_capacity(self, *args):
            calls.append(args)
            return result

    monkeypatch.setattr(orders_page, "st", fake_st)
    monkeypatch.setattr(orders_page, "RouteCapacityService", FakeService)

    orders_page._render_route_capacity_check(object(), [route])

    saved_params = fake_st.session_state[orders_page.ROUTE_CAPACITY_RESULT_SESSION_KEY][
        "params"
    ]
    assert calls == [saved_params]
    assert (
        fake_st.session_state[orders_page.ROUTE_CAPACITY_RESULT_SESSION_KEY]["result"]
        is result
    )


def test_zero_quantity_stops_before_slot_service(monkeypatch) -> None:
    import app.ui.pages.orders_page as orders_page
    from app.services.route_capacity_service import RouteCapacityResult

    fake_st = _FakeRouteCapacityStreamlit(
        clicked={"Показать свободные слоты отгрузки"}, quantity=0.0
    )
    route = Route(id=1, name="маршрут")
    period_start = date.today().replace(day=1)
    next_month = (period_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    period_end = next_month - timedelta(days=1)
    fake_st.session_state[orders_page.ROUTE_CAPACITY_RESULT_SESSION_KEY] = {
        "params": (route.id, period_start, period_end),
        "result": RouteCapacityResult(route.id, route.name, 1000, "участок"),
    }
    calls = []

    class FakeService:
        def __init__(self, session):
            pass

        def find_available_shipment_slots_for_capacity(self, *args):
            calls.append(args)
            return []

    monkeypatch.setattr(orders_page, "st", fake_st)
    monkeypatch.setattr(orders_page, "RouteCapacityService", FakeService)

    orders_page._render_route_capacity_check(object(), [route])

    assert calls == []
    assert "Тираж должен быть больше 0" in fake_st.error_messages


def test_save_button_is_renamed_and_not_primary() -> None:
    source = __import__("pathlib").Path("app/ui/pages/orders_page.py").read_text()
    save_call = source.split("save_requested = st.button(", 1)[1].split(")", 1)[0]
    assert '"Сохранить изменения и пересчитать план"' in save_call
    assert 'type="primary"' not in save_call


def test_manual_status_options_only_include_new_and_cancelled() -> None:
    assert MANUAL_ORDER_STATUSES == (ORDER_STATUS_NEW, ORDER_STATUS_CANCELLED)


def test_validate_new_order_rejects_calculated_statuses() -> None:
    base = {
        "Номер": "N-1",
        "Клиент": "Клиент",
        "Продукция": "Продукт",
        "Тираж": 1000,
        "Срок отгрузки": date(2026, 7, 10),
        "Маршрут": "наша сборка",
    }
    for status in (ORDER_STATUS_PLANNED, ORDER_STATUS_CONFLICT, ORDER_STATUS_CANCELLED):
        errors = validate_order_editor_row(
            {**base, "Статус": status},
            route_names={"наша сборка"},
            existing_numbers={},
            current_order_id=None,
        )
        assert "Новый заказ можно создать только со статусом «Новый»." in errors


def test_validate_existing_order_allows_only_manual_statuses() -> None:
    base = {
        "Номер": "N-1",
        "Клиент": "Клиент",
        "Продукция": "Продукт",
        "Тираж": 1000,
        "Срок отгрузки": date(2026, 7, 10),
        "Маршрут": "наша сборка",
    }
    for status in (ORDER_STATUS_NEW, ORDER_STATUS_CANCELLED):
        assert validate_order_editor_row(
            {**base, "Статус": status},
            route_names={"наша сборка"},
            existing_numbers={"N-1": 1},
            current_order_id=1,
        ) == []
    for status in (ORDER_STATUS_PLANNED, ORDER_STATUS_CONFLICT):
        errors = validate_order_editor_row(
            {**base, "Статус": status},
            route_names={"наша сборка"},
            existing_numbers={"N-1": 1},
            current_order_id=1,
        )
        assert "Вручную можно назначить только статус «Новый» или «Отменён»." in errors


def test_route_capacity_cache_uses_planning_data_version(monkeypatch) -> None:
    import app.ui.pages.orders_page as orders_page
    from app.services.route_capacity_service import RouteCapacityResult

    route = Route(id=1, name="маршрут")
    period_start = date(2026, 7, 3)
    period_end = date(2026, 7, 31)
    fake_st = _FakeRouteCapacityStreamlit()
    old_result = RouteCapacityResult(route.id, route.name, 100, "старый участок")
    fake_st.session_state[orders_page.ROUTE_CAPACITY_RESULT_SESSION_KEY] = {
        "params": (route.id, period_start, period_end),
        "version": (1, 1, 1, 1, 1),
        "result": old_result,
    }

    monkeypatch.setattr(orders_page, "st", fake_st)
    monkeypatch.setattr(
        orders_page,
        "_planning_data_version",
        lambda session: (2, 1, 1, 1, 1),
    )

    assert (
        orders_page._get_current_capacity_result(
            object(), route.id, period_start, period_end
        )
        is None
    )
