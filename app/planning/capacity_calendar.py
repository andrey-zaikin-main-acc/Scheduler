"""In-memory capacity calendar for pure planning calculations."""

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.planning.entities import PlanningWorkCenter, ScheduledOperationDay

WORKDAY_START = time(hour=9)


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

    def __init__(self, work_centers: list[PlanningWorkCenter] | tuple[PlanningWorkCenter, ...]) -> None:
        self._work_centers = {work_center.id: work_center for work_center in work_centers}
        self._occupied_hours: dict[tuple[int, date], float] = defaultdict(float)
        self._reservations: dict[tuple[int, date], list[CapacityReservation]] = defaultdict(list)

    def available_hours(self, work_center_id: int) -> float:
        """Return daily available hours for a work center."""
        return self._get_work_center(work_center_id).available_hours_per_day

    def workday_bounds(self, work_center_id: int, day: date) -> tuple[datetime, datetime]:
        """Return start and end datetimes of the work center day."""
        start = datetime.combine(day, WORKDAY_START)
        return start, start + timedelta(hours=self.available_hours(work_center_id))

    def occupied_hours(self, work_center_id: int, day: date) -> float:
        """Return occupied hours for a work center on a date."""
        return self._occupied_hours[(work_center_id, day)]

    def free_hours(self, work_center_id: int, day: date) -> float:
        """Return free hours for a work center on a date."""
        return max(0.0, self.available_hours(work_center_id) - self.occupied_hours(work_center_id, day))

    def reserve(self, *, order_id: int, work_center_id: int, day: date, hours: float) -> ScheduledOperationDay:
        """Reserve the latest free non-overlapping interval on one work center date."""
        if hours <= 0:
            raise ValueError("Reserved hours must be greater than 0.")
        interval = self._find_latest_free_interval(work_center_id, day, hours)
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
        )

    def total_free_hours(self, *, work_center_id: int, start_date: date, end_date: date) -> float:
        """Return total free hours in an inclusive date window."""
        if start_date > end_date:
            return 0.0
        total = 0.0
        current = start_date
        while current <= end_date:
            total += self.free_hours(work_center_id, current)
            current = current.fromordinal(current.toordinal() + 1)
        return total

    def blocking_order_ids(self, *, work_center_id: int, start_date: date, end_date: date) -> tuple[int, ...]:
        """Return orders occupying a work center in an inclusive date window."""
        order_ids: set[int] = set()
        current = start_date
        while current <= end_date:
            order_ids.update(r.order_id for r in self._reservations.get((work_center_id, current), []))
            current = current.fromordinal(current.toordinal() + 1)
        return tuple(sorted(order_ids))

    def snapshot(self) -> tuple[dict[tuple[int, date], float], dict[tuple[int, date], list[CapacityReservation]]]:
        """Return a restorable snapshot of occupied hours and reservations."""
        return dict(self._occupied_hours), deepcopy(dict(self._reservations))

    def restore(self, snapshot: tuple[dict[tuple[int, date], float], dict[tuple[int, date], list[CapacityReservation]]]) -> None:
        """Restore occupied hours and reservations from a snapshot."""
        occupied_hours, reservations = snapshot
        self._occupied_hours = defaultdict(float, occupied_hours)
        self._reservations = defaultdict(list, reservations)

    def _find_latest_free_interval(self, work_center_id: int, day: date, hours: float) -> tuple[datetime, datetime] | None:
        duration = timedelta(hours=hours)
        work_start, work_end = self.workday_bounds(work_center_id, day)
        cursor_end = work_end
        for reservation in sorted(self._reservations.get((work_center_id, day), []), key=lambda r: r.start_datetime, reverse=True):
            if cursor_end - reservation.end_datetime >= duration:
                return cursor_end - duration, cursor_end
            cursor_end = min(cursor_end, reservation.start_datetime)
        if cursor_end - work_start >= duration:
            return cursor_end - duration, cursor_end
        return None

    def _get_work_center(self, work_center_id: int) -> PlanningWorkCenter:
        try:
            work_center = self._work_centers[work_center_id]
        except KeyError as exc:
            raise ValueError(f"Unknown work center: {work_center_id}") from exc
        if work_center.available_hours_per_day <= 0:
            raise ValueError("Work center available hours per day must be greater than 0.")
        return work_center
