from datetime import date

import pytest

pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base
from app.db.models import Order, Route, RouteOperation, Setting, WorkCenter
from app.db.seed_data import ROUTE_SPECS, WORK_CENTER_SPECS, reset_seed_data, seed_demo_data


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return session_factory()


def test_seed_demo_data_is_idempotent() -> None:
    with make_session() as session:
        seed_demo_data(session)
        seed_demo_data(session)

        assert session.query(WorkCenter).count() == 6
        assert session.query(Route).count() == 8
        assert session.query(RouteOperation).count() == 34
        assert session.query(Order).count() == 5
        assert session.query(Setting).count() == 2


def test_seed_work_centers_match_excel_source() -> None:
    with make_session() as session:
        seed_demo_data(session)

        rows = session.scalars(select(WorkCenter).order_by(WorkCenter.name)).all()

        assert {row.name: row.available_hours_per_day for row in rows} == {
            name: hours for name, hours, _ in WORK_CENTER_SPECS
        }
        assert {
            row.name: row.workday_start_time.isoformat(timespec="minutes")
            for row in rows
        } == {
            name: start.isoformat(timespec="minutes")
            for name, _, start in WORK_CENTER_SPECS
        }
        assert all(row.is_active for row in rows)


def test_seed_routes_match_excel_source_and_skip_zero_labor_operations() -> None:
    with make_session() as session:
        seed_demo_data(session)

        route_names = {route.name for route in session.scalars(select(Route)).all()}
        assert route_names == {spec.name for spec in ROUTE_SPECS}

        route = session.scalar(select(Route).where(Route.name == "поток театры"))
        assert route is not None
        assert route.description == "Проект: 222562"

        operations = session.scalars(
            select(RouteOperation)
            .where(RouteOperation.route_id == route.id)
            .order_by(RouteOperation.sequence_number)
        ).all()

        assert [operation.work_center.name for operation in operations] == [
            "Склейка",
            "Кашировка",
            "Резка_плоттер",
            "Цифровая_печать",
        ]
        assert [operation.labor_hours_per_1000 for operation in operations] == [
            1110.428,
            65.285,
            3626.428,
            506.71,
        ]
        assert [operation.min_transfer_quantity_to_next for operation in operations] == [
            1000.0,
            1000.0,
            1000.0,
            None,
        ]


def test_seed_demo_data_removes_legacy_demo_records() -> None:
    with make_session() as session:
        old_center = WorkCenter(name="Печать", available_hours_per_day=8)
        old_route = Route(name="Маршрут A", description="Старый demo-маршрут")
        session.add_all([old_center, old_route])
        session.flush()
        session.add(
            RouteOperation(
                route_id=old_route.id,
                sequence_number=1,
                work_center_id=old_center.id,
                labor_hours_per_1000=4,
            )
        )
        session.add(
            Order(
                order_number="MVP-101",
                client_name="Клиент A",
                product_name="Коробка A",
                quantity=10_000,
                shipment_date=date(2026, 7, 1),
                route_id=old_route.id,
                status="Новый",
            )
        )
        session.commit()

        seed_demo_data(session)

        assert session.scalar(select(WorkCenter).where(WorkCenter.name == "Печать")) is None
        assert session.scalar(select(Route).where(Route.name == "Маршрут A")) is None
        assert session.scalar(select(Order).where(Order.order_number == "MVP-101")) is None


def test_reset_seed_data_leaves_only_excel_seed_dataset() -> None:
    with make_session() as session:
        session.add(WorkCenter(name="Лишний участок", available_hours_per_day=1))
        session.commit()

        reset_seed_data(session)

        assert session.scalar(select(WorkCenter).where(WorkCenter.name == "Лишний участок")) is None
        assert session.query(WorkCenter).count() == 6
        assert session.query(Route).count() == 8
        assert session.query(Order).count() == 5
