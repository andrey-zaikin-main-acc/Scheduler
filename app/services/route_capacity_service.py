"""Route capacity and shipment slot pre-checks for orders."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import math

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.constants import ORDER_STATUS_NEW
from app.db.models import PlannedOperationDay, Route, RouteOperation, WorkCenter
from app.planning.capacity_calendar import (
    CapacityCalendar,
    CapacityReservation,
    WORKDAY_START,
)
from app.planning.entities import PlanningOrder, PlanningRouteOperation
from app.planning.planner import PlanningEngine
from app.services.planning_mapper import map_work_center_to_planning

SIMULATED_ORDER_ID = -1


@dataclass(frozen=True)
class RouteCapacityDetail:
    """Capacity detail for one route operation."""

    route_operation_id: int
    sequence_number: int
    work_center_id: int
    work_center_name: str
    available_hours: float
    occupied_hours: float
    free_hours: float
    labor_hours_per_1000: float
    available_quantity: float
    warning: str | None = None


@dataclass(frozen=True)
class RouteCapacityResult:
    """Available quantity for a route in a period."""

    route_id: int
    route_name: str
    max_quantity: int
    bottleneck_work_center: str | None
    details: tuple[RouteCapacityDetail, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def can_calculate_slots(self) -> bool:
        """Return True when route data is valid and capacity is positive."""
        return not self.warnings and self.max_quantity > 0


class RouteCapacityService:
    """Calculate route capacity and simulate shipment dates without DB writes."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def calculate_route_capacity(
        self, route_id: int, period_start: date, period_end: date
    ) -> RouteCapacityResult:
        """Return maximum still-available route quantity in an inclusive period."""
        route = self._get_route(route_id)
        if route is None:
            return RouteCapacityResult(
                route_id=route_id,
                route_name="",
                max_quantity=0,
                bottleneck_work_center=None,
                warnings=("Активный маршрут не найден.",),
            )
        if period_start > period_end:
            return RouteCapacityResult(
                route_id=route.id,
                route_name=route.name,
                max_quantity=0,
                bottleneck_work_center=None,
                warnings=("Дата начала периода позже даты окончания.",),
            )

        occupied = self._occupied_hours_by_work_center(period_start, period_end)
        details: list[RouteCapacityDetail] = []
        warnings: list[str] = []
        limits: list[tuple[float, str]] = []
        days = (period_end - period_start).days + 1

        if not route.operations:
            warnings.append("В маршруте нет операций.")

        for operation in route.operations:
            work_center = operation.work_center
            warning = None
            if work_center is None:
                warning = "В операции не указан участок."
            elif not work_center.is_active:
                warning = f"Участок «{work_center.name}» неактивен."
            elif operation.labor_hours_per_1000 <= 0:
                warning = "Норма часов на 1000 должна быть больше 0."

            available_hours = (
                (work_center.available_hours_per_day * days) if work_center else 0.0
            )
            occupied_hours = occupied.get(operation.work_center_id, 0.0)
            free_hours = max(0.0, available_hours - occupied_hours)
            available_quantity = 0.0
            work_center_name = (
                work_center.name if work_center else f"ID {operation.work_center_id}"
            )

            if warning is not None:
                warnings.append(warning)
            else:
                available_quantity = free_hours / operation.labor_hours_per_1000 * 1000
                limits.append((available_quantity, work_center_name))

            details.append(
                RouteCapacityDetail(
                    operation.id,
                    operation.sequence_number,
                    operation.work_center_id,
                    work_center_name,
                    available_hours,
                    occupied_hours,
                    free_hours,
                    operation.labor_hours_per_1000,
                    available_quantity,
                    warning,
                )
            )

        if limits:
            max_quantity, bottleneck = min(limits, key=lambda item: item[0])
        else:
            max_quantity, bottleneck = 0.0, None
        return RouteCapacityResult(
            route.id,
            route.name,
            max_quantity=max(0, math.floor(max_quantity)),
            bottleneck_work_center=bottleneck,
            details=tuple(details),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    def find_available_shipment_slots(
        self, route_id: int, quantity: float, period_start: date, period_end: date
    ) -> list[date]:
        """Return shipment dates where a simulated order fits without persisting changes."""
        capacity = self.calculate_route_capacity(route_id, period_start, period_end)
        if quantity <= 0 or quantity > capacity.max_quantity or capacity.warnings:
            return []
        route = self._get_route(route_id)
        if route is None:
            return []
        slots: list[date] = []
        for shipment_date in _date_range(period_start, period_end):
            calendar = self._build_capacity_calendar(period_start, period_end)
            engine = PlanningEngine(calendar, planning_start_date=period_start)
            result = engine.plan_order(
                PlanningOrder(
                    id=SIMULATED_ORDER_ID,
                    quantity=quantity,
                    shipment_date=shipment_date,
                    status=ORDER_STATUS_NEW,
                ),
                tuple(
                    _map_route_operation(operation) for operation in route.operations
                ),
            )
            if result.is_success:
                slots.append(shipment_date)
        return slots

    def _get_route(self, route_id: int) -> Route | None:
        return self.session.scalar(
            select(Route)
            .where(Route.id == route_id, Route.is_active.is_(True))
            .options(
                selectinload(Route.operations).selectinload(RouteOperation.work_center)
            )
        )

    def _occupied_hours_by_work_center(
        self, start: date, end: date
    ) -> dict[int, float]:
        rows = self.session.execute(
            select(
                PlannedOperationDay.work_center_id,
                func.coalesce(func.sum(PlannedOperationDay.hours), 0.0),
            )
            .where(PlannedOperationDay.date >= start, PlannedOperationDay.date <= end)
            .group_by(PlannedOperationDay.work_center_id)
        ).all()
        return {work_center_id: float(hours) for work_center_id, hours in rows}

    def _build_capacity_calendar(self, start: date, end: date) -> CapacityCalendar:
        work_centers = self.session.scalars(
            select(WorkCenter)
            .where(WorkCenter.is_active.is_(True))
            .order_by(WorkCenter.name)
        ).all()
        calendar = CapacityCalendar(
            [map_work_center_to_planning(work_center) for work_center in work_centers]
        )
        planned_days = self.session.scalars(
            select(PlannedOperationDay)
            .where(PlannedOperationDay.date >= start, PlannedOperationDay.date <= end)
            .order_by(PlannedOperationDay.date, PlannedOperationDay.id)
        ).all()
        fallback_offset: dict[tuple[int, date], float] = defaultdict(float)
        for day in planned_days:
            key = (day.work_center_id, day.date)
            start_dt = day.start_datetime
            end_dt = day.end_datetime
            if start_dt is None or end_dt is None:
                start_dt = datetime.combine(day.date, WORKDAY_START) + timedelta(
                    hours=fallback_offset[key]
                )
                end_dt = start_dt + timedelta(hours=day.hours)
                fallback_offset[key] += day.hours
            calendar._occupied_hours[
                key
            ] += day.hours  # noqa: SLF001 - intentional snapshot seeding for simulation
            calendar._reservations[key].append(
                CapacityReservation(
                    order_id=day.planned_operation.order_id,
                    work_center_id=day.work_center_id,
                    date=day.date,
                    hours=day.hours,
                    start_datetime=start_dt,
                    end_datetime=end_dt,
                )
            )  # noqa: SLF001
            calendar._reservations[key].sort(
                key=lambda item: item.start_datetime
            )  # noqa: SLF001
        return calendar


def _map_route_operation(operation: RouteOperation) -> PlanningRouteOperation:
    return PlanningRouteOperation(
        operation.id,
        operation.sequence_number,
        operation.work_center_id,
        operation.work_center.name,
        operation.labor_hours_per_1000,
        operation.min_transfer_quantity_to_next,
    )


def _date_range(start: date, end: date) -> list[date]:
    if start > end:
        return []
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
