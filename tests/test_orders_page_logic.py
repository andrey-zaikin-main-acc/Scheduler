from datetime import date, datetime, timedelta

import pytest

pytest.importorskip("streamlit")
from app.constants import (
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_NEW,
    ORDER_STATUS_PLANNED,
    MANUAL_ORDER_STATUSES,
    PLANNING_MODE_SHIPMENT,
    PLANNING_MODE_START,
)
from app.db.models import Order, Route
from app.ui.pages.orders_page import (
    _row_changed,
    _split_child_quantities,
    apply_order_status_overrides,
    build_order_editor_rows,
    order_status_options_for_row,
    READ_ONLY_EDITOR_COLUMNS,
    EDITOR_COLUMNS,
    apply_scheduling_overrides,
    reconcile_priority_move,
    normalize_editor_date,
    validate_order_editor_row,
)


def test_fractional_child_quantities_preserve_exact_total() -> None:
    quantities = _split_child_quantities(10.5, 3.2)
    assert quantities == pytest.approx([3.2, 3.2, 3.2, 0.9])
    assert sum(quantities) == pytest.approx(10.5)


def test_calculated_start_does_not_make_unchanged_row_dirty() -> None:
    order = _order()
    order.calculated_start_date = date(2026, 7, 5)
    assert not _row_changed(_order_row(order), order)


def test_shipment_planning_row_displays_calculated_start_date() -> None:
    order = _order()
    order.planning_mode = PLANNING_MODE_SHIPMENT
    order.calculated_start_date = date(2026, 7, 5)

    row = build_order_editor_rows([order], selected_order_id=None, include_draft=False)[
        0
    ]

    assert row["Заданная дата запуска"] is None
    assert row["Расчётная дата запуска"] == date(2026, 7, 5)


def test_start_planning_row_displays_fixed_and_calculated_start_dates() -> None:
    order = _order()
    order.planning_mode = PLANNING_MODE_START
    order.fixed_start_date = date(2026, 7, 5)
    order.calculated_start_date = date(2026, 7, 5)

    row = build_order_editor_rows([order], selected_order_id=None, include_draft=False)[
        0
    ]

    assert row["Заданная дата запуска"] == date(2026, 7, 5)
    assert row["Расчётная дата запуска"] == date(2026, 7, 5)


def test_calculated_start_column_is_read_only() -> None:
    assert "Расчётная дата запуска" in READ_ONLY_EDITOR_COLUMNS


def test_unchanged_calculated_start_is_never_copied_to_fixed_start() -> None:
    import app.ui.pages.orders_page as orders_page

    order = _order()
    order.calculated_start_date = date(2026, 7, 5)
    row = _order_row(order)

    assert not _row_changed(row, order)
    payload = orders_page._row_to_order_payload(row, {order.route.name: order.route})
    assert payload["fixed_start_date"] is None


def test_status_dropdown_displays_all_current_statuses() -> None:
    assert order_status_options_for_row(ORDER_STATUS_NEW) == [
        ORDER_STATUS_NEW,
        ORDER_STATUS_PLANNED,
        ORDER_STATUS_CANCELLED,
    ]
    assert order_status_options_for_row(ORDER_STATUS_PLANNED) == [
        ORDER_STATUS_NEW,
        ORDER_STATUS_PLANNED,
        ORDER_STATUS_CANCELLED,
    ]
    assert order_status_options_for_row(ORDER_STATUS_CANCELLED) == [
        ORDER_STATUS_NEW,
        ORDER_STATUS_PLANNED,
        ORDER_STATUS_CANCELLED,
    ]


def test_status_overrides_are_applied_per_row() -> None:
    rows = [
        {"ID": 1, "Статус": ORDER_STATUS_NEW},
        {"ID": 2, "Статус": ORDER_STATUS_PLANNED},
    ]

    edited = apply_order_status_overrides(
        rows, {0: ORDER_STATUS_CANCELLED, 1: ORDER_STATUS_NEW}
    )

    assert edited[0]["Статус"] == ORDER_STATUS_CANCELLED
    assert edited[1]["Статус"] == ORDER_STATUS_NEW
    assert rows[0]["Статус"] == ORDER_STATUS_NEW


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

    assert rows[0]["ID"] == 10
    assert rows[0]["Заданная дата отгрузки"] == date(2026, 7, 10)
    assert rows[0]["Запланирован"] is False
    assert rows[0]["Конфликт планирования"] is False
    assert rows[1]["ID"] is None
    assert rows[1]["Статус"] == ORDER_STATUS_NEW


def test_validate_order_editor_row_rejects_duplicate_order_number() -> None:
    row = {
        "Номер": "DUP-1",
        "Клиент": "Клиент",
        "Продукция": "Продукт",
        "Тираж": 1000,
        "Режим планирования": "От даты отгрузки",
        "Фиксированная дата запуска": None,
        "Расчётная дата запуска": None,
        "Срок отгрузки": date(2026, 7, 10),
        "Группа": "",
        "Связанная группа": False,
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
        "Режим планирования": "От даты отгрузки",
        "Фиксированная дата запуска": None,
        "Расчётная дата запуска": None,
        "Срок отгрузки": date(2026, 7, 10),
        "Группа": "",
        "Связанная группа": False,
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
        "Приоритет": order.priority or 1,
        "Режим планирования": order.planning_mode,
        "Срок отгрузки": order.shipment_date,
        "Группа": order.child_group_key or "",
        "Связанная группа": bool(order.is_linked_child_group),
        "Маршрут": order.route.name,
        "Статус": order.status,
        "Фиксированная дата запуска": order.fixed_start_date,
        "Расчётная дата запуска": order.calculated_start_date,
        "Конфликт": False,
    }


def _order(route: Route | None = None) -> Order:
    route = route or Route(id=1, name="наша сборка")
    return Order(
        id=10,
        priority=1,
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


def test_save_button_recalculates_even_when_no_rows_changed(monkeypatch) -> None:
    import app.ui.pages.orders_page as orders_page

    fake_st = _FakeStreamlit()
    repository = _FakeOrdersRepository()
    session = _FakeSession()
    recalculations = []
    order = _order()
    monkeypatch.setattr(orders_page, "st", fake_st)
    monkeypatch.setattr(
        orders_page,
        "recalculate_after_save",
        lambda value: recalculations.append(value),
    )

    with pytest.raises(_RerunRequested):
        orders_page._process_editor_changes(
            session,
            repository,
            [order],
            [_order_row(order)],
            {order.route.name: order.route},
            save_requested=True,
        )

    assert repository.updated == []
    assert session.commits == 1
    assert recalculations == [session]


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


def test_only_global_recalculation_button_remains() -> None:
    pathlib = __import__("pathlib")
    sources = "\n".join(
        pathlib.Path(path).read_text()
        for path in ("app/ui/navigation.py", "app/ui/pages/orders_page.py", "app/ui/pages/common.py")
    )
    assert "Сохранить все изменения и пересчитать план" not in sources
    assert sources.count('st.button("Пересчитать план")') == 1


def test_calculated_dates_are_read_only_and_child_fields_are_hidden() -> None:
    assert "Расчётная дата запуска" in READ_ONLY_EDITOR_COLUMNS
    assert "Расчётная дата отгрузки" in READ_ONLY_EDITOR_COLUMNS
    order = _order(); order.child_sequence_number = 7; order.is_child_order = True
    row = build_order_editor_rows([order], selected_order_id=None, include_draft=False)[0]
    assert "Номер в группе" not in EDITOR_COLUMNS
    assert "Дочерний заказ" not in EDITOR_COLUMNS
    assert "Связанная группа" not in EDITOR_COLUMNS
    assert "Связанные заказы" in EDITOR_COLUMNS
    assert row["_child_sequence_number"] == 7
    assert row["_is_child_order"] is True
    assert "Удалить выбранные заказы" in __import__("pathlib").Path(
        "app/ui/pages/orders_page.py"
    ).read_text()


def _priority_rows() -> list[dict]:
    return [
        {"ID": i, "Приоритет": i, "Статус": ORDER_STATUS_NEW,
         "Группа": "", "Связанные заказы": False}
        for i in range(1, 4)
    ]


def test_priority_edit_two_to_three_is_a_move() -> None:
    before = _priority_rows(); edited = [dict(row) for row in before]
    edited[1]["Приоритет"] = 3
    result = reconcile_priority_move(before, edited)
    assert [row["ID"] for row in sorted(result, key=lambda r: r["Приоритет"])] == [1, 3, 2]


def test_priority_edit_three_to_one_is_a_move() -> None:
    before = _priority_rows(); edited = [dict(row) for row in before]
    edited[2]["Приоритет"] = 1
    result = reconcile_priority_move(before, edited)
    assert [row["ID"] for row in sorted(result, key=lambda r: r["Приоритет"])] == [3, 1, 2]


def test_linked_children_move_as_one_ordered_block() -> None:
    before = _priority_rows()
    before[1].update({"Группа": "G", "Связанные заказы": True, "_child_sequence_number": 1})
    before[2].update({"Группа": "G", "Связанные заказы": True, "_child_sequence_number": 2})
    edited = [dict(row) for row in before]; edited[2]["Приоритет"] = 1
    result = reconcile_priority_move(before, edited)
    assert [row["ID"] for row in sorted(result, key=lambda r: r["Приоритет"])] == [2, 3, 1]


@pytest.mark.parametrize(
    ("mode", "value", "start", "shipment"),
    [
        (PLANNING_MODE_START, date(2026, 8, 1), date(2026, 8, 1), None),
        (PLANNING_MODE_SHIPMENT, date(2026, 8, 2), None, date(2026, 8, 2)),
    ],
)
def test_scheduling_override_exposes_only_the_mode_specific_date(mode, value, start, shipment) -> None:
    row = {"Режим планирования": PLANNING_MODE_SHIPMENT,
           "Заданная дата запуска": date(2026, 7, 1),
           "Заданная дата отгрузки": date(2026, 7, 2)}
    result = apply_scheduling_overrides([row], {0: (mode, value)})[0]
    assert result["Заданная дата запуска"] == start
    assert result["Заданная дата отгрузки"] == shipment


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (date(2026, 8, 1), date(2026, 8, 1)),
        (datetime(2026, 8, 2, 14, 30), date(2026, 8, 2)),
        ("2026-08-03", date(2026, 8, 3)),
        (None, None),
        ("not-a-date", None),
    ],
)
def test_normalize_editor_date(value, expected) -> None:
    assert normalize_editor_date(value) == expected


def test_normalize_editor_date_accepts_pandas_timestamp() -> None:
    pandas = pytest.importorskip("pandas")
    assert normalize_editor_date(pandas.Timestamp("2026-08-04 11:00")) == date(
        2026, 8, 4
    )


def test_mode_fixed_date_and_priority_are_saved_together(monkeypatch) -> None:
    import app.ui.pages.orders_page as orders_page

    fake_st = _FakeStreamlit()
    repository = _FakeOrdersRepository()
    repository.moves = []
    repository.move_order = lambda order_id, priority: repository.moves.append(
        (order_id, priority)
    )
    repository.normalize_priorities = lambda: None
    session = _FakeSession()
    recalculations = []
    order = _order()
    row = {
        **_order_row(order),
        "Режим планирования": PLANNING_MODE_START,
        "Фиксированная дата запуска": datetime(2026, 8, 5, 9),
        "Приоритет": 3,
    }
    monkeypatch.setattr(orders_page, "st", fake_st)
    monkeypatch.setattr(
        orders_page,
        "recalculate_after_save",
        lambda value: recalculations.append(value),
    )

    with pytest.raises(_RerunRequested):
        orders_page._process_editor_changes(
            session,
            repository,
            [order],
            [row],
            {order.route.name: order.route},
            save_requested=True,
        )

    payload = repository.updated[0][1]
    assert payload["planning_mode"] == PLANNING_MODE_START
    assert payload["fixed_start_date"] == date(2026, 8, 5)
    assert repository.moves == [(order.id, 3)]
    assert session.commits == 1
    assert recalculations == [session]


def test_validation_error_identifies_order_and_is_atomic(monkeypatch) -> None:
    import app.ui.pages.orders_page as orders_page

    fake_st = _FakeStreamlit()
    repository = _FakeOrdersRepository()
    session = _FakeSession()
    session.rollbacks = 0
    session.rollback = lambda: setattr(session, "rollbacks", session.rollbacks + 1)
    order = _order()
    row = {
        **_order_row(order),
        "Режим планирования": PLANNING_MODE_START,
        "Фиксированная дата запуска": None,
        "Приоритет": 3,
    }
    monkeypatch.setattr(orders_page, "st", fake_st)

    orders_page._process_editor_changes(
        session,
        repository,
        [order],
        [row],
        {order.route.name: order.route},
        save_requested=True,
    )

    assert fake_st.error_messages == [
        "Заказ ID 10 / № O-10: фиксированная дата запуска обязательна."
    ]
    assert repository.updated == []
    assert session.commits == 0
    assert session.rollbacks == 1


def test_unchanged_invalid_row_does_not_block_other_priority(monkeypatch) -> None:
    import app.ui.pages.orders_page as orders_page

    route = Route(id=1, name="наша сборка")
    invalid = _order(route)
    invalid.id = 10
    invalid.priority = 1
    invalid.shipment_date = None
    moved = _order(route)
    moved.id = 11
    moved.order_number = "O-11"
    moved.priority = 2
    repository = _FakeOrdersRepository()
    repository.moves = []
    repository.move_order = lambda order_id, priority: repository.moves.append(
        (order_id, priority)
    )
    repository.normalize_priorities = lambda: None
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(orders_page, "st", fake_st)
    monkeypatch.setattr(orders_page, "recalculate_after_save", lambda session: None)

    with pytest.raises(_RerunRequested):
        orders_page._process_editor_changes(
            _FakeSession(),
            repository,
            [invalid, moved],
            [_order_row(invalid), {**_order_row(moved), "Приоритет": 3}],
            {route.name: route},
            save_requested=True,
        )

    assert fake_st.error_messages == []
    assert repository.moves == [(moved.id, 3)]


def test_manual_status_options_only_include_new_and_cancelled() -> None:
    assert MANUAL_ORDER_STATUSES == (ORDER_STATUS_NEW, ORDER_STATUS_CANCELLED)


def test_validate_new_order_rejects_calculated_statuses() -> None:
    base = {
        "Номер": "N-1",
        "Клиент": "Клиент",
        "Продукция": "Продукт",
        "Тираж": 1000,
        "Режим планирования": "От даты отгрузки",
        "Фиксированная дата запуска": None,
        "Расчётная дата запуска": None,
        "Срок отгрузки": date(2026, 7, 10),
        "Группа": "",
        "Связанная группа": False,
        "Маршрут": "наша сборка",
    }
    for status in (ORDER_STATUS_PLANNED, ORDER_STATUS_CANCELLED):
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
        "Режим планирования": "От даты отгрузки",
        "Фиксированная дата запуска": None,
        "Расчётная дата запуска": None,
        "Срок отгрузки": date(2026, 7, 10),
        "Группа": "",
        "Связанная группа": False,
        "Маршрут": "наша сборка",
    }
    for status in (ORDER_STATUS_NEW, ORDER_STATUS_CANCELLED):
        assert (
            validate_order_editor_row(
                {**base, "Статус": status},
                route_names={"наша сборка"},
                existing_numbers={"N-1": 1},
                current_order_id=1,
            )
            == []
        )
    for status in (ORDER_STATUS_PLANNED,):
        errors = validate_order_editor_row(
            {**base, "Статус": status},
            route_names={"наша сборка"},
            existing_numbers={"N-1": 1},
            current_order_id=1,
        )
        assert (
            "Статус «Запланирован» назначается только после пересчёта; вручную можно сохранить только «Новый» или «Отменён»."
            in errors
        )


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


def test_can_change_quantity_for_planned_order_without_manual_status_change(
    monkeypatch,
) -> None:
    import app.ui.pages.orders_page as orders_page

    fake_st = _FakeStreamlit()
    repository = _FakeOrdersRepository()
    session = _FakeSession()
    recalculations = []
    order = _order()
    order.status = ORDER_STATUS_PLANNED
    edited_row = {**_order_row(order), "Тираж": 1700.0}

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
            {order.route.name: order.route},
            save_requested=True,
        )

    assert repository.updated[0][1]["quantity"] == 1700.0
    assert repository.updated[0][1]["status"] == ORDER_STATUS_PLANNED
    assert recalculations == [session]


def test_can_change_conflict_order_data_without_manual_status_change(
    monkeypatch,
) -> None:
    import app.ui.pages.orders_page as orders_page

    fake_st = _FakeStreamlit()
    repository = _FakeOrdersRepository()
    session = _FakeSession()
    recalculations = []
    order = _order()
    order.status = ORDER_STATUS_NEW
    edited_row = {**_order_row(order), "Клиент": "Новый клиент"}

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
            {order.route.name: order.route},
            save_requested=True,
        )

    assert repository.updated[0][1]["client_name"] == "Новый клиент"
    assert repository.updated[0][1]["status"] == ORDER_STATUS_NEW
    assert recalculations == [session]


def test_editor_signature_changes_after_recalculated_status_update() -> None:
    route = Route(id=1, name="маршрут")
    order = _order(route)
    order.status = ORDER_STATUS_NEW
    rows_before = build_order_editor_rows(
        [order], selected_order_id=None, include_draft=False
    )
    order.status = ORDER_STATUS_PLANNED
    order.calculated_start_date = date(2026, 7, 8)
    rows_after = build_order_editor_rows(
        [order], selected_order_id=None, include_draft=False
    )

    import app.ui.pages.orders_page as orders_page

    assert orders_page._order_editor_rows_signature(
        rows_before
    ) != orders_page._order_editor_rows_signature(rows_after)
    assert rows_after[0]["Статус"] == ORDER_STATUS_PLANNED
    assert rows_after[0]["Расчётная дата запуска"] == date(2026, 7, 8)
