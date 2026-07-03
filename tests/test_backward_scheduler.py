from datetime import date

from app.planning.backward_scheduler import schedule_operation_backward
from app.planning.capacity_calendar import CapacityCalendar
from app.planning.entities import (
    PlanningConflict,
    PlanningWorkCenter,
    ScheduledOperation,
)


def test_schedule_operation_backward_splits_hours_across_days() -> None:
    calendar = CapacityCalendar(
        [PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=248)]
    )

    result = schedule_operation_backward(
        order_id=101,
        shipment_date=date(2026, 7, 10),
        route_operation_id=1,
        work_center_id=1,
        sequence_number=1,
        required_hours=18,
        latest_allowed_date=date(2026, 7, 10),
        earliest_allowed_date=date(2026, 7, 1),
        capacity_calendar=calendar,
    )

    assert isinstance(result, ScheduledOperation)
    assert result.planned_start_date == date(2026, 7, 8)
    assert result.planned_end_date == date(2026, 7, 10)
    assert [(day.date, day.hours) for day in result.days] == [
        (date(2026, 7, 8), 2),
        (date(2026, 7, 9), 8),
        (date(2026, 7, 10), 8),
    ]


def test_schedule_operation_backward_uses_remaining_capacity() -> None:
    calendar = CapacityCalendar(
        [PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=248)]
    )
    calendar.reserve(order_id=100, work_center_id=1, day=date(2026, 7, 10), hours=6)

    result = schedule_operation_backward(
        order_id=101,
        shipment_date=date(2026, 7, 10),
        route_operation_id=1,
        work_center_id=1,
        sequence_number=1,
        required_hours=4,
        latest_allowed_date=date(2026, 7, 10),
        earliest_allowed_date=date(2026, 7, 1),
        capacity_calendar=calendar,
    )

    assert isinstance(result, ScheduledOperation)
    assert [(day.date, day.hours) for day in result.days] == [
        (date(2026, 7, 9), 2),
        (date(2026, 7, 10), 2),
    ]


def test_schedule_operation_backward_returns_conflict_when_window_is_too_small() -> (
    None
):
    calendar = CapacityCalendar(
        [PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=248)]
    )
    calendar.reserve(order_id=100, work_center_id=1, day=date(2026, 7, 10), hours=8)

    result = schedule_operation_backward(
        order_id=101,
        shipment_date=date(2026, 7, 10),
        route_operation_id=1,
        work_center_id=1,
        sequence_number=1,
        required_hours=4,
        latest_allowed_date=date(2026, 7, 10),
        earliest_allowed_date=date(2026, 7, 10),
        capacity_calendar=calendar,
    )

    assert isinstance(result, PlanningConflict)
    assert result.deficit_hours == 4
    assert result.blocking_order_ids == (100,)


def test_schedule_operation_backward_uses_calendar_dates_for_aggregate_window() -> None:
    calendar = CapacityCalendar(
        [PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=108792.84)]
    )
    calendar.reserve(
        order_id=100,
        work_center_id=1,
        day=date(2026, 6, 26),
        hours=1,
    )

    result = schedule_operation_backward(
        order_id=101,
        shipment_date=date(2026, 6, 26),
        route_operation_id=1,
        work_center_id=1,
        sequence_number=1,
        required_hours=3626.428,
        latest_allowed_date=date(2026, 6, 26),
        earliest_allowed_date=date(2026, 6, 25),
        capacity_calendar=calendar,
    )

    assert isinstance(result, ScheduledOperation)
    assert result.planned_start_date == date(2026, 6, 25)
    assert result.planned_end_date == date(2026, 6, 26)
    assert result.planned_start_date <= result.planned_end_date
