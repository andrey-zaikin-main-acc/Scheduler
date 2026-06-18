from datetime import date

import pytest

pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session, sessionmaker

from app.constants import ORDER_STATUS_NEW, ORDER_STATUS_PLANNED
from app.db.database import Base
from app.db.models import (
    Order,
    PlannedOperation,
    PlannedOperationDay,
    PlanningConflict,
    Route,
    RouteOperation,
    WorkCenter,
)
from app.services.route_capacity_service import RouteCapacityService


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    with session_factory() as session:
        yield session


def create_route(
    session: Session, *, print_hours=8, glue_hours=4
) -> tuple[Route, WorkCenter, WorkCenter, RouteOperation, RouteOperation]:
    print_center = WorkCenter(name="Печать", available_hours_per_day=print_hours)
    glue_center = WorkCenter(name="Склейка", available_hours_per_day=glue_hours)
    route = Route(name="Маршрут A", is_active=True)
    session.add_all([print_center, glue_center, route])
    session.flush()
    print_operation = RouteOperation(
        route_id=route.id,
        sequence_number=1,
        work_center_id=print_center.id,
        labor_hours_per_1000=2,
    )
    glue_operation = RouteOperation(
        route_id=route.id,
        sequence_number=2,
        work_center_id=glue_center.id,
        labor_hours_per_1000=1,
    )
    session.add_all([print_operation, glue_operation])
    session.commit()
    return route, print_center, glue_center, print_operation, glue_operation


def add_planned_day(
    session: Session,
    *,
    route: Route,
    operation: RouteOperation,
    work_center: WorkCenter,
    day: date,
    hours: float,
) -> None:
    order = Order(
        order_number=f"O-{day}-{work_center.id}-{hours}",
        client_name="Клиент",
        product_name="Продукт",
        quantity=1000,
        shipment_date=day,
        route_id=route.id,
        status=ORDER_STATUS_NEW,
    )
    session.add(order)
    session.flush()
    planned_operation = PlannedOperation(
        order_id=order.id,
        route_operation_id=operation.id,
        work_center_id=work_center.id,
        sequence_number=operation.sequence_number,
        planned_start_date=day,
        planned_end_date=day,
        required_hours=hours,
        planned_hours=hours,
        status=ORDER_STATUS_PLANNED,
    )
    session.add(planned_operation)
    session.flush()
    session.add(
        PlannedOperationDay(
            planned_operation_id=planned_operation.id,
            work_center_id=work_center.id,
            date=day,
            hours=hours,
        )
    )
    session.commit()


def test_route_capacity_is_minimum_across_operations(session: Session) -> None:
    route, *_ = create_route(session, print_hours=10, glue_hours=4)

    result = RouteCapacityService(session).calculate_route_capacity(
        route.id, date(2026, 7, 1), date(2026, 7, 1)
    )

    assert result.max_quantity == 4000
    assert result.bottleneck_work_center == "Склейка"


def test_planned_operation_days_reduce_available_quantity(session: Session) -> None:
    route, print_center, _, print_operation, _ = create_route(
        session, print_hours=8, glue_hours=16
    )
    add_planned_day(
        session,
        route=route,
        operation=print_operation,
        work_center=print_center,
        day=date(2026, 7, 1),
        hours=6,
    )

    result = RouteCapacityService(session).calculate_route_capacity(
        route.id, date(2026, 7, 1), date(2026, 7, 1)
    )

    assert result.max_quantity == 1000
    assert result.bottleneck_work_center == "Печать"


def test_capacity_is_zero_when_no_free_hours(session: Session) -> None:
    route, print_center, _, print_operation, _ = create_route(
        session, print_hours=8, glue_hours=16
    )
    add_planned_day(
        session,
        route=route,
        operation=print_operation,
        work_center=print_center,
        day=date(2026, 7, 1),
        hours=8,
    )

    result = RouteCapacityService(session).calculate_route_capacity(
        route.id, date(2026, 7, 1), date(2026, 7, 1)
    )

    assert result.max_quantity == 0


def test_quantity_above_capacity_does_not_calculate_slots(session: Session) -> None:
    route, *_ = create_route(session, print_hours=8, glue_hours=4)

    slots = RouteCapacityService(session).find_available_shipment_slots(
        route.id, 5000, date(2026, 7, 1), date(2026, 7, 1)
    )

    assert slots == []


def test_slot_search_does_not_create_orders_or_saved_plan(session: Session) -> None:
    route, *_ = create_route(session, print_hours=8, glue_hours=8)
    before_orders = session.scalar(select(func.count(Order.id)))
    before_days = session.scalar(select(func.count(PlannedOperationDay.id)))
    before_conflicts = session.scalar(select(func.count(PlanningConflict.id)))

    slots = RouteCapacityService(session).find_available_shipment_slots(
        route.id, 1000, date(2026, 7, 1), date(2026, 7, 3)
    )

    assert slots
    assert session.scalar(select(func.count(Order.id))) == before_orders
    assert session.scalar(select(func.count(PlannedOperationDay.id))) == before_days
    assert session.scalar(select(func.count(PlanningConflict.id))) == before_conflicts


def test_slot_search_returns_possible_dates(session: Session) -> None:
    route, *_ = create_route(session, print_hours=8, glue_hours=8)

    slots = RouteCapacityService(session).find_available_shipment_slots(
        route.id, 1000, date(2026, 7, 1), date(2026, 7, 3)
    )

    assert slots == [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)]


def test_slot_search_returns_empty_when_dates_do_not_fit(session: Session) -> None:
    route, print_center, glue_center, print_operation, glue_operation = create_route(
        session, print_hours=8, glue_hours=8
    )
    for day in [date(2026, 7, 1), date(2026, 7, 2)]:
        add_planned_day(
            session,
            route=route,
            operation=print_operation,
            work_center=print_center,
            day=day,
            hours=7,
        )
        add_planned_day(
            session,
            route=route,
            operation=glue_operation,
            work_center=glue_center,
            day=day,
            hours=7,
        )

    slots = RouteCapacityService(session).find_available_shipment_slots(
        route.id, 1000, date(2026, 7, 1), date(2026, 7, 2)
    )

    assert slots == []
