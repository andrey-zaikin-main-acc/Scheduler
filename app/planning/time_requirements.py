"""Time requirement calculations for route operations."""

from app.planning.entities import OperationRequirement, PlanningRouteOperation


def calculate_required_hours(quantity: float, labor_hours_per_1000: float) -> float:
    """Calculate required hours from quantity and labor hours per 1000 pieces."""
    if quantity <= 0:
        raise ValueError("Order quantity must be greater than 0.")
    if labor_hours_per_1000 <= 0:
        raise ValueError("Labor hours per 1000 must be greater than 0.")
    return quantity * labor_hours_per_1000 / 1000


def calculate_operation_requirements(
    quantity: float,
    route_operations: list[PlanningRouteOperation] | tuple[PlanningRouteOperation, ...],
) -> tuple[OperationRequirement, ...]:
    """Calculate hour requirements for every operation in route order."""
    if not route_operations:
        raise ValueError("Route must contain at least one operation.")

    ordered_operations = sorted(route_operations, key=lambda operation: operation.sequence_number)
    return tuple(
        OperationRequirement(
            route_operation=operation,
            required_hours=calculate_required_hours(quantity, operation.labor_hours_per_1000),
        )
        for operation in ordered_operations
    )


def calculate_total_required_hours(requirements: tuple[OperationRequirement, ...]) -> float:
    """Return the total required hours for all operations."""
    return sum(requirement.required_hours for requirement in requirements)


def effective_transfer_quantity(order_quantity: float, min_transfer_quantity: float | None) -> float:
    """Return the effective first transfer batch quantity for MVP partial transfer."""
    if order_quantity <= 0:
        raise ValueError("Order quantity must be greater than 0.")
    if min_transfer_quantity is None:
        return order_quantity
    if min_transfer_quantity <= 0:
        raise ValueError("Minimum transfer quantity must be greater than 0 when provided.")
    return min(order_quantity, min_transfer_quantity)


def calculate_first_transfer_hours(
    *,
    order_quantity: float,
    min_transfer_quantity: float | None,
    labor_hours_per_1000: float,
) -> float:
    """Calculate hours needed to produce the first transferable batch."""
    transfer_quantity = effective_transfer_quantity(order_quantity, min_transfer_quantity)
    return calculate_required_hours(transfer_quantity, labor_hours_per_1000)
