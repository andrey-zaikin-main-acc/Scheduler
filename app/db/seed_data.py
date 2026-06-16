"""Seed data loaded from the production planning Excel source."""

import argparse
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.constants import ORDER_STATUS_NEW
from app.db import models as _models  # noqa: F401
from app.db.database import SessionLocal, create_all, drop_all, ensure_data_dir
from app.db.models import (
    Order,
    PlanChange,
    PlannedOperation,
    PlannedOperationDay,
    PlanningConflict,
    RecalculationRun,
    Route,
    RouteOperation,
    Setting,
    WorkCenter,
)

TRANSFER_BATCH_QUANTITY = 1000.0

WORK_CENTER_SPECS: tuple[tuple[str, float], ...] = (
    ("Склейка", 3300.0),
    ("Высечка", 1500.0),
    ("Кашировка", 1000.0),
    ("Резка_плоттер", 1000.0),
    ("Цифровая_печать", 236.0),
    ("Копакинг", 7560.0),
)

ROUTE_OPERATION_SEQUENCE: tuple[str, ...] = (
    "Склейка",
    "Высечка",
    "Кашировка",
    "Резка_плоттер",
    "Цифровая_печать",
    "Копакинг",
)


@dataclass(frozen=True)
class RouteSpec:
    """Technological route specification imported from the Excel source."""

    name: str
    project_code: int
    labor_hours_by_work_center: dict[str, float]


ROUTE_SPECS: tuple[RouteSpec, ...] = (
    RouteSpec(
        name="наша сборка",
        project_code=222398,
        labor_hours_by_work_center={
            "Склейка": 93.278,
            "Высечка": 42.719,
            "Кашировка": 4.017,
            "Резка_плоттер": 0.0,
            "Цифровая_печать": 0.0,
            "Копакинг": 381.82,
        },
    ),
    RouteSpec(
        name="наша сборка малая",
        project_code=222179,
        labor_hours_by_work_center={
            "Склейка": 64.466,
            "Высечка": 1.415,
            "Кашировка": 0.629,
            "Резка_плоттер": 0.235,
            "Цифровая_печать": 0.0,
            "Копакинг": 80.52,
        },
    ),
    RouteSpec(
        name="поток витрина Кола",
        project_code=222247,
        labor_hours_by_work_center={
            "Склейка": 158.317,
            "Высечка": 16.593,
            "Кашировка": 14.595,
            "Резка_плоттер": 0.931,
            "Цифровая_печать": 0.4,
            "Копакинг": 0.0,
        },
    ),
    RouteSpec(
        name="поток витрина простая большая",
        project_code=222287,
        labor_hours_by_work_center={
            "Склейка": 16.356,
            "Высечка": 6.211,
            "Кашировка": 4.058,
            "Резка_плоттер": 2.644,
            "Цифровая_печать": 0.86,
            "Копакинг": 0.0,
        },
    ),
    RouteSpec(
        name="поток витрина простая малая",
        project_code=222548,
        labor_hours_by_work_center={
            "Склейка": 16.545,
            "Высечка": 21.408,
            "Кашировка": 4.205,
            "Резка_плоттер": 0.672,
            "Цифровая_печать": 0.0,
            "Копакинг": 0.0,
        },
    ),
    RouteSpec(
        name="поток витрина с клипсами",
        project_code=221810,
        labor_hours_by_work_center={
            "Склейка": 101.97,
            "Высечка": 155.183,
            "Кашировка": 7.677,
            "Резка_плоттер": 0.0,
            "Цифровая_печать": 0.0,
            "Копакинг": 0.0,
        },
    ),
    RouteSpec(
        name="поток ленты",
        project_code=222597,
        labor_hours_by_work_center={
            "Склейка": 7.761,
            "Высечка": 17.87,
            "Кашировка": 2.371,
            "Резка_плоттер": 0.401,
            "Цифровая_печать": 0.0,
            "Копакинг": 0.0,
        },
    ),
    RouteSpec(
        name="поток театры",
        project_code=222562,
        labor_hours_by_work_center={
            "Склейка": 1110.428,
            "Высечка": 0.0,
            "Кашировка": 65.285,
            "Резка_плоттер": 3626.428,
            "Цифровая_печать": 506.71,
            "Копакинг": 0.0,
        },
    ),
)

ORDER_SPECS: tuple[tuple[str, str, str, float, int, str], ...] = (
    ("EXCEL-101", "Клиент Excel A", "Наша сборка", 10_000.0, 21, "наша сборка"),
    ("EXCEL-102", "Клиент Excel B", "Наша сборка малая", 8_000.0, 18, "наша сборка малая"),
    ("EXCEL-103", "Клиент Excel C", "Витрина Кола", 6_000.0, 14, "поток витрина Кола"),
    ("EXCEL-104", "Клиент Excel D", "Ленты", 20_000.0, 10, "поток ленты"),
    ("EXCEL-105", "Клиент Excel E", "Театры", 2_000.0, 7, "поток театры"),
)


def seed_demo_data(session: Session) -> None:
    """Create an idempotent dataset based on the provided Excel source."""
    _clear_saved_plan(session)
    _remove_legacy_demo_data(session)
    work_centers = _seed_work_centers(session)
    routes = _seed_routes(session, work_centers)
    _seed_orders(session, routes)
    _seed_settings(session)
    session.commit()


def reset_seed_data(session: Session) -> None:
    """Clear planner data and fill it with the current Excel-based seed dataset."""
    _clear_planner_data(session)
    seed_demo_data(session)


def reset_sqlite_database() -> None:
    """Drop, recreate and seed the configured SQLite database."""
    ensure_data_dir()
    drop_all()
    create_all()
    with SessionLocal() as session:
        seed_demo_data(session)


def _remove_legacy_demo_data(session: Session) -> None:
    legacy_order_numbers = ["MVP-101", "MVP-102", "MVP-103", "MVP-104"]
    legacy_routes = ["Маршрут A"]
    legacy_work_centers = ["Печать", "Упаковка"]

    session.execute(delete(Order).where(Order.order_number.in_(legacy_order_numbers)))
    session.execute(delete(RouteOperation).where(RouteOperation.route_id.in_(select(Route.id).where(Route.name.in_(legacy_routes)))))
    session.execute(delete(Route).where(Route.name.in_(legacy_routes)))
    session.execute(delete(WorkCenter).where(WorkCenter.name.in_(legacy_work_centers)))
    session.flush()


def _clear_saved_plan(session: Session) -> None:
    session.execute(delete(PlanChange))
    session.execute(delete(RecalculationRun))
    session.execute(delete(PlanningConflict))
    session.execute(delete(PlannedOperationDay))
    session.execute(delete(PlannedOperation))
    session.flush()


def _clear_planner_data(session: Session) -> None:
    _clear_saved_plan(session)
    session.execute(delete(Order))
    session.execute(delete(RouteOperation))
    session.execute(delete(Route))
    session.execute(delete(WorkCenter))
    session.execute(delete(Setting))
    session.flush()


def _seed_work_centers(session: Session) -> dict[str, WorkCenter]:
    result: dict[str, WorkCenter] = {}
    for name, hours in WORK_CENTER_SPECS:
        work_center = session.scalar(select(WorkCenter).where(WorkCenter.name == name))
        if work_center is None:
            work_center = WorkCenter(name=name, available_hours_per_day=hours, is_active=True)
            session.add(work_center)
        else:
            work_center.available_hours_per_day = hours
            work_center.is_active = True
        session.flush()
        result[name] = work_center
    return result


def _seed_routes(session: Session, work_centers: dict[str, WorkCenter]) -> dict[str, Route]:
    routes: dict[str, Route] = {}
    for spec in ROUTE_SPECS:
        route = session.scalar(select(Route).where(Route.name == spec.name))
        description = f"Проект: {spec.project_code}"
        if route is None:
            route = Route(name=spec.name, description=description, is_active=True)
            session.add(route)
            session.flush()
        else:
            route.description = description
            route.is_active = True
            session.execute(delete(RouteOperation).where(RouteOperation.route_id == route.id))
            session.flush()

        operations = _positive_route_operations(spec)
        for index, (work_center_name, labor_hours) in enumerate(operations, start=1):
            session.add(
                RouteOperation(
                    route_id=route.id,
                    sequence_number=index,
                    work_center_id=work_centers[work_center_name].id,
                    labor_hours_per_1000=labor_hours,
                    min_transfer_quantity_to_next=TRANSFER_BATCH_QUANTITY if index < len(operations) else None,
                )
            )
        session.flush()
        routes[spec.name] = route
    return routes


def _positive_route_operations(spec: RouteSpec) -> list[tuple[str, float]]:
    """Return only route operations with positive labor because the DB enforces it."""
    return [
        (work_center_name, spec.labor_hours_by_work_center[work_center_name])
        for work_center_name in ROUTE_OPERATION_SEQUENCE
        if spec.labor_hours_by_work_center[work_center_name] > 0
    ]


def _seed_orders(session: Session, routes: dict[str, Route]) -> None:
    today = date.today()
    for order_number, client_name, product_name, quantity, due_in_days, route_name in ORDER_SPECS:
        order = session.scalar(select(Order).where(Order.order_number == order_number))
        shipment_date = today + timedelta(days=due_in_days)
        if order is None:
            session.add(
                Order(
                    order_number=order_number,
                    client_name=client_name,
                    product_name=product_name,
                    quantity=quantity,
                    shipment_date=shipment_date,
                    route_id=routes[route_name].id,
                    status=ORDER_STATUS_NEW,
                )
            )
        else:
            order.client_name = client_name
            order.product_name = product_name
            order.quantity = quantity
            order.shipment_date = shipment_date
            order.route_id = routes[route_name].id
            order.status = ORDER_STATUS_NEW
            order.calculated_start_date = None


def _seed_settings(session: Session) -> None:
    specs = {
        "default_free_slot_days": "30",
        "max_backward_search_months": "12",
    }
    for key, value in specs.items():
        setting = session.get(Setting, key)
        if setting is None:
            session.add(Setting(key=key, value=value))
        else:
            setting.value = value


def main() -> None:
    """Create the database schema and insert the Excel-based seed data."""
    parser = argparse.ArgumentParser(description="Load Excel-based seed data into the local SQLite database.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop and recreate SQLite before loading the current Excel-based seed data.",
    )
    args = parser.parse_args()

    if args.reset:
        reset_sqlite_database()
    else:
        create_all()
        with SessionLocal() as session:
            seed_demo_data(session)


if __name__ == "__main__":
    main()
