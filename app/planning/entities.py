"""Pure planning data structures used by the MVP planning engine."""

from dataclasses import dataclass, field
from datetime import date, datetime, time


@dataclass(frozen=True)
class PlanningOrder:
    """Order data required by the pure planning engine."""

    id: int
    quantity: float
    shipment_date: date
    status: str


@dataclass(frozen=True)
class PlanningWorkCenter:
    """Work center capacity used by the pure planning engine."""

    id: int
    name: str
    available_hours_per_day: float
    workday_start_time: time = time(hour=9)


@dataclass(frozen=True)
class PlanningRouteOperation:
    """Route operation data required by the pure planning engine."""

    id: int
    sequence_number: int
    work_center_id: int
    work_center_name: str
    labor_hours_per_1000: float
    min_transfer_quantity_to_next: float | None = None


@dataclass(frozen=True)
class OperationRequirement:
    """Calculated hour requirement for one operation."""

    route_operation: PlanningRouteOperation
    required_hours: float


@dataclass(frozen=True)
class ScheduledOperationDay:
    """Hours reserved for an operation on one date."""

    work_center_id: int
    date: date
    hours: float
    start_datetime: datetime
    end_datetime: datetime
    quantity_part: float | None = None


@dataclass(frozen=True)
class ScheduledOperation:
    """Scheduled operation with aggregate dates and daily placements."""

    order_id: int
    route_operation_id: int
    work_center_id: int
    sequence_number: int
    required_hours: float
    planned_hours: float
    planned_start_date: date
    planned_end_date: date
    days: tuple[ScheduledOperationDay, ...]


@dataclass(frozen=True)
class PlanningConflict:
    """Pure planning conflict returned when placement is impossible."""

    order_id: int
    shipment_date: date
    work_center_id: int | None
    required_hours: float
    available_hours: float
    deficit_hours: float
    blocking_order_ids: tuple[int, ...]
    reason: str


@dataclass(frozen=True)
class PlannedOrderResult:
    """Planning result for one order."""

    order_id: int
    calculated_start_date: date | None
    operations: tuple[ScheduledOperation, ...] = field(default_factory=tuple)
    conflict: PlanningConflict | None = None

    @property
    def is_success(self) -> bool:
        """Return True when the order was planned without conflicts."""
        return self.conflict is None
