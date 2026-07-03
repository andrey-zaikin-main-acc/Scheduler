"""Capacity unit helpers while WorkCenter field names are being migrated."""

import calendar
from datetime import date


def daily_capacity_from_monthly(monthly_capacity: float, day: date) -> float:
    """Return the capacity available on ``day`` from a monthly capacity value."""
    return monthly_capacity / calendar.monthrange(day.year, day.month)[1]


def total_capacity_between(
    monthly_capacity: float, start_date: date, end_date: date
) -> float:
    """Return total capacity for an inclusive date range, recalculating per month."""
    if start_date > end_date:
        return 0.0
    total = 0.0
    current = start_date
    while current <= end_date:
        total += daily_capacity_from_monthly(monthly_capacity, current)
        current = current.fromordinal(current.toordinal() + 1)
    return total
