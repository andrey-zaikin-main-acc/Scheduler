from datetime import date, datetime, time

import pytest

from app.planning.capacity_calendar import CapacityCalendar
from app.planning.entities import PlanningWorkCenter


def test_capacity_calendar_reserves_and_reports_free_hours() -> None:
    calendar = CapacityCalendar(
        [PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=8)]
    )
    day = date(2026, 7, 10)

    calendar.reserve(order_id=101, work_center_id=1, day=day, hours=6)

    assert calendar.occupied_hours(1, day) == 6
    assert calendar.free_hours(1, day) == 2


def test_capacity_calendar_rejects_overbooking() -> None:
    calendar = CapacityCalendar(
        [PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=8)]
    )
    day = date(2026, 7, 10)

    calendar.reserve(order_id=101, work_center_id=1, day=day, hours=7)

    with pytest.raises(ValueError):
        calendar.reserve(order_id=102, work_center_id=1, day=day, hours=2)


def test_capacity_calendar_returns_blocking_orders() -> None:
    calendar = CapacityCalendar(
        [PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=8)]
    )
    calendar.reserve(order_id=101, work_center_id=1, day=date(2026, 7, 9), hours=8)
    calendar.reserve(order_id=102, work_center_id=1, day=date(2026, 7, 10), hours=4)

    assert calendar.blocking_order_ids(
        work_center_id=1,
        start_date=date(2026, 7, 8),
        end_date=date(2026, 7, 10),
    ) == (101, 102)


def test_capacity_calendar_assigns_non_overlapping_latest_intraday_intervals() -> None:
    calendar = CapacityCalendar(
        [PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=8)]
    )
    day = date(2026, 7, 10)

    first = calendar.reserve(order_id=101, work_center_id=1, day=day, hours=3)
    second = calendar.reserve(order_id=102, work_center_id=1, day=day, hours=4)

    assert first.start_datetime.isoformat(sep=" ") == "2026-07-10 14:00:00"
    assert first.end_datetime.isoformat(sep=" ") == "2026-07-10 17:00:00"
    assert second.start_datetime.isoformat(sep=" ") == "2026-07-10 10:00:00"
    assert second.end_datetime.isoformat(sep=" ") == "2026-07-10 14:00:00"
    assert second.end_datetime <= first.start_datetime
    assert calendar.free_hours(1, day) == 1


def test_capacity_calendar_uses_work_center_start_time_for_bounds() -> None:
    calendar = CapacityCalendar(
        [
            PlanningWorkCenter(
                id=1,
                name="A",
                available_hours_per_day=8,
                workday_start_time=time(hour=8),
            ),
            PlanningWorkCenter(
                id=2,
                name="B",
                available_hours_per_day=6,
                workday_start_time=time(hour=10),
            ),
        ]
    )
    day = date(2026, 7, 10)

    assert tuple(
        value.isoformat(sep=" ") for value in calendar.workday_bounds(1, day)
    ) == (
        "2026-07-10 08:00:00",
        "2026-07-10 16:00:00",
    )
    assert tuple(
        value.isoformat(sep=" ") for value in calendar.workday_bounds(2, day)
    ) == (
        "2026-07-10 10:00:00",
        "2026-07-10 16:00:00",
    )


def test_capacity_calendar_carries_remainder_to_work_center_start_time() -> None:
    calendar = CapacityCalendar(
        [
            PlanningWorkCenter(
                id=1,
                name="B",
                available_hours_per_day=6,
                workday_start_time=time(hour=10),
            ),
        ]
    )

    placements = calendar.reserve_contiguous_forward(
        order_id=101,
        work_center_id=1,
        start_datetime=datetime(2026, 7, 10, 14),
        hours=4,
    )

    assert [item.start_datetime.isoformat(sep=" ") for item in placements] == [
        "2026-07-10 14:00:00",
        "2026-07-11 10:00:00",
    ]
    assert [item.end_datetime.isoformat(sep=" ") for item in placements] == [
        "2026-07-10 16:00:00",
        "2026-07-11 12:00:00",
    ]


def test_capacity_calendar_defaults_workday_start_to_09_00() -> None:
    calendar = CapacityCalendar(
        [PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=8)]
    )

    start, end = calendar.workday_bounds(1, date(2026, 7, 10))

    assert start.isoformat(sep=" ") == "2026-07-10 09:00:00"
    assert end.isoformat(sep=" ") == "2026-07-10 17:00:00"
