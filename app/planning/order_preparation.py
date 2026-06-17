"""Order preparation and sorting rules for planning."""

from dataclasses import dataclass
from datetime import datetime

from app.constants import PLANNABLE_ORDER_STATUSES
from app.planning.entities import OperationRequirement, PlanningOrder, PlanningRouteOperation
from app.planning.time_requirements import calculate_operation_requirements, calculate_total_required_hours


@dataclass(frozen=True)
class PreparedOrder:
    """Order with calculated route requirements and total labor."""

    order: PlanningOrder
    requirements: tuple[OperationRequirement, ...]
    total_required_hours: float
    ideal_start_datetime: datetime | None = None


def prepare_order(
    order: PlanningOrder,
    route_operations: list[PlanningRouteOperation] | tuple[PlanningRouteOperation, ...],
) -> PreparedOrder:
    """Validate and calculate requirements for one order."""
    if order.status not in PLANNABLE_ORDER_STATUSES:
        raise ValueError(f"Order status is not plannable: {order.status}")
    requirements = calculate_operation_requirements(order.quantity, route_operations)
    total_required_hours = calculate_total_required_hours(requirements)
    return PreparedOrder(order=order, requirements=requirements, total_required_hours=total_required_hours)


def sort_prepared_orders(prepared_orders: list[PreparedOrder] | tuple[PreparedOrder, ...]) -> tuple[PreparedOrder, ...]:
    """Sort orders by ideal start, shipment date, total labor descending, then order ID."""
    return tuple(
        sorted(
            prepared_orders,
            key=lambda prepared_order: (
                prepared_order.ideal_start_datetime or datetime.max,
                prepared_order.order.shipment_date,
                -prepared_order.total_required_hours,
                prepared_order.order.id,
            ),
        )
    )
