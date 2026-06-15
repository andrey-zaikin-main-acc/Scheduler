"""Partial transfer helpers for route operations."""

from datetime import date

from app.planning.entities import ScheduledOperation
from app.planning.time_requirements import calculate_first_transfer_hours


def calculate_transfer_ready_date(
    *,
    scheduled_operation: ScheduledOperation,
    order_quantity: float,
    min_transfer_quantity: float | None,
    labor_hours_per_1000: float,
) -> date:
    """Return the first date when the next operation may start under MVP transfer rules."""
    hours_to_first_transfer = calculate_first_transfer_hours(
        order_quantity=order_quantity,
        min_transfer_quantity=min_transfer_quantity,
        labor_hours_per_1000=labor_hours_per_1000,
    )
    accumulated_hours = 0.0
    for placement in sorted(scheduled_operation.days, key=lambda day: day.date):
        accumulated_hours += placement.hours
        if accumulated_hours >= hours_to_first_transfer:
            return placement.date
    return scheduled_operation.planned_end_date


def transfer_is_ready_before_next_start(
    *,
    scheduled_operation: ScheduledOperation,
    next_operation_start: date,
    order_quantity: float,
    min_transfer_quantity: float | None,
    labor_hours_per_1000: float,
) -> bool:
    """Return True when the first transferable batch is ready before the next operation starts."""
    ready_date = calculate_transfer_ready_date(
        scheduled_operation=scheduled_operation,
        order_quantity=order_quantity,
        min_transfer_quantity=min_transfer_quantity,
        labor_hours_per_1000=labor_hours_per_1000,
    )
    return ready_date <= next_operation_start
