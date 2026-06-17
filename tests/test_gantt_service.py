from datetime import date, datetime

import pytest

pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.constants import ORDER_STATUS_NEW, ORDER_STATUS_PLANNED
from app.db.database import Base
from app.db.models import Order, PlannedOperation, PlannedOperationDay, Route, RouteOperation, WorkCenter
from app.services.gantt_service import GanttService


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with session_factory() as session:
        yield session


def create_planned_operation(session: Session) -> None:
    work_center = WorkCenter(name="Печать", available_hours_per_day=8)
    route = Route(name="Маршрут A")
    session.add_all([work_center, route])
    session.flush()
    route_operation = RouteOperation(
        route_id=route.id,
        sequence_number=1,
        work_center_id=work_center.id,
        labor_hours_per_1000=8,
    )
    session.add(route_operation)
    session.flush()
    order = Order(
        order_number="G-001",
        client_name="Клиент",
        product_name="Продукт",
        quantity=1000,
        shipment_date=date(2026, 7, 10),
        route_id=route.id,
        status=ORDER_STATUS_NEW,
    )
    session.add(order)
    session.flush()
    planned_operation = PlannedOperation(
            order_id=order.id,
            route_operation_id=route_operation.id,
            work_center_id=work_center.id,
            sequence_number=1,
            planned_start_date=date(2026, 7, 10),
            planned_end_date=date(2026, 7, 10),
            required_hours=8,
            planned_hours=8,
            status=ORDER_STATUS_PLANNED,
        )
    session.add(planned_operation)
    session.flush()
    session.add(
        PlannedOperationDay(
            planned_operation_id=planned_operation.id,
            work_center_id=work_center.id,
            date=date(2026, 7, 10),
            hours=8,
            start_datetime=datetime(2026, 7, 10, 9),
            end_datetime=datetime(2026, 7, 10, 17),
        )
    )
    session.commit()


def test_gantt_by_orders_uses_order_lanes(session: Session) -> None:
    create_planned_operation(session)

    rows = GanttService(session).get_gantt_by_orders()

    assert rows == [
        {
            "row": "G-001",
            "task": "1. Печать",
            "start": datetime(2026, 7, 10, 9),
            "finish": datetime(2026, 7, 10, 17),
            "start_datetime": datetime(2026, 7, 10, 9),
            "end_datetime": datetime(2026, 7, 10, 17),
            "order": "G-001",
            "work_center": "Печать",
            "hours": 8,
            "sequence_number": 1,
        }
    ]


def test_gantt_by_work_centers_uses_work_center_lanes(session: Session) -> None:
    create_planned_operation(session)

    rows = GanttService(session).get_gantt_by_work_centers()

    assert rows[0]["row"] == "Печать"
    assert rows[0]["task"] == "G-001"
    assert rows[0]["order"] == "G-001"
    assert rows[0]["work_center"] == "Печать"
