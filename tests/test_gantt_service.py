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


def create_fragmented_planned_operation(
    session: Session,
    intervals: list[tuple[datetime, datetime]],
) -> None:
    work_center = WorkCenter(name="Склейка", available_hours_per_day=8)
    route = Route(name="Маршрут партии")
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
        order_number="101",
        client_name="Клиент",
        product_name="Продукт",
        quantity=3000,
        shipment_date=date(2026, 7, 10),
        route_id=route.id,
        status=ORDER_STATUS_NEW,
    )
    session.add(order)
    session.flush()
    total_hours = sum((finish - start).total_seconds() / 3600 for start, finish in intervals)
    planned_operation = PlannedOperation(
        order_id=order.id,
        route_operation_id=route_operation.id,
        work_center_id=work_center.id,
        sequence_number=1,
        planned_start_date=intervals[0][0].date(),
        planned_end_date=intervals[-1][1].date(),
        required_hours=total_hours,
        planned_hours=total_hours,
        status=ORDER_STATUS_PLANNED,
    )
    session.add(planned_operation)
    session.flush()
    for start, finish in intervals:
        session.add(
            PlannedOperationDay(
                planned_operation_id=planned_operation.id,
                work_center_id=work_center.id,
                date=start.date(),
                hours=(finish - start).total_seconds() / 3600,
                start_datetime=start,
                end_datetime=finish,
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


def test_gantt_merges_contiguous_fragments_for_same_order_operation_and_work_center(session: Session) -> None:
    create_fragmented_planned_operation(
        session,
        [
            (datetime(2026, 7, 10, 9), datetime(2026, 7, 10, 10)),
            (datetime(2026, 7, 10, 10), datetime(2026, 7, 10, 11)),
            (datetime(2026, 7, 10, 11), datetime(2026, 7, 10, 12)),
        ],
    )

    order_rows = GanttService(session).get_gantt_by_orders()
    work_center_rows = GanttService(session).get_gantt_by_work_centers()

    assert len(order_rows) == 1
    assert order_rows[0]["row"] == "101"
    assert order_rows[0]["task"] == "1. Склейка"
    assert order_rows[0]["start"] == datetime(2026, 7, 10, 9)
    assert order_rows[0]["finish"] == datetime(2026, 7, 10, 12)
    assert order_rows[0]["hours"] == 3
    assert len(work_center_rows) == 1
    assert work_center_rows[0]["row"] == "Склейка"
    assert work_center_rows[0]["task"] == "101"
    assert work_center_rows[0]["start"] == datetime(2026, 7, 10, 9)
    assert work_center_rows[0]["finish"] == datetime(2026, 7, 10, 12)
    assert work_center_rows[0]["hours"] == 3


def test_gantt_keeps_fragments_separate_when_real_gap_exists(session: Session) -> None:
    create_fragmented_planned_operation(
        session,
        [
            (datetime(2026, 7, 10, 9), datetime(2026, 7, 10, 10)),
            (datetime(2026, 7, 10, 11), datetime(2026, 7, 10, 12)),
        ],
    )

    rows = GanttService(session).get_gantt_by_orders()

    assert len(rows) == 2
    assert rows[0]["start"] == datetime(2026, 7, 10, 9)
    assert rows[0]["finish"] == datetime(2026, 7, 10, 10)
    assert rows[1]["start"] == datetime(2026, 7, 10, 11)
    assert rows[1]["finish"] == datetime(2026, 7, 10, 12)
