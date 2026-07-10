from datetime import date

from app.constants import ORDER_STATUS_NEW
from app.planning.capacity_calendar import CapacityCalendar
from app.planning.entities import (
    PlanningOrder,
    PlanningRouteOperation,
    PlanningWorkCenter,
)
from app.planning.planner import PlanningEngine


def _operation_days(result, sequence_number: int):
    return sorted(
        [
            day
            for op in result.operations
            if op.sequence_number == sequence_number
            for day in op.days
        ],
        key=lambda day: day.start_datetime,
    )


def test_unchecked_work_center_keeps_existing_batch_placement_behavior() -> None:
    calendar = CapacityCalendar(
        [
            PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=31),
        ]
    )
    engine = PlanningEngine(calendar, planning_start_date=date(2026, 7, 1))
    route = (
        PlanningRouteOperation(
            id=1,
            sequence_number=1,
            work_center_id=1,
            work_center_name="Печать",
            labor_hours_per_1000=1,
            min_transfer_quantity_to_next=1000,
        ),
    )

    result = engine.plan_order(
        PlanningOrder(
            id=1, quantity=2000, shipment_date=date(2026, 7, 3), status=ORDER_STATUS_NEW
        ),
        route,
    )

    assert result.is_success
    assert len(result.operations) == 2
    assert calendar.work_center(1).prevent_order_interruption is False


def test_protected_work_center_does_not_place_other_order_between_batches() -> None:
    calendar = CapacityCalendar(
        [
            PlanningWorkCenter(
                id=1,
                name="Печать",
                available_hours_per_day=31,
                prevent_order_interruption=True,
            ),
        ]
    )
    engine = PlanningEngine(calendar, planning_start_date=date(2026, 7, 1))
    route = (
        PlanningRouteOperation(
            id=1,
            sequence_number=1,
            work_center_id=1,
            work_center_name="Печать",
            labor_hours_per_1000=1,
            min_transfer_quantity_to_next=1000,
        ),
    )

    blocker = engine.plan_order(
        PlanningOrder(
            id=2, quantity=1000, shipment_date=date(2026, 7, 2), status=ORDER_STATUS_NEW
        ),
        (
            PlanningRouteOperation(
                id=2,
                sequence_number=1,
                work_center_id=1,
                work_center_name="Печать",
                labor_hours_per_1000=1,
            ),
        ),
    )
    result = engine.plan_order(
        PlanningOrder(
            id=1, quantity=2000, shipment_date=date(2026, 7, 4), status=ORDER_STATUS_NEW
        ),
        route,
    )

    assert blocker.is_success
    assert result.is_success
    days = _operation_days(result, 1)
    assert len(result.operations) == 2
    assert (
        days[0].end_datetime.date().toordinal() + 1
        == days[1].start_datetime.date().toordinal()
    )
    blocker_start = min(
        day.start_datetime for op in blocker.operations for day in op.days
    )
    blocker_end = max(day.end_datetime for op in blocker.operations for day in op.days)
    assert (
        blocker_end <= days[0].start_datetime or days[-1].end_datetime <= blocker_start
    )


def test_protected_work_center_waits_until_next_input_batch_is_ready() -> None:
    calendar = CapacityCalendar(
        [
            PlanningWorkCenter(id=1, name="Первая", available_hours_per_day=62),
            PlanningWorkCenter(
                id=2,
                name="Защищенная",
                available_hours_per_day=62,
                prevent_order_interruption=True,
            ),
        ]
    )
    engine = PlanningEngine(calendar, planning_start_date=date(2026, 7, 1))
    route = (
        PlanningRouteOperation(
            id=1,
            sequence_number=1,
            work_center_id=1,
            work_center_name="Первая",
            labor_hours_per_1000=1,
            min_transfer_quantity_to_next=1000,
        ),
        PlanningRouteOperation(
            id=2,
            sequence_number=2,
            work_center_id=2,
            work_center_name="Защищенная",
            labor_hours_per_1000=1,
            min_transfer_quantity_to_next=1000,
        ),
    )

    result = engine.plan_order(
        PlanningOrder(
            id=1, quantity=2000, shipment_date=date(2026, 7, 3), status=ORDER_STATUS_NEW
        ),
        route,
    )

    assert result.is_success
    first_finishes = [
        max(day.end_datetime for day in op.days)
        for op in result.operations
        if op.sequence_number == 1
    ]
    protected_days = _operation_days(result, 2)
    assert protected_days[0].start_datetime >= min(first_finishes)
    assert protected_days[0].end_datetime >= max(first_finishes)
    assert protected_days[0].end_datetime == protected_days[1].start_datetime


def test_protected_block_may_cross_calendar_days() -> None:
    calendar = CapacityCalendar(
        [
            PlanningWorkCenter(
                id=1,
                name="Печать",
                available_hours_per_day=31,
                prevent_order_interruption=True,
            ),
        ]
    )
    engine = PlanningEngine(calendar, planning_start_date=date(2026, 7, 1))
    route = (
        PlanningRouteOperation(
            id=1,
            sequence_number=1,
            work_center_id=1,
            work_center_name="Печать",
            labor_hours_per_1000=1,
            min_transfer_quantity_to_next=1000,
        ),
    )

    result = engine.plan_order(
        PlanningOrder(
            id=1, quantity=2000, shipment_date=date(2026, 7, 3), status=ORDER_STATUS_NEW
        ),
        route,
    )

    assert result.is_success
    days = _operation_days(result, 1)
    assert days[0].date < days[1].date
    assert days[0].end_datetime.date() == date(2026, 7, 2)
    assert days[1].start_datetime.date() == date(2026, 7, 3)


def test_protected_work_center_allows_idle_time_between_orders() -> None:
    calendar = CapacityCalendar(
        [
            PlanningWorkCenter(
                id=1,
                name="Печать",
                available_hours_per_day=31,
                prevent_order_interruption=True,
            ),
        ]
    )
    engine = PlanningEngine(calendar, planning_start_date=date(2026, 7, 1))
    route = (
        PlanningRouteOperation(
            id=1,
            sequence_number=1,
            work_center_id=1,
            work_center_name="Печать",
            labor_hours_per_1000=1,
        ),
    )

    first = engine.plan_order(
        PlanningOrder(
            id=1, quantity=1000, shipment_date=date(2026, 7, 1), status=ORDER_STATUS_NEW
        ),
        route,
    )
    second = engine.plan_order(
        PlanningOrder(
            id=2, quantity=1000, shipment_date=date(2026, 7, 3), status=ORDER_STATUS_NEW
        ),
        route,
    )

    assert first.is_success
    assert second.is_success
    first_end = max(day.end_datetime for op in first.operations for day in op.days)
    second_start = min(
        day.start_datetime for op in second.operations for day in op.days
    )
    assert first_end < second_start


def test_protected_work_center_conflicts_when_only_split_capacity_exists() -> None:
    calendar = CapacityCalendar(
        [
            PlanningWorkCenter(
                id=1,
                name="Печать",
                available_hours_per_day=31,
                prevent_order_interruption=True,
            ),
        ]
    )
    engine = PlanningEngine(calendar, planning_start_date=date(2026, 7, 1))
    single_batch_route = (
        PlanningRouteOperation(
            id=1,
            sequence_number=1,
            work_center_id=1,
            work_center_name="Печать",
            labor_hours_per_1000=1,
        ),
    )
    protected_route = (
        PlanningRouteOperation(
            id=2,
            sequence_number=1,
            work_center_id=1,
            work_center_name="Печать",
            labor_hours_per_1000=1,
            min_transfer_quantity_to_next=1000,
        ),
    )

    blocker = engine.plan_order(
        PlanningOrder(
            id=2, quantity=1000, shipment_date=date(2026, 7, 2), status=ORDER_STATUS_NEW
        ),
        single_batch_route,
    )
    result = engine.plan_order(
        PlanningOrder(
            id=1, quantity=2000, shipment_date=date(2026, 7, 3), status=ORDER_STATUS_NEW
        ),
        protected_route,
    )

    assert blocker.is_success
    assert not result.is_success
    assert result.conflict is not None
    assert "невозможно непрерывно разместить" in result.conflict.reason
