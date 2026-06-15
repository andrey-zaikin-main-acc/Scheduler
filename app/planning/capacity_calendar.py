"""In-memory capacity calendar for pure planning calculations."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from app.planning.entities import PlanningWorkCenter, ScheduledOperationDay


@dataclass(frozen=True)
class CapacityReservation:
    """Reservation metadata stored in the capacity calendar."""

    order_id: int
    work_center_id: int
    date: date
    hours: float


class CapacityCalendar:
    """Track available, occupied and free hours per work center and day."""

    def __init__(self, work_centers: list[PlanningWorkCenter] | tuple[PlanningWorkCenter, ...]) -> None:
        self._work_centers = {work_center.id: work_center for work_center in work_centers}
        self._occupied_hours: dict[tuple[int, date], float] = defaultdict(float)
        self._reservations: dict[tuple[int, date], list[CapacityReservation]] = defaultdict(list)

    def available_hours(self, work_center_id: int) -> float:
        """Return daily available hours for a work center."""
        work_center = self._get_work_center(work_center_id)
        return work_center.available_hours_per_day

    def occupied_hours(self, work_center_id: int, day: date) -> float:
        """Return occupied hours for a work center on a date."""
        return self._occupied_hours[(work_center_id, day)]

    def free_hours(self, work_center_id: int, day: date) -> float:
        """Return free hours for a work center on a date."""
        return max(0.0, self.available_hours(work_center_id) - self.occupied_hours(work_center_id, day))

    def reserve(self, *, order_id: int, work_center_id: int, day: date, hours: float) -> ScheduledOperationDay:
        """Reserve hours for one order and one work center date."""
        if hours <= 0:
            raise ValueError("Reserved hours must be greater than 0.")
        free_hours = self.free_hours(work_center_id, day)
        if hours > free_hours:
            raise ValueError("Reserved hours exceed free capacity.")

        key = (work_center_id, day)
        self._occupied_hours[key] += hours
        self._reservations[key].append(
            CapacityReservation(order_id=order_id, work_center_id=work_center_id, date=day, hours=hours)
        )
        return ScheduledOperationDay(work_center_id=work_center_id, date=day, hours=hours)

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
            reservations = self._reservations.get((work_center_id, current), [])
            order_ids.update(reservation.order_id for reservation in reservations)
            current = current.fromordinal(current.toordinal() + 1)
        return tuple(sorted(order_ids))

    def _get_work_center(self, work_center_id: int) -> PlanningWorkCenter:
        try:
            work_center = self._work_centers[work_center_id]
        except KeyError as exc:
            raise ValueError(f"Unknown work center: {work_center_id}") from exc
        if work_center.available_hours_per_day <= 0:
            raise ValueError("Work center available hours per day must be greater than 0.")
        return work_center
