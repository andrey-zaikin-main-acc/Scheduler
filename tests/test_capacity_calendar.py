from datetime import date

import pytest

from app.planning.capacity_calendar import CapacityCalendar
from app.planning.entities import PlanningWorkCenter


def test_capacity_calendar_reserves_and_reports_free_hours() -> None:
    calendar = CapacityCalendar([PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=8)])
    day = date(2026, 7, 10)

    calendar.reserve(order_id=101, work_center_id=1, day=day, hours=6)

    assert calendar.occupied_hours(1, day) == 6
    assert calendar.free_hours(1, day) == 2


def test_capacity_calendar_rejects_overbooking() -> None:
    calendar = CapacityCalendar([PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=8)])
    day = date(2026, 7, 10)

    calendar.reserve(order_id=101, work_center_id=1, day=day, hours=7)

    with pytest.raises(ValueError):
        calendar.reserve(order_id=102, work_center_id=1, day=day, hours=2)


def test_capacity_calendar_returns_blocking_orders() -> None:
    calendar = CapacityCalendar([PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=8)])
    calendar.reserve(order_id=101, work_center_id=1, day=date(2026, 7, 9), hours=8)
    calendar.reserve(order_id=102, work_center_id=1, day=date(2026, 7, 10), hours=4)

    assert calendar.blocking_order_ids(
        work_center_id=1,
        start_date=date(2026, 7, 8),
        end_date=date(2026, 7, 10),
    ) == (101, 102)
