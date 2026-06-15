from datetime import date

import pytest

pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.constants import ORDER_STATUS_CONFLICT, ORDER_STATUS_NEW, ORDER_STATUS_PLANNED
from app.db.database import Base
from app.db.models import Order, PlanChange, PlannedOperation, PlannedOperationDay, PlanningConflict, Route, RouteOperation, WorkCenter
from app.services.recalculation_service import RecalculationService


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with session_factory() as session:
        yield session


def create_route_with_operation(session: Session, *, hours_per_day: float, labor_hours_per_1000: float) -> Route:
    work_center = WorkCenter(name="Печать", available_hours_per_day=hours_per_day)
    route = Route(name="Маршрут A")
    session.add_all([work_center, route])
    session.flush()
    session.add(
        RouteOperation(
            route_id=route.id,
            sequence_number=1,
            work_center_id=work_center.id,
            labor_hours_per_1000=labor_hours_per_1000,
        )
    )
    session.flush()
    return route


def test_recalculation_service_persists_successful_plan(session: Session) -> None:
    route = create_route_with_operation(session, hours_per_day=8, labor_hours_per_1000=8)
    order = Order(
        order_number="R-001",
        client_name="Клиент",
        product_name="Продукт",
        quantity=1000,
        shipment_date=date(2026, 7, 10),
        route_id=route.id,
        status=ORDER_STATUS_NEW,
    )
    session.add(order)
    session.commit()

    summary = RecalculationService(session, planning_start_date=date(2026, 7, 1)).recalculate_plan()

    assert summary.planned_orders == 1
    assert summary.conflicts == 0
    assert session.query(PlannedOperation).count() == 1
    assert session.query(PlannedOperationDay).count() == 1
    assert session.query(PlanningConflict).count() == 0
    assert order.status == ORDER_STATUS_PLANNED
    assert order.calculated_start_date == date(2026, 7, 10)


def test_recalculation_service_persists_conflict(session: Session) -> None:
    route = create_route_with_operation(session, hours_per_day=1, labor_hours_per_1000=3)
    order = Order(
        order_number="R-002",
        client_name="Клиент",
        product_name="Продукт",
        quantity=1000,
        shipment_date=date(2026, 7, 10),
        route_id=route.id,
        status=ORDER_STATUS_NEW,
    )
    session.add(order)
    session.commit()

    summary = RecalculationService(session, planning_start_date=date(2026, 7, 10)).recalculate_plan()

    conflict = session.query(PlanningConflict).one()
    assert summary.planned_orders == 0
    assert summary.conflicts == 1
    assert session.query(PlannedOperation).count() == 0
    assert order.status == ORDER_STATUS_CONFLICT
    assert conflict.order_id == order.id
    assert conflict.deficit_hours == 2


def test_recalculation_service_clears_previous_plan(session: Session) -> None:
    route = create_route_with_operation(session, hours_per_day=8, labor_hours_per_1000=8)
    order = Order(
        order_number="R-003",
        client_name="Клиент",
        product_name="Продукт",
        quantity=1000,
        shipment_date=date(2026, 7, 10),
        route_id=route.id,
        status=ORDER_STATUS_NEW,
    )
    session.add(order)
    session.commit()

    service = RecalculationService(session, planning_start_date=date(2026, 7, 1))
    service.recalculate_plan()
    service.recalculate_plan()

    assert session.query(PlannedOperation).count() == 1
    assert session.query(PlannedOperationDay).count() == 1

def test_recalculation_service_records_plan_changes_when_operation_moves(session: Session) -> None:
    route = create_route_with_operation(session, hours_per_day=8, labor_hours_per_1000=8)
    first_order = Order(
        order_number="R-004",
        client_name="Клиент",
        product_name="Продукт",
        quantity=1000,
        shipment_date=date(2026, 7, 10),
        route_id=route.id,
        status=ORDER_STATUS_NEW,
    )
    session.add(first_order)
    session.commit()

    service = RecalculationService(session, planning_start_date=date(2026, 7, 1))
    service.recalculate_plan()

    first_order.shipment_date = date(2026, 7, 11)
    session.commit()

    service.recalculate_plan()

    changes = session.query(PlanChange).all()
    assert any(change.change_type == "order_start_changed" for change in changes)
    assert any(change.change_type == "operation_moved" for change in changes)

