"""Past-date validation in the atomic draft commit production path."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.constants import ORDER_STATUS_CANCELLED, ORDER_STATUS_NEW
from app.db.database import Base
from app.db.models import Order, PlannedOperation, PlanningConflict, RecalculationRun, Route, RouteOperation, WorkCenter
from app.services.draft_commit_service import DraftBundle, DraftCommitService


TODAY = date(2026, 8, 6)


@pytest.fixture
def context():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    center = WorkCenter(name="WC", available_hours_per_day=248)
    route = Route(name="R")
    session.add_all([center, route]); session.flush()
    operation = RouteOperation(route_id=route.id, sequence_number=1, work_center_id=center.id,
                               labor_hours_per_1000=1)
    session.add(operation); session.commit()
    return session, route, center, operation


def row(route_id, *, identity=-1, mode="От даты запуска", active_date=TODAY,
        status=ORDER_STATUS_NEW, number="125"):
    return {
        "id": identity, "_draft_id": identity, "priority": 1, "order_number": number,
        "client_name": "C", "product_name": "P", "quantity": 10,
        "shipment_date": active_date if mode == "От даты отгрузки" else date(2020, 1, 1),
        "fixed_start_date": active_date if mode == "От даты запуска" else date(2020, 1, 1),
        "route_id": route_id, "status": status, "planning_mode": mode,
        "child_group_key": None, "child_sequence_number": None,
        "is_child_order": False, "is_linked_child_group": False,
    }


def persisted(context, *, status="", mode="От даты запуска"):
    session, route, _, _ = context
    order = Order(priority=1, order_number="125", client_name="C", product_name="P", quantity=10,
                  shipment_date=date(2020, 1, 1), fixed_start_date=date(2020, 1, 1),
                  planning_mode=mode, route_id=route.id, status=status)
    session.add(order); session.commit()
    return order


def plan(context, order):
    session, _, center, operation = context
    session.add(PlannedOperation(
        order_id=order.id, route_operation_id=operation.id, work_center_id=center.id,
        sequence_number=1, planned_start_date=date(2020, 1, 1),
        planned_end_date=date(2020, 1, 1), required_hours=1, planned_hours=1, status="Запланирован",
    )); session.commit()


def conflict(context, order):
    session, _, _, _ = context
    session.add(PlanningConflict(order_id=order.id, shipment_date=order.shipment_date,
                                 required_hours=1, available_hours=0, deficit_hours=1, reason="old"))
    session.commit()


@pytest.mark.parametrize("mode", ["От даты запуска", "От даты отгрузки"])
@pytest.mark.parametrize("value,allowed", [
    (date(2026, 8, 5), False), (TODAY, True), (date(2026, 8, 7), True),
])
def test_new_order_date_boundary_and_active_mode(context, mode, value, allowed):
    session, route, _, _ = context
    errors = DraftCommitService(session, current_date=TODAY).validate(
        DraftBundle(orders=[row(route.id, mode=mode, active_date=value)]), sections={"orders"})
    assert (not any("раньше текущей даты" in error for error in errors)) is allowed


def test_temporary_rows_and_all_errors_are_reported(context):
    session, route, _, _ = context
    rows = [row(route.id, identity=-2, active_date=date(2026, 8, 5), number="125"),
            row(route.id, identity=-3, active_date=date(2026, 8, 4), number="126") | {"priority": 2}]
    errors = DraftCommitService(session, current_date=TODAY).validate(DraftBundle(orders=rows), sections={"orders"})
    past = [error for error in errors if "раньше текущей даты" in error]
    assert len(past) == 2 and "ID -2" in past[0] and "ID -3" in past[1]


@pytest.mark.parametrize("mode", ["От даты запуска", "От даты отгрузки"])
def test_previously_conflicted_past_date_is_rejected(context, mode):
    session, route, _, _ = context
    order = persisted(context, mode=mode); conflict(context, order)
    errors = DraftCommitService(session, current_date=TODAY).validate(
        DraftBundle(orders=[row(route.id, identity=order.id, mode=mode, active_date=date(2026, 8, 5), status="")]),
        sections={"orders"})
    assert any("для ранее конфликтного заказа" in error for error in errors)


@pytest.mark.parametrize("mode", ["От даты запуска", "От даты отгрузки"])
def test_previously_planned_past_date_is_allowed_unless_manually_new(context, mode):
    session, route, _, _ = context
    order = persisted(context, mode=mode); plan(context, order)
    draft_row = row(route.id, identity=order.id, mode=mode, active_date=date(2026, 8, 5), status="")
    service = DraftCommitService(session, current_date=TODAY)
    assert not any("раньше текущей даты" in error for error in service.validate(
        DraftBundle(orders=[draft_row]), sections={"orders"}))
    draft_row["status"] = ORDER_STATUS_NEW
    assert any("для нового заказа" in error for error in service.validate(
        DraftBundle(orders=[draft_row]), sections={"orders"}))


def test_cancelled_order_and_inactive_date_do_not_block(context):
    session, route, _, _ = context
    draft_row = row(route.id, status=ORDER_STATUS_CANCELLED, active_date=date(2026, 8, 5))
    assert not any("раньше текущей даты" in error for error in DraftCommitService(
        session, current_date=TODAY).validate(DraftBundle(orders=[draft_row]), sections={"orders"}))
    draft_row = row(route.id, active_date=TODAY)
    draft_row["shipment_date"] = date(2020, 1, 1)
    assert DraftCommitService(session, current_date=TODAY).validate(
        DraftBundle(orders=[draft_row]), sections={"orders"}) == []


def test_missing_active_date_keeps_required_error(context):
    session, route, _, _ = context
    errors = DraftCommitService(session, current_date=TODAY).validate(
        DraftBundle(orders=[row(route.id, active_date=None)]), sections={"orders"})
    assert any("Заданная дата запуска»: обязательное поле" in error for error in errors)


def test_corrupt_simultaneous_plan_and_conflict_is_integrity_error(context):
    session, route, _, _ = context
    order = persisted(context); plan(context, order); conflict(context, order)
    errors = DraftCommitService(session, current_date=TODAY).validate(
        DraftBundle(orders=[row(route.id, identity=order.id, status="")]), sections={"orders"})
    assert any("ошибка целостности" in error for error in errors)


def test_failed_then_corrected_production_commit_is_atomic(context):
    session, route, _, operation = context
    order = persisted(context); plan(context, order); conflict(context, order)
    # Remove the deliberately corrupt combination: this scenario starts from an old conflict only.
    session.query(PlannedOperation).delete(); session.commit()
    calls = []
    class Recalc:
        def __init__(self, db): calls.append(db)
        def recalculate_plan(self):
            return type("Summary", (), {"planned_orders": 1, "conflicts": 0})()
    before = (session.query(Order).one().fixed_start_date,
              session.query(PlanningConflict).count(), session.query(RecalculationRun).count())
    draft_row = row(route.id, identity=order.id, active_date=date(2026, 8, 5), status="")
    service = DraftCommitService(session, Recalc, current_date=TODAY)
    failed = service.commit_and_recalculate(DraftBundle(orders=[draft_row], pending_delete_ids={999}), sections={"orders"})
    assert not failed.ok and calls == []
    assert (session.query(Order).one().fixed_start_date,
            session.query(PlanningConflict).count(), session.query(RecalculationRun).count()) == before
    draft_row["fixed_start_date"] = TODAY
    succeeded = service.commit_and_recalculate(DraftBundle(orders=[draft_row]), sections={"orders"})
    assert succeeded.ok and len(calls) == 1 and session.query(Order).one().fixed_start_date == TODAY
