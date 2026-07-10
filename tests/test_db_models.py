from datetime import date

import pytest

pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.constants import ORDER_STATUS_NEW
from app.db.database import Base
from app.db.models import Order, PlanChange, PlannedOperation, PlannedOperationDay, PlanningConflict, RecalculationRun, Route, RouteOperation, WorkCenter
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


def test_orders_repository_updates_order(session: Session) -> None:
    work_centers = WorkCentersRepository(session)
    routes = RoutesRepository(session)
    orders = OrdersRepository(session)
    work_center = work_centers.create_work_center(name="Склейка", available_hours_per_day=8)
    route = routes.create_route(name="наша сборка")
    routes.add_operation(route_id=route.id, sequence_number=1, work_center_id=work_center.id, labor_hours_per_1000=4)
    order = orders.create_order(
        order_number="T-002",
        client_name="Клиент",
        product_name="Продукт",
        quantity=1000,
        shipment_date=date(2026, 7, 10),
        route_id=route.id,
        status=ORDER_STATUS_NEW,
    )

    updated = orders.update_order(
        order.id,
        order_number="T-002-EDIT",
        client_name="Новый клиент",
        product_name="Новый продукт",
        quantity=2000,
        shipment_date=date(2026, 7, 11),
        route_id=route.id,
        status=ORDER_STATUS_NEW,
    )

    assert updated is not None
    assert updated.order_number == "T-002-EDIT"
    assert updated.client_name == "Новый клиент"
    assert updated.quantity == 2000
    assert updated.shipment_date == date(2026, 7, 11)


def test_orders_repository_delete_order_clears_related_plan_data(session: Session) -> None:
    work_centers = WorkCentersRepository(session)
    routes = RoutesRepository(session)
    orders = OrdersRepository(session)
    work_center = work_centers.create_work_center(name="Высечка", available_hours_per_day=8)
    route = routes.create_route(name="поток ленты")
    route_operation = routes.add_operation(route_id=route.id, sequence_number=1, work_center_id=work_center.id, labor_hours_per_1000=4)
    order = orders.create_order(
        order_number="T-003",
        client_name="Клиент",
        product_name="Продукт",
        quantity=1000,
        shipment_date=date(2026, 7, 10),
        route_id=route.id,
        status=ORDER_STATUS_NEW,
    )
    planned_operation = PlannedOperation(
        order_id=order.id,
        route_operation_id=route_operation.id,
        work_center_id=work_center.id,
        sequence_number=1,
        planned_start_date=date(2026, 7, 10),
        planned_end_date=date(2026, 7, 10),
        required_hours=4,
        planned_hours=4,
        status=ORDER_STATUS_NEW,
    )
    session.add(planned_operation)
    session.flush()
    session.add(
        PlannedOperationDay(
            planned_operation_id=planned_operation.id,
            work_center_id=work_center.id,
            date=date(2026, 7, 10),
            hours=4,
        )
    )
    session.add(
        PlanningConflict(
            order_id=order.id,
            shipment_date=date(2026, 7, 10),
            work_center_id=work_center.id,
            required_hours=4,
            available_hours=0,
            deficit_hours=4,
            reason="Тест",
        )
    )
    run = RecalculationRun(status="completed")
    session.add(run)
    session.flush()
    session.add(PlanChange(recalculation_run_id=run.id, order_id=order.id, change_type="created", description="Тест"))
    session.commit()

    assert orders.delete_order(order.id) is True

    assert session.query(Order).count() == 0
    assert session.query(PlannedOperation).count() == 0
    assert session.query(PlannedOperationDay).count() == 0
    assert session.query(PlanningConflict).count() == 0
    assert session.query(PlanChange).count() == 0


def test_repository_rejects_manual_calculated_status(session):
    from app.constants import ORDER_STATUS_PLANNED
    from app.repositories.orders_repository import OrdersRepository

    order = session.query(Order).first()
    if order is None:
        return
    with pytest.raises(ValueError):
        OrdersRepository(session).update_status(order.id, ORDER_STATUS_PLANNED)


def test_work_center_prevent_order_interruption_is_saved_and_mapped(session: Session) -> None:
    work_centers = WorkCentersRepository(session)

    created = work_centers.create_work_center(
        name="Защищенный участок",
        available_hours_per_day=8,
        prevent_order_interruption=True,
    )
    session.commit()
    work_centers.update_work_center(
        created.id,
        name="Защищенный участок",
        available_hours_per_day=8,
        workday_start_time=created.workday_start_time,
        is_active=True,
        prevent_order_interruption=False,
    )
    session.commit()

    loaded = session.get(WorkCenter, created.id)
    assert loaded is not None
    assert loaded.prevent_order_interruption is False

    from app.services.planning_mapper import map_work_center_to_planning

    mapped = map_work_center_to_planning(loaded)
    assert mapped.prevent_order_interruption is False


def test_new_work_center_prevent_order_interruption_default_is_false(session: Session) -> None:
    work_center = WorkCenter(name="Обычный участок", available_hours_per_day=8)
    session.add(work_center)
    session.commit()

    loaded = session.get(WorkCenter, work_center.id)
    assert loaded is not None
    assert loaded.prevent_order_interruption is False


def test_create_all_migrates_existing_routes_prevent_order_interruption_column(
    monkeypatch, tmp_path
) -> None:
    from app.db import database

    db_path = tmp_path / "legacy.sqlite"
    legacy_engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    with legacy_engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE routes (
                id INTEGER PRIMARY KEY,
                name VARCHAR(255) NOT NULL UNIQUE,
                description TEXT,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO routes (name, description, is_active, created_at, updated_at)
            VALUES ('наша сборка', NULL, 1, '2026-07-10 00:00:00', '2026-07-10 00:00:00')
            """
        )

    monkeypatch.setattr(database, "engine", legacy_engine)
    monkeypatch.setattr(database, "DATA_DIR", tmp_path)

    database.create_all()

    columns = {column["name"] for column in inspect(legacy_engine).get_columns("routes")}
    assert "prevent_order_interruption" in columns
    with sessionmaker(bind=legacy_engine)() as session:
        route = session.scalar(select(Route).where(Route.name == "наша сборка"))
    assert route is not None
    assert route.prevent_order_interruption is False
