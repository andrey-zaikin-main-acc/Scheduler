"""Order preparation and basic processing order for planning."""

from dataclasses import dataclass

from app.constants import PLANNABLE_ORDER_STATUSES
from app.planning.entities import (
    OperationRequirement,
    PlanningOrder,
    PlanningRouteOperation,
)
from app.planning.time_requirements import (
    calculate_operation_requirements,
    calculate_total_required_hours,
)


@dataclass(frozen=True)
class PreparedOrder:
    """Order with calculated route requirements."""

    order: PlanningOrder
    requirements: tuple[OperationRequirement, ...]
    total_required_hours: float


def prepare_order(
    order: PlanningOrder,
    route_operations: list[PlanningRouteOperation] | tuple[PlanningRouteOperation, ...],
) -> PreparedOrder:
    """Validate and calculate requirements for one order."""
    if order.status not in PLANNABLE_ORDER_STATUSES:
        raise ValueError(f"Order status is not plannable: {order.status}")
    requirements = calculate_operation_requirements(order.quantity, route_operations)
    total_required_hours = calculate_total_required_hours(requirements)
    return PreparedOrder(
        order=order,
        requirements=requirements,
        total_required_hours=total_required_hours,
    )


def sort_prepared_orders(
    prepared_orders: list[PreparedOrder] | tuple[PreparedOrder, ...],
) -> tuple[PreparedOrder, ...]:
    """Sort orders exclusively by user priority (ID only breaks corrupt ties)."""
    return tuple(
        sorted(
            prepared_orders,
            key=lambda prepared_order: (
                prepared_order.order.priority,
                prepared_order.order.id,
            ),
        )
    )
