from datetime import date

import pytest

pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.constants import ORDER_STATUS_NEW, ORDER_STATUS_PLANNED
from app.db.database import Base
from app.db.models import (
    Order,
    PlannedOperation,
    PlannedOperationDay,
    Route,
    RouteOperation,
    WorkCenter,
)
from app.services.free_slots_service import FreeSlotsService


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    with session_factory() as session:
        yield session


def create_route_plan_fixture(session: Session) -> None:
    print_center = WorkCenter(name="Печать", available_hours_per_day=248)
    glue_center = WorkCenter(name="Склейка", available_hours_per_day=496)
    route = Route(name="Маршрут A")
    session.add_all([print_center, glue_center, route])
    session.flush()

    print_operation = RouteOperation(
        route_id=route.id,
        sequence_number=1,
        work_center_id=print_center.id,
        labor_hours_per_1000=4,
    )
    glue_operation = RouteOperation(
        route_id=route.id,
        sequence_number=2,
        work_center_id=glue_center.id,
        labor_hours_per_1000=2,
    )
    session.add_all([print_operation, glue_operation])
    session.flush()

    order = Order(
        order_number="S-001",
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
        route_operation_id=print_operation.id,
        work_center_id=print_center.id,
        sequence_number=1,
        planned_start_date=date(2026, 7, 10),
        planned_end_date=date(2026, 7, 10),
        required_hours=6,
        planned_hours=6,
        status=ORDER_STATUS_PLANNED,
    )
    session.add(planned_operation)
    session.flush()
    session.add(
        PlannedOperationDay(
            planned_operation_id=planned_operation.id,
            work_center_id=print_center.id,
            date=date(2026, 7, 10),
            hours=6,
        )
    )
    session.commit()


def test_free_slots_by_work_center_and_date(session: Session) -> None:
    create_route_plan_fixture(session)

    rows = FreeSlotsService(session).get_free_slots(
        start_date=date(2026, 7, 10),
        end_date=date(2026, 7, 10),
    )

    by_center = {row["Участок"]: row for row in rows}
    assert by_center["Печать"]["Доступно часов"] == 8
    assert by_center["Печать"]["Занято часов"] == 6
    assert by_center["Печать"]["Свободно часов"] == 2
    assert by_center["Склейка"]["Свободно часов"] == 16


def test_route_capacity_uses_bottleneck_work_center(session: Session) -> None:
    create_route_plan_fixture(session)

    rows = FreeSlotsService(session).get_route_capacities(
        start_date=date(2026, 7, 10),
        end_date=date(2026, 7, 10),
    )

    assert rows == [
        {
            "Маршрут": "Маршрут A",
            "Теоретический максимальный тираж": 500.0,
            "Ограничивающий участок": "Печать",
        }
    ]


def test_shipment_slots_are_calculated_backwards_for_each_deadline(session: Session) -> None:
    create_route_plan_fixture(session)
    route_id = session.scalar(__import__("sqlalchemy").select(Route.id))
    rows = FreeSlotsService(session).find_shipment_slots(
        route_id=route_id, quantity=4000,
        start_date=date(2026, 7, 10), end_date=date(2026, 7, 11),
    )
    assert [row["Заданная дата отгрузки"] for row in rows] == [
        date(2026, 7, 10), date(2026, 7, 11)
    ]
    assert all(row["Расчётная дата запуска"] <= row["Заданная дата отгрузки"] for row in rows)
