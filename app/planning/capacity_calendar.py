"""In-memory capacity calendar for pure planning calculations."""

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.planning.capacity_units import daily_capacity_from_monthly
from app.planning.entities import PlanningWorkCenter, ScheduledOperationDay

NORMALIZED_DAY_START = time.min
NORMALIZED_DAY_END = time.max


@dataclass(frozen=True)
class CapacityReservation:
    """Reservation metadata stored in the capacity calendar."""

    order_id: int
    work_center_id: int
    date: date
    hours: float
    start_datetime: datetime
    end_datetime: datetime


class CapacityCalendar:
    """Track available, occupied and free intervals per work center and day."""

    def __init__(
        self, work_centers: list[PlanningWorkCenter] | tuple[PlanningWorkCenter, ...]
    ) -> None:
        self._work_centers = {
            work_center.id: work_center for work_center in work_centers
        }
        self._occupied_hours: dict[tuple[int, date], float] = defaultdict(float)
        self._reservations: dict[tuple[int, date], list[CapacityReservation]] = (
            defaultdict(list)
        )

    def available_hours(self, work_center_id: int, day: date) -> float:
        """Return daily available capacity for a work center on a calendar date.

        The persisted ``available_hours_per_day`` value currently stores the
        monthly production capacity.  Daily capacity is calculated from the
        actual number of days in the month of ``day``.
        """
        monthly_capacity = self._get_work_center(work_center_id).available_hours_per_day
        return daily_capacity_from_monthly(monthly_capacity, day)

    def workday_bounds(
        self, work_center_id: int, day: date
    ) -> tuple[datetime, datetime]:
        """Return normalized technical bounds of a calendar date.

        ``available_hours_per_day`` is production capacity, not a calendar shift
        duration.  The returned datetimes are only normalized Gantt anchors
        inside the calendar date and must not be interpreted as actual shift
        times.
        """
        self._get_work_center(work_center_id)
        return datetime.combine(day, NORMALIZED_DAY_START), datetime.combine(
            day, NORMALIZED_DAY_END
        )

    def occupied_hours(self, work_center_id: int, day: date) -> float:
        """Return occupied hours for a work center on a date."""
        return self._occupied_hours[(work_center_id, day)]

    def free_hours(self, work_center_id: int, day: date) -> float:
        """Return free hours for a work center on a date."""
        return max(
            0.0,
            self.available_hours(work_center_id, day)
            - self.occupied_hours(work_center_id, day),
        )

    def reserve(
        self,
        *,
        order_id: int,
        work_center_id: int,
        day: date,
        hours: float,
        quantity_part: float | None = None,
        latest_end_datetime: datetime | None = None,
    ) -> ScheduledOperationDay:
        """Reserve the latest free non-overlapping interval on one work center date."""
        if hours <= 0:
            raise ValueError("Reserved hours must be greater than 0.")
        interval = self._find_latest_free_interval(
            work_center_id, day, hours, latest_end_datetime
        )
        if interval is None:
            raise ValueError("Reserved hours exceed free capacity.")
        start_datetime, end_datetime = interval

        key = (work_center_id, day)
        self._occupied_hours[key] += hours
        reservation = CapacityReservation(
            order_id=order_id,
            work_center_id=work_center_id,
            date=day,
            hours=hours,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
        )
        self._reservations[key].append(reservation)
        self._reservations[key].sort(key=lambda item: item.start_datetime)
        return ScheduledOperationDay(
            work_center_id=work_center_id,
            date=day,
            hours=hours,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            quantity_part=quantity_part,
        )

    def find_earliest_contiguous_start(
        self, work_center_id: int, not_before: datetime, hours: float
    ) -> datetime:
        """Return earliest start where an uninterrupted order operation can fit."""
        candidate = self._normalize_to_work_time(work_center_id, not_before)
        while True:
            if self._can_reserve_contiguous(work_center_id, candidate, hours):
                return candidate
            candidate = self._next_reservation_end_or_next_day(
                work_center_id, candidate
            )

    def reserve_contiguous_forward(
        self,
        *,
        order_id: int,
        work_center_id: int,
        start_datetime: datetime,
        hours: float,
        quantity_part: float | None = None,
    ) -> tuple[ScheduledOperationDay, ...]:
        """Reserve a contiguous operation from a start datetime forward."""
        if hours <= 0:
            raise ValueError("Reserved hours must be greater than 0.")
        if not self._can_reserve_contiguous(work_center_id, start_datetime, hours):
            raise ValueError("Reserved hours exceed contiguous free capacity.")

        remaining = hours
        cursor = self._normalize_to_work_time(work_center_id, start_datetime)
        placements: list[ScheduledOperationDay] = []
        while remaining > 1e-9:
            work_start, work_end = self.workday_bounds(work_center_id, cursor.date())
            cursor = max(cursor, work_start)
            remaining_day_hours = self._capacity_between_datetimes(
                work_center_id, cursor, work_end
            )
            used_hours = min(remaining, remaining_day_hours)
            end_datetime = cursor + self._hours_to_normalized_delta(
                work_center_id, cursor.date(), used_hours
            )
            if end_datetime > work_end:
                end_datetime = work_end
            key = (work_center_id, cursor.date())
            self._occupied_hours[key] += used_hours
            reservation = CapacityReservation(
                order_id=order_id,
                work_center_id=work_center_id,
                date=cursor.date(),
                hours=used_hours,
                start_datetime=cursor,
                end_datetime=end_datetime,
            )
            self._reservations[key].append(reservation)
            self._reservations[key].sort(key=lambda item: item.start_datetime)
            placements.append(
                ScheduledOperationDay(
                    work_center_id=work_center_id,
                    date=cursor.date(),
                    hours=used_hours,
                    start_datetime=cursor,
                    end_datetime=end_datetime,
                    quantity_part=(
                        None
                        if quantity_part is None
                        else quantity_part * used_hours / hours
                    ),
                )
            )
            remaining -= used_hours
            cursor = self._normalize_to_work_time(
                work_center_id,
                datetime.combine(cursor.date() + timedelta(days=1), time.min),
            )
        return tuple(placements)

    def free_hours_before(
        self, work_center_id: int, day: date, latest_end_datetime: datetime
    ) -> float:
        """Return free hours on a date that can finish no later than the given datetime."""
        work_start, work_end = self.workday_bounds(work_center_id, day)
        cursor_end = min(work_end, latest_end_datetime)
        if cursor_end <= work_start:
            return 0.0
        free = 0.0
        for reservation in sorted(
            self._reservations.get((work_center_id, day), []),
            key=lambda r: r.start_datetime,
            reverse=True,
        ):
            if reservation.end_datetime <= cursor_end:
                free += self._capacity_between_datetimes(
                    work_center_id, reservation.end_datetime, cursor_end
                )
                cursor_end = min(cursor_end, reservation.start_datetime)
            elif reservation.start_datetime < cursor_end:
                cursor_end = reservation.start_datetime
        free += self._capacity_between_datetimes(work_center_id, work_start, cursor_end)
        return free

    def total_free_hours(
        self, *, work_center_id: int, start_date: date, end_date: date
    ) -> float:
        """Return total free hours in an inclusive date window."""
        if start_date > end_date:
            return 0.0
        total = 0.0
        current = start_date
        while current <= end_date:
            total += self.free_hours(work_center_id, current)
            current = current.fromordinal(current.toordinal() + 1)
        return total

    def blocking_order_ids(
        self, *, work_center_id: int, start_date: date, end_date: date
    ) -> tuple[int, ...]:
        """Return orders occupying a work center in an inclusive date window."""
        order_ids: set[int] = set()
        current = start_date
        while current <= end_date:
            order_ids.update(
                r.order_id
                for r in self._reservations.get((work_center_id, current), [])
            )
            current = current.fromordinal(current.toordinal() + 1)
        return tuple(sorted(order_ids))

    def snapshot(
        self,
    ) -> tuple[
        dict[tuple[int, date], float], dict[tuple[int, date], list[CapacityReservation]]
    ]:
        """Return a restorable snapshot of occupied hours and reservations."""
        return dict(self._occupied_hours), deepcopy(dict(self._reservations))

    def restore(
        self,
        snapshot: tuple[
            dict[tuple[int, date], float],
            dict[tuple[int, date], list[CapacityReservation]],
        ],
    ) -> None:
        """Restore occupied hours and reservations from a snapshot."""
        occupied_hours, reservations = snapshot
        self._occupied_hours = defaultdict(float, occupied_hours)
        self._reservations = defaultdict(list, reservations)

    def _find_latest_free_interval(
        self,
        work_center_id: int,
        day: date,
        hours: float,
        latest_end_datetime: datetime | None = None,
    ) -> tuple[datetime, datetime] | None:
        duration = self._hours_to_normalized_delta(work_center_id, day, hours)
        work_start, work_end = self.workday_bounds(work_center_id, day)
        cursor_end = (
            min(work_end, latest_end_datetime)
            if latest_end_datetime is not None
            else work_end
        )
        for reservation in sorted(
            self._reservations.get((work_center_id, day), []),
            key=lambda r: r.start_datetime,
            reverse=True,
        ):
            if cursor_end - reservation.end_datetime >= duration:
                return cursor_end - duration, cursor_end
            cursor_end = min(cursor_end, reservation.start_datetime)
        if cursor_end - work_start >= duration:
            return cursor_end - duration, cursor_end
        return None

    def _normalize_to_work_time(self, work_center_id: int, value: datetime) -> datetime:
        work_start, work_end = self.workday_bounds(work_center_id, value.date())
        if value < work_start:
            return work_start
        if value >= work_end:
            next_day = value.date() + timedelta(days=1)
            return self.workday_bounds(work_center_id, next_day)[0]
        return value

    def _can_reserve_contiguous(
        self, work_center_id: int, start_datetime: datetime, hours: float
    ) -> bool:
        remaining = hours
        cursor = self._normalize_to_work_time(work_center_id, start_datetime)
        while remaining > 1e-9:
            work_start, work_end = self.workday_bounds(work_center_id, cursor.date())
            cursor = max(cursor, work_start)
            reservations = sorted(
                self._reservations.get((work_center_id, cursor.date()), []),
                key=lambda r: r.start_datetime,
            )
            next_busy_start = work_end
            for reservation in reservations:
                if reservation.start_datetime < cursor < reservation.end_datetime:
                    return False
                if reservation.start_datetime >= cursor:
                    next_busy_start = min(next_busy_start, reservation.start_datetime)
                    break
            free_hours = self._capacity_between_datetimes(
                work_center_id, cursor, next_busy_start
            )
            if free_hours <= 1e-9:
                return False
            remaining -= free_hours
            if remaining > 1e-9:
                if next_busy_start < work_end:
                    return False
                cursor = self._normalize_to_work_time(
                    work_center_id,
                    datetime.combine(cursor.date() + timedelta(days=1), time.min),
                )
        return True

    def _next_reservation_end_or_next_day(
        self, work_center_id: int, value: datetime
    ) -> datetime:
        cursor = self._normalize_to_work_time(work_center_id, value)
        _, work_end = self.workday_bounds(work_center_id, cursor.date())
        for reservation in sorted(
            self._reservations.get((work_center_id, cursor.date()), []),
            key=lambda r: r.start_datetime,
        ):
            if reservation.end_datetime > cursor:
                return self._normalize_to_work_time(
                    work_center_id, reservation.end_datetime
                )
        return self._normalize_to_work_time(
            work_center_id,
            datetime.combine(cursor.date() + timedelta(days=1), time.min),
        )

    def _hours_to_normalized_delta(
        self, work_center_id: int, day: date, hours: float
    ) -> timedelta:
        capacity = self.available_hours(work_center_id, day)
        if hours <= 0:
            return timedelta(0)
        start, end = self.workday_bounds(work_center_id, day)
        normalized_seconds = (end - start).total_seconds()
        return timedelta(seconds=normalized_seconds * hours / capacity)

    def _capacity_between_datetimes(
        self, work_center_id: int, start: datetime, end: datetime
    ) -> float:
        if end <= start:
            return 0.0
        day_start, day_end = self.workday_bounds(work_center_id, start.date())
        bounded_start = max(start, day_start)
        bounded_end = min(end, day_end)
        if bounded_end <= bounded_start:
            return 0.0
        normalized_seconds = (day_end - day_start).total_seconds()
        used_seconds = (bounded_end - bounded_start).total_seconds()
        return round(
            self.available_hours(work_center_id, start.date())
            * used_seconds
            / normalized_seconds,
            9,
        )

    def _get_work_center(self, work_center_id: int) -> PlanningWorkCenter:
        try:
            work_center = self._work_centers[work_center_id]
        except KeyError as exc:
            raise ValueError(f"Unknown work center: {work_center_id}") from exc
        if work_center.available_hours_per_day <= 0:
            raise ValueError(
                "Work center available hours per day must be greater than 0."
            )
        return work_center
