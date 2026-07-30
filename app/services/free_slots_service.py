"""Free capacity and route quantity calculations for the MVP."""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import PlannedOperationDay, Route, RouteOperation, WorkCenter
from app.planning.capacity_units import daily_capacity_from_monthly


@dataclass(frozen=True)
class FreeSlotRow:
    """Free hours for one work center on one date."""

    work_center_id: int
    work_center: str
    date: date
    available_hours: float
    occupied_hours: float
    free_hours: float

    def to_dict(self) -> dict[str, object]:
        """Return a UI-friendly row."""
        return {
            "Участок": self.work_center,
            "Дата": self.date,
            "Доступно часов": round(self.available_hours, 2),
            "Занято часов": round(self.occupied_hours, 2),
            "Свободно часов": round(self.free_hours, 2),
        }


@dataclass(frozen=True)
class RouteCapacityRow:
    """Approximate route quantity constrained by its bottleneck operation."""

    route_id: int
    route: str
    possible_quantity: float
    bottleneck_work_center: str | None

    def to_dict(self) -> dict[str, object]:
        """Return a UI-friendly row."""
        return {
            "Маршрут": self.route,
            "Теоретический максимальный тираж": round(self.possible_quantity, 2),
            "Ограничивающий участок": self.bottleneck_work_center,
        }


class FreeSlotsService:
    """Calculate free slots and approximate available route quantities."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_free_slots(
        self, *, start_date: date, end_date: date
    ) -> list[dict[str, object]]:
        """Return free hours by work center and date for an inclusive period."""
        rows = self._free_slot_rows(start_date=start_date, end_date=end_date)
        return [row.to_dict() for row in rows]

    def get_route_capacities(
        self, *, start_date: date, end_date: date
    ) -> list[dict[str, object]]:
        """Return approximate possible quantities by route for an inclusive period."""
        free_hours_by_work_center = self._total_free_hours_by_work_center(
            start_date=start_date, end_date=end_date
        )
        routes = self.session.scalars(
            select(Route)
            .where(Route.is_active.is_(True))
            .options(
                selectinload(Route.operations).selectinload(RouteOperation.work_center)
            )
            .order_by(Route.name)
        ).all()

        rows: list[RouteCapacityRow] = []
        for route in routes:
            operation_limits: list[tuple[float, str]] = []
            for operation in route.operations:
                if operation.labor_hours_per_1000 <= 0:
                    continue
                free_hours = free_hours_by_work_center.get(
                    operation.work_center_id, 0.0
                )
                possible_quantity = free_hours * 1000 / operation.labor_hours_per_1000
                work_center_name = (
                    operation.work_center.name
                    if operation.work_center
                    else str(operation.work_center_id)
                )
                operation_limits.append((possible_quantity, work_center_name))

            if operation_limits:
                possible_quantity, bottleneck = min(
                    operation_limits, key=lambda item: item[0]
                )
            else:
                possible_quantity, bottleneck = 0.0, None
            rows.append(
                RouteCapacityRow(
                    route_id=route.id,
                    route=route.name,
                    possible_quantity=possible_quantity,
                    bottleneck_work_center=bottleneck,
                )
            )
        return [row.to_dict() for row in rows]

    def find_start_slots(self, *, route_id: int, quantity: float, start_date: date, end_date: date) -> list[dict[str, date]]:
        """Return non-persisting candidate start/result-shipment pairs.

        Capacity is checked against the saved plan only.  Completion is allowed
        beyond ``end_date``; only the candidate start is constrained.
        """
        route = self.session.scalar(select(Route).where(Route.id == route_id).options(selectinload(Route.operations).selectinload(RouteOperation.work_center)))
        if not route or not route.is_active or not route.operations or any(not op.is_active or not op.work_center or not op.work_center.is_active for op in route.operations):
            return []
        results = []
        for candidate in _date_range(start_date, end_date):
            finish = candidate
            possible = True
            for operation in route.operations:
                hours = quantity * operation.labor_hours_per_1000 / 1000
                while hours > 1e-9:
                    occupied = self._occupied_hours_by_work_center_and_date(start_date=finish, end_date=finish).get((operation.work_center_id, finish), 0)
                    free = max(0.0, daily_capacity_from_monthly(operation.work_center.available_hours_per_day, finish) - occupied)
                    hours -= free
                    if hours > 1e-9:
                        finish += timedelta(days=1)
                    if (finish - candidate).days > 3660:
                        possible = False; break
                if not possible: break
            if possible:
                results.append({"Заданная дата запуска": candidate, "Расчётная дата отгрузки": finish})
        return results

    def find_shipment_slots(self, *, route_id: int, quantity: float, start_date: date, end_date: date) -> list[dict[str, date]]:
        """Check every requested shipment date by allocating route work backwards."""
        route = self.session.scalar(select(Route).where(Route.id == route_id).options(
            selectinload(Route.operations).selectinload(RouteOperation.work_center)))
        if not route or not route.is_active or not route.operations or any(
            not op.is_active or not op.work_center or not op.work_center.is_active
            for op in route.operations
        ):
            return []
        results: list[dict[str, date]] = []
        for shipment in _date_range(start_date, end_date):
            cursor = shipment
            possible = True
            for operation in reversed(route.operations):
                hours = quantity * operation.labor_hours_per_1000 / 1000
                while hours > 1e-9:
                    occupied = self._occupied_hours_by_work_center_and_date(
                        start_date=cursor, end_date=cursor
                    ).get((operation.work_center_id, cursor), 0)
                    free = max(0.0, daily_capacity_from_monthly(
                        operation.work_center.available_hours_per_day, cursor
                    ) - occupied)
                    hours -= free
                    if hours > 1e-9:
                        cursor -= timedelta(days=1)
                    if (shipment - cursor).days > 3660:
                        possible = False
                        break
                if not possible:
                    break
            if possible:
                results.append({"Расчётная дата запуска": cursor, "Заданная дата отгрузки": shipment})
        return results

    def _free_slot_rows(self, *, start_date: date, end_date: date) -> list[FreeSlotRow]:
        work_centers = self.session.scalars(
            select(WorkCenter)
            .where(WorkCenter.is_active.is_(True))
            .order_by(WorkCenter.name)
        ).all()
        occupied_hours = self._occupied_hours_by_work_center_and_date(
            start_date=start_date, end_date=end_date
        )

        rows: list[FreeSlotRow] = []
        for current_date in _date_range(start_date, end_date):
            for work_center in work_centers:
                occupied = occupied_hours.get((work_center.id, current_date), 0.0)
                available = daily_capacity_from_monthly(
                    work_center.available_hours_per_day, current_date
                )
                rows.append(
                    FreeSlotRow(
                        work_center_id=work_center.id,
                        work_center=work_center.name,
                        date=current_date,
                        available_hours=available,
                        occupied_hours=occupied,
                        free_hours=max(0.0, available - occupied),
                    )
                )
        return rows

    def _total_free_hours_by_work_center(
        self, *, start_date: date, end_date: date
    ) -> dict[int, float]:
        totals: dict[int, float] = {}
        for row in self._free_slot_rows(start_date=start_date, end_date=end_date):
            totals[row.work_center_id] = (
                totals.get(row.work_center_id, 0.0) + row.free_hours
            )
        return totals

    def _occupied_hours_by_work_center_and_date(
        self, *, start_date: date, end_date: date
    ) -> dict[tuple[int, date], float]:
        planned_days = self.session.scalars(
            select(PlannedOperationDay).where(
                PlannedOperationDay.date >= start_date,
                PlannedOperationDay.date <= end_date,
            )
        ).all()
        occupied_hours: dict[tuple[int, date], float] = {}
        for day in planned_days:
            key = (day.work_center_id, day.date)
            occupied_hours[key] = occupied_hours.get(key, 0.0) + day.hours
        return occupied_hours


def _date_range(start_date: date, end_date: date) -> list[date]:
    if start_date > end_date:
        return []
    days = (end_date - start_date).days
    return [start_date + timedelta(days=offset) for offset in range(days + 1)]
