from datetime import date

import pytest

pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.constants import ORDER_STATUS_NEW, ORDER_STATUS_PLANNED, PLANNING_MODE_START
from app.db.database import Base
from app.db.models import (
    Order,
    PlanChange,
    PlannedOperation,
    PlannedOperationDay,
    PlanningConflict,
    Route,
    RouteOperation,
    WorkCenter,
)
from app.repositories.orders_repository import OrdersRepository
from app.services.recalculation_service import RecalculationService


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    with session_factory() as session:
        yield session


def create_route_with_operation(
    session: Session, *, hours_per_day: float, labor_hours_per_1000: float
) -> Route:
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
    route = create_route_with_operation(
        session, hours_per_day=248, labor_hours_per_1000=8
    )
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

    summary = RecalculationService(
        session, planning_start_date=date(2026, 7, 1)
    ).recalculate_plan()

    assert summary.planned_orders == 1
    assert summary.conflicts == 0
    assert session.query(PlannedOperation).count() == 1
    assert session.query(PlannedOperationDay).count() == 1
    assert session.query(PlanningConflict).count() == 0
    assert order.status == ""
    assert order.calculated_start_date == date(2026, 7, 10)


def test_recalculation_service_persists_conflict(session: Session) -> None:
    route = create_route_with_operation(
        session, hours_per_day=1, labor_hours_per_1000=3
    )
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

    summary = RecalculationService(
        session, planning_start_date=date(2026, 7, 10)
    ).recalculate_plan()

    conflict = session.query(PlanningConflict).one()
    assert summary.planned_orders == 0
    assert summary.conflicts == 1
    assert session.query(PlannedOperation).count() == 0
    assert order.status == ""
    assert conflict.order_id == order.id
    assert conflict.deficit_hours == pytest.approx(3 - 1 / 31)


def test_recalculation_service_clears_previous_plan(session: Session) -> None:
    route = create_route_with_operation(
        session, hours_per_day=248, labor_hours_per_1000=8
    )
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


def test_recalculation_service_persists_plan_changes(session: Session) -> None:
    route = create_route_with_operation(
        session, hours_per_day=248, labor_hours_per_1000=8
    )
    order = Order(
        order_number="R-004",
        client_name="Клиент",
        product_name="Продукт",
        quantity=1000,
        shipment_date=date(2026, 7, 10),
        route_id=route.id,
        status=ORDER_STATUS_NEW,
    )
    session.add(order)
    session.commit()

    RecalculationService(
        session, planning_start_date=date(2026, 7, 1)
    ).recalculate_plan()

    changes = session.query(PlanChange).all()
    assert len(changes) == 1
    assert changes[0].change_type == "created"
    assert changes[0].new_start_date == date(2026, 7, 10)


def test_recalculation_persists_high_capacity_order_within_shipment_date(
    session: Session,
) -> None:
    route = create_route_with_operation(
        session, hours_per_day=930, labor_hours_per_1000=20
    )
    order = Order(
        order_number="R-005",
        client_name="Клиент",
        product_name="Продукт",
        quantity=1000,
        shipment_date=date(2026, 7, 10),
        route_id=route.id,
        status=ORDER_STATUS_NEW,
    )
    session.add(order)
    session.commit()

    summary = RecalculationService(
        session, planning_start_date=date(2026, 7, 10)
    ).recalculate_plan()

    assert summary.planned_orders == 1
    assert summary.conflicts == 0
    assert order.status == ""
    assert order.calculated_start_date == order.shipment_date
    assert session.query(PlannedOperation).count() == 1


def test_recalculation_recomputes_start_and_status_after_shipment_date_change(
    session: Session,
) -> None:
    route = create_route_with_operation(
        session, hours_per_day=248, labor_hours_per_1000=8
    )
    order = Order(
        order_number="R-006",
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
    assert order.status == ""
    assert order.calculated_start_date == date(2026, 7, 10)

    order.shipment_date = date(2026, 7, 1)
    session.commit()
    service.recalculate_plan()

    assert order.status == ""
    assert order.calculated_start_date == date(2026, 7, 1)
    last_day = session.query(PlannedOperationDay).one()
    assert last_day.end_datetime.date() <= order.shipment_date


def test_order_update_clears_stale_calculated_start_date_before_recalculation(
    session: Session,
) -> None:
    route = create_route_with_operation(
        session, hours_per_day=248, labor_hours_per_1000=8
    )
    order = Order(
        order_number="R-007",
        client_name="Клиент",
        product_name="Продукт",
        quantity=1000,
        shipment_date=date(2026, 7, 10),
        route_id=route.id,
        status=ORDER_STATUS_PLANNED,
        calculated_start_date=date(2026, 7, 10),
    )
    session.add(order)
    session.commit()

    updated = OrdersRepository(session).update_order(
        order.id,
        order_number="R-007",
        client_name="Клиент",
        product_name="Продукт",
        quantity=1000,
        shipment_date=date(2026, 7, 1),
        route_id=route.id,
        status=ORDER_STATUS_NEW,
    )

    assert updated is not None
    assert updated.calculated_start_date is None

    RecalculationService(
        session, planning_start_date=date(2026, 7, 1)
    ).recalculate_plan()

    assert updated.status == ""
    assert updated.calculated_start_date == date(2026, 7, 1)


def test_cancelled_order_is_kept_but_excluded_from_recalculation(
    session: Session,
) -> None:
    from app.constants import ORDER_STATUS_CANCELLED

    route = create_route_with_operation(
        session, hours_per_day=248, labor_hours_per_1000=8
    )
    order = Order(
        order_number="R-CANCEL",
        client_name="Клиент",
        product_name="Продукт",
        quantity=1000,
        shipment_date=date(2026, 7, 10),
        route_id=route.id,
        status=ORDER_STATUS_CANCELLED,
    )
    session.add(order)
    session.commit()

    summary = RecalculationService(
        session, planning_start_date=date(2026, 7, 1)
    ).recalculate_plan()

    assert summary.planned_orders == 0
    assert summary.conflicts == 0
    assert session.get(Order, order.id) is order
    assert order.status == ORDER_STATUS_CANCELLED
    assert session.query(PlannedOperation).filter_by(order_id=order.id).count() == 0
    assert session.query(PlanningConflict).filter_by(order_id=order.id).count() == 0


def test_conflicted_order_participates_again_and_can_become_planned(
    session: Session,
) -> None:
    route = create_route_with_operation(
        session, hours_per_day=248, labor_hours_per_1000=8
    )
    order = Order(
        order_number="R-RETRY",
        client_name="Клиент",
        product_name="Продукт",
        quantity=1000,
        shipment_date=date(2026, 7, 10),
        route_id=route.id,
        status=ORDER_STATUS_NEW,
    )
    session.add(order)
    session.commit()

    RecalculationService(
        session, planning_start_date=date(2026, 7, 1)
    ).recalculate_plan()

    assert order.status == ""
    assert session.query(PlannedOperation).filter_by(order_id=order.id).count() == 1


def test_fallback_sort_ignores_status_and_shipment_date() -> None:
    from app.planning.entities import PlanningOrder
    from app.planning.order_preparation import PreparedOrder, sort_prepared_orders

    planned = PreparedOrder(
        PlanningOrder(2, 1000, date(2026, 7, 20), ORDER_STATUS_PLANNED), (), 0
    )
    new = PreparedOrder(
        PlanningOrder(1, 1000, date(2026, 7, 10), ORDER_STATUS_NEW), (), 0
    )

    assert sort_prepared_orders([planned, new]) == (new, planned)


def test_start_driven_order_without_shipment_date_is_planned_from_fixed_date(
    session: Session,
) -> None:
    route = create_route_with_operation(session, hours_per_day=248, labor_hours_per_1000=8)
    order = Order(
        order_number="START-NO-DEADLINE", client_name="Клиент", product_name="Продукт",
        quantity=1000, shipment_date=None, fixed_start_date=date(2026, 7, 10),
        planning_mode=PLANNING_MODE_START, route_id=route.id, status=ORDER_STATUS_NEW,
    )
    session.add(order)
    summary = RecalculationService(session, planning_start_date=date(2026, 7, 1)).recalculate_plan()

    assert summary.planned_orders == 1
    # The requested start is shown in fixed_start_date; only the opposite,
    # calculated shipment date is populated for start-driven planning.
    assert order.calculated_start_date is None
    assert order.calculated_shipment_date == date(2026, 7, 10)
    assert session.query(PlanningConflict).count() == 0


def test_start_driven_conflict_can_store_null_shipment_date(session: Session) -> None:
    route = create_route_with_operation(session, hours_per_day=1, labor_hours_per_1000=3)
    route.is_active = False
    order = Order(
        order_number="START-CONFLICT", client_name="Клиент", product_name="Продукт",
        quantity=1000, shipment_date=None, fixed_start_date=date(2026, 7, 10),
        planning_mode=PLANNING_MODE_START, route_id=route.id, status=ORDER_STATUS_NEW,
    )
    session.add(order)
    summary = RecalculationService(session, planning_start_date=date(2026, 7, 1)).recalculate_plan()

    conflict = session.query(PlanningConflict).one()
    assert summary.conflicts == 1
    assert conflict.shipment_date is None
    assert order.calculated_start_date is None
    assert order.calculated_shipment_date is None


def test_conflict_survives_two_consecutive_recalculations(session: Session) -> None:
    route = create_route_with_operation(session, hours_per_day=1, labor_hours_per_1000=3)
    route.is_active = False
    order = Order(
        order_number="REPEAT-CONFLICT", client_name="Клиент", product_name="Продукт",
        quantity=1000, shipment_date=date(2026, 7, 10), route_id=route.id,
        status=ORDER_STATUS_NEW,
    )
    session.add(order); session.flush()
    service = RecalculationService(session, planning_start_date=date(2026, 7, 1))

    first = service.recalculate_plan()
    second = service.recalculate_plan()

    assert first.conflicts == second.conflicts == 1
    assert session.query(PlanningConflict).filter_by(order_id=order.id).count() == 1
    assert session.query(PlannedOperation).filter_by(order_id=order.id).count() == 0


def test_previously_planned_order_stays_cancelled(session: Session) -> None:
    from app.constants import ORDER_STATUS_CANCELLED
    route = create_route_with_operation(session, hours_per_day=248, labor_hours_per_1000=8)
    order = Order(order_number="CANCEL-OLD", client_name="C", product_name="P", quantity=1000,
                  shipment_date=date(2026, 7, 10), route_id=route.id, status=ORDER_STATUS_NEW)
    session.add(order)
    service = RecalculationService(session, planning_start_date=date(2026, 7, 1))
    service.recalculate_plan()
    order.status = ORDER_STATUS_CANCELLED
    service.recalculate_plan()

    assert order.priority == 0
    assert order.calculated_start_date is None
    assert order.calculated_shipment_date is None
    assert session.query(PlannedOperation).filter_by(order_id=order.id).count() == 0
