"""Backward operation scheduler for the MVP planning engine."""

from datetime import date, timedelta

from app.planning.capacity_calendar import CapacityCalendar
from app.planning.entities import PlanningConflict, ScheduledOperation, ScheduledOperationDay


def schedule_operation_backward(
    *,
    order_id: int,
    shipment_date: date,
    route_operation_id: int,
    work_center_id: int,
    sequence_number: int,
    required_hours: float,
    latest_allowed_date: date,
    earliest_allowed_date: date,
    capacity_calendar: CapacityCalendar,
) -> ScheduledOperation | PlanningConflict:
    """Schedule one operation as late as possible before or on the allowed date."""
    if required_hours <= 0:
        raise ValueError("Required hours must be greater than 0.")
    if earliest_allowed_date > latest_allowed_date:
        return _build_conflict(
            order_id=order_id,
            shipment_date=shipment_date,
            work_center_id=work_center_id,
            required_hours=required_hours,
            available_hours=0.0,
            blocking_order_ids=(),
            reason="Допустимое окно размещения пустое.",
        )

    remaining_hours = required_hours
    current_date = latest_allowed_date
    planned_days: list[tuple[date, float]] = []

    while remaining_hours > 0 and current_date >= earliest_allowed_date:
        free_hours = capacity_calendar.free_hours(work_center_id, current_date)
        if free_hours > 0:
            planned_hours = min(remaining_hours, free_hours)
            planned_days.append((current_date, planned_hours))
            remaining_hours -= planned_hours
        current_date -= timedelta(days=1)

    if remaining_hours > 0:
        available_hours = sum(hours for _, hours in planned_days)
        blocking_order_ids = capacity_calendar.blocking_order_ids(
            work_center_id=work_center_id,
            start_date=earliest_allowed_date,
            end_date=latest_allowed_date,
        )
        return _build_conflict(
            order_id=order_id,
            shipment_date=shipment_date,
            work_center_id=work_center_id,
            required_hours=required_hours,
            available_hours=available_hours,
            blocking_order_ids=blocking_order_ids,
            reason="Недостаточно свободной мощности в допустимом окне размещения.",
        )

    placements = [
        capacity_calendar.reserve(order_id=order_id, work_center_id=work_center_id, day=day, hours=hours)
        for day, hours in planned_days
    ]
    ordered_placements = tuple(sorted(placements, key=lambda placement: placement.date))
    return ScheduledOperation(
        order_id=order_id,
        route_operation_id=route_operation_id,
        work_center_id=work_center_id,
        sequence_number=sequence_number,
        required_hours=required_hours,
        planned_hours=sum(placement.hours for placement in ordered_placements),
        planned_start_date=ordered_placements[0].date,
        planned_end_date=ordered_placements[-1].date,
        days=ordered_placements,
    )


def _build_conflict(
    *,
    order_id: int,
    shipment_date: date,
    work_center_id: int,
    required_hours: float,
    available_hours: float,
    blocking_order_ids: tuple[int, ...],
    reason: str,
) -> PlanningConflict:
    return PlanningConflict(
        order_id=order_id,
        shipment_date=shipment_date,
        work_center_id=work_center_id,
        required_hours=required_hours,
        available_hours=available_hours,
        deficit_hours=max(0.0, required_hours - available_hours),
        blocking_order_ids=blocking_order_ids,
        reason=reason,
    )
