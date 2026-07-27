from datetime import date

import pytest

pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import Base
from app.db.models import Order, Route, RouteOperation, Setting, WorkCenter
from app.db.seed_data import (
    ROUTE_SPECS,
    WORK_CENTER_SPECS,
    reset_seed_data,
    seed_demo_data,
)


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
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


def test_seed_orders_receive_continuous_priorities_and_keep_manual_order() -> None:
    with make_session() as session:
        seed_demo_data(session)
        orders = session.scalars(select(Order).order_by(Order.priority)).all()
        assert [order.priority for order in orders] == list(range(1, len(orders) + 1))

        orders[0].priority, orders[-1].priority = (
            orders[-1].priority,
            orders[0].priority,
        )
        expected_numbers = [
            order.order_number
            for order in sorted(orders, key=lambda item: (item.priority, item.id))
        ]
        session.commit()

        seed_demo_data(session)
        reloaded = session.scalars(select(Order).order_by(Order.priority)).all()
        assert [order.order_number for order in reloaded] == expected_numbers
        assert [order.priority for order in reloaded] == list(
            range(1, len(reloaded) + 1)
        )


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
        assert [
            operation.min_transfer_quantity_to_next for operation in operations
        ] == [
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

        assert (
            session.scalar(select(WorkCenter).where(WorkCenter.name == "Печать"))
            is None
        )
        assert session.scalar(select(Route).where(Route.name == "Маршрут A")) is None
        assert (
            session.scalar(select(Order).where(Order.order_number == "MVP-101")) is None
        )


def test_reset_seed_data_leaves_only_excel_seed_dataset() -> None:
    with make_session() as session:
        session.add(WorkCenter(name="Лишний участок", available_hours_per_day=1))
        session.commit()

        reset_seed_data(session)

        assert (
            session.scalar(
                select(WorkCenter).where(WorkCenter.name == "Лишний участок")
            )
            is None
        )
        assert session.query(WorkCenter).count() == 6
        assert session.query(Route).count() == 8
        assert session.query(Order).count() == 5


def test_seed_planned_orders_do_not_start_or_finish_after_shipment_date() -> None:
    from app.constants import ORDER_STATUS_PLANNED
    from app.db.models import PlannedOperation, PlannedOperationDay
    from app.services.recalculation_service import RecalculationService

    with make_session() as session:
        seed_demo_data(session)
        RecalculationService(
            session, planning_start_date=date.today()
        ).recalculate_plan()

        planned_orders = session.scalars(
            select(Order).where(Order.status == ORDER_STATUS_PLANNED)
        ).all()
        assert planned_orders
        for order in planned_orders:
            assert order.calculated_start_date is not None
            assert order.calculated_start_date <= order.shipment_date
            last_finish = session.scalar(
                select(PlannedOperationDay.end_datetime)
                .join(PlannedOperationDay.planned_operation)
                .where(PlannedOperation.order_id == order.id)
                .order_by(PlannedOperationDay.end_datetime.desc())
                .limit(1)
            )
            assert last_finish is not None
            assert last_finish.date() <= order.shipment_date


def test_excel_105_plans_with_same_rules_as_capacity_precheck() -> None:
    from app.constants import ORDER_STATUS_CANCELLED, ORDER_STATUS_PLANNED
    from app.db.models import PlannedOperation, PlannedOperationDay
    from app.services.recalculation_service import RecalculationService
    from app.services.route_capacity_service import RouteCapacityService

    planning_start = date(2026, 7, 3)
    shipment_deadline = date(2026, 7, 31)

    with make_session() as session:
        seed_demo_data(session)
        route = session.scalar(select(Route).where(Route.name == "поток театры"))
        assert route is not None

        for order_number in ["EXCEL-101", "EXCEL-102", "EXCEL-103", "EXCEL-104"]:
            order = session.scalar(
                select(Order).where(Order.order_number == order_number)
            )
            assert order is not None
            order.status = ORDER_STATUS_CANCELLED

        excel_105 = session.scalar(
            select(Order).where(Order.order_number == "EXCEL-105")
        )
        assert excel_105 is not None
        excel_105.route_id = route.id
        excel_105.quantity = 100
        excel_105.shipment_date = shipment_deadline
        session.commit()

        RecalculationService(
            session, planning_start_date=planning_start
        ).recalculate_plan()
        session.refresh(excel_105)

        assert excel_105.status == ORDER_STATUS_PLANNED
        assert excel_105.calculated_start_date is not None

        last_finish = session.scalar(
            select(PlannedOperationDay.end_datetime)
            .join(PlannedOperationDay.planned_operation)
            .where(PlannedOperation.order_id == excel_105.id)
            .order_by(PlannedOperationDay.end_datetime.desc())
            .limit(1)
        )
        assert last_finish is not None
        assert last_finish.date() <= shipment_deadline

        capacity_service = RouteCapacityService(session)
        capacity = capacity_service.calculate_route_capacity(
            route.id,
            planning_start,
            shipment_deadline,
            planning_start_date=planning_start,
            exclude_order_id=excel_105.id,
        )
        assert capacity.max_quantity >= 100

        slots = capacity_service.find_available_shipment_slots_for_capacity(
            capacity,
            100,
            planning_start,
            shipment_deadline,
            planning_start_date=planning_start,
            exclude_order_id=excel_105.id,
        )
        assert shipment_deadline in slots
