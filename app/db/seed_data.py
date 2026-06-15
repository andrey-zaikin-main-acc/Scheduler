"""Demonstration seed data for the production planner MVP."""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import ORDER_STATUS_CANCELLED, ORDER_STATUS_DONE, ORDER_STATUS_NEW
from app.db import models as _models  # noqa: F401
from app.db.database import SessionLocal, create_all
from app.db.models import Order, Route, RouteOperation, Setting, WorkCenter


def seed_demo_data(session: Session) -> None:
    """Create an idempotent demo dataset close to the MVP planning domain."""
    work_centers = _seed_work_centers(session)
    route = _seed_route(session, work_centers)
    _seed_orders(session, route)
    _seed_settings(session)
    session.commit()


def _seed_work_centers(session: Session) -> dict[str, WorkCenter]:
    specs = [
        ("Печать", 8.0),
        ("Высечка", 8.0),
        ("Склейка", 16.0),
        ("Упаковка", 8.0),
    ]
    result: dict[str, WorkCenter] = {}
    for name, hours in specs:
        work_center = session.scalar(select(WorkCenter).where(WorkCenter.name == name))
        if work_center is None:
            work_center = WorkCenter(name=name, available_hours_per_day=hours)
            session.add(work_center)
            session.flush()
        result[name] = work_center
    return result


def _seed_route(session: Session, work_centers: dict[str, WorkCenter]) -> Route:
    route = session.scalar(select(Route).where(Route.name == "Маршрут A"))
    if route is None:
        route = Route(name="Маршрут A", description="Демонстрационный маршрут MVP")
        session.add(route)
        session.flush()

    operation_count = session.scalar(
        select(RouteOperation).where(RouteOperation.route_id == route.id).limit(1)
    )
    if operation_count is None:
        operations = [
            (1, "Печать", 4.0, 1000.0),
            (2, "Высечка", 3.0, 1000.0),
            (3, "Склейка", 2.0, 2000.0),
            (4, "Упаковка", 1.0, None),
        ]
        for sequence_number, work_center_name, labor_hours, transfer_quantity in operations:
            session.add(
                RouteOperation(
                    route_id=route.id,
                    sequence_number=sequence_number,
                    work_center_id=work_centers[work_center_name].id,
                    labor_hours_per_1000=labor_hours,
                    min_transfer_quantity_to_next=transfer_quantity,
                )
            )
    return route


def _seed_orders(session: Session, route: Route) -> None:
    today = date.today()
    specs = [
        ("MVP-101", "Клиент A", "Коробка A", 10_000.0, today + timedelta(days=14), ORDER_STATUS_NEW),
        ("MVP-102", "Клиент B", "Коробка B", 40_000.0, today + timedelta(days=14), ORDER_STATUS_NEW),
        ("MVP-103", "Клиент C", "Коробка C", 5_000.0, today + timedelta(days=7), ORDER_STATUS_DONE),
        ("MVP-104", "Клиент D", "Коробка D", 8_000.0, today + timedelta(days=21), ORDER_STATUS_CANCELLED),
    ]
    for order_number, client_name, product_name, quantity, shipment_date, status in specs:
        exists = session.scalar(select(Order).where(Order.order_number == order_number))
        if exists is None:
            session.add(
                Order(
                    order_number=order_number,
                    client_name=client_name,
                    product_name=product_name,
                    quantity=quantity,
                    shipment_date=shipment_date,
                    route_id=route.id,
                    status=status,
                )
            )


def _seed_settings(session: Session) -> None:
    specs = {
        "default_free_slot_days": "30",
        "max_backward_search_months": "12",
    }
    for key, value in specs.items():
        setting = session.get(Setting, key)
        if setting is None:
            session.add(Setting(key=key, value=value))


def main() -> None:
    """Create the database schema and insert demo data."""
    create_all()
    with SessionLocal() as session:
        seed_demo_data(session)


if __name__ == "__main__":
    main()
