from datetime import date

import pytest

pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.constants import ORDER_STATUS_NEW
from app.db.database import Base
from app.db.models import Order, Route, RouteOperation, WorkCenter
from app.repositories.orders_repository import OrdersRepository
from app.repositories.routes_repository import RoutesRepository
from app.repositories.work_centers_repository import WorkCentersRepository


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with session_factory() as session:
        yield session


def test_expected_tables_are_created(session: Session) -> None:
    table_names = set(inspect(session.bind).get_table_names())

    assert {
        "orders",
        "work_centers",
        "routes",
        "route_operations",
        "planned_operations",
        "planned_operation_days",
        "planning_conflicts",
        "recalculation_runs",
        "plan_changes",
        "settings",
    }.issubset(table_names)


def test_work_center_capacity_must_be_positive(session: Session) -> None:
    session.add(WorkCenter(name="Некорректный участок", available_hours_per_day=0))

    with pytest.raises(IntegrityError):
        session.commit()


def test_route_operation_labor_must_be_positive(session: Session) -> None:
    work_center = WorkCenter(name="Печать", available_hours_per_day=8)
    route = Route(name="Маршрут A")
    session.add_all([work_center, route])
    session.flush()

    session.add(
        RouteOperation(
            route_id=route.id,
            sequence_number=1,
            work_center_id=work_center.id,
            labor_hours_per_1000=0,
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_repositories_create_and_read_route_with_order(session: Session) -> None:
    work_centers = WorkCentersRepository(session)
    routes = RoutesRepository(session)
    orders = OrdersRepository(session)

    work_center = work_centers.create_work_center(name="Печать", available_hours_per_day=8)
    route = routes.create_route(name="Маршрут A", description="Тестовый маршрут")
    routes.add_operation(
        route_id=route.id,
        sequence_number=1,
        work_center_id=work_center.id,
        labor_hours_per_1000=4,
        min_transfer_quantity_to_next=1000,
    )
    order = orders.create_order(
        order_number="T-001",
        client_name="Клиент",
        product_name="Продукт",
        quantity=10_000,
        shipment_date=date(2026, 7, 10),
        route_id=route.id,
        status=ORDER_STATUS_NEW,
    )
    session.commit()

    loaded_route = routes.get_route_with_operations(route.id)
    loaded_order = orders.get_by_number("T-001")

    assert loaded_route is not None
    assert len(loaded_route.operations) == 1
    assert loaded_route.operations[0].work_center.name == "Печать"
    assert loaded_order is not None
    assert loaded_order.id == order.id
    assert loaded_order.client_name == "Клиент"
    assert loaded_order.product_name == "Продукт"
