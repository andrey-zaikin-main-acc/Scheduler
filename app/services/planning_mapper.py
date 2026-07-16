"""Mapping helpers between SQLAlchemy ORM models and pure planning entities."""

from app.constants import ORDER_STATUS_PLANNED
from app.db.models import Order, PlannedOperation, PlannedOperationDay, PlanningConflict as ORMPlanningConflict, RouteOperation, WorkCenter
from app.planning.entities import (
    PlannedOrderResult,
    PlanningConflict,
    PlanningOrder,
    PlanningRouteOperation,
    PlanningWorkCenter,
    ScheduledOperation,
)


def map_order_to_planning(order: Order) -> PlanningOrder:
    """Convert an ORM order to a pure planning order."""
    return PlanningOrder(
        id=order.id,
        quantity=order.quantity,
        shipment_date=order.shipment_date,
        status=order.status,
        planning_mode=order.planning_mode,
        fixed_start_date=order.fixed_start_date,
        child_group_key=order.child_group_key,
        child_sequence_number=order.child_sequence_number,
        is_child_order=order.is_child_order,
        is_linked_child_group=order.is_linked_child_group,
    )


def map_work_center_to_planning(work_center: WorkCenter) -> PlanningWorkCenter:
    """Convert an ORM work center to a pure planning work center."""
    return PlanningWorkCenter(
        id=work_center.id,
        name=work_center.name,
        available_hours_per_day=work_center.available_hours_per_day,
        workday_start_time=work_center.workday_start_time,
        prevent_order_interruption=work_center.prevent_order_interruption,
    )


def map_route_operation_to_planning(route_operation: RouteOperation) -> PlanningRouteOperation:
    """Convert an ORM route operation to a pure planning route operation."""
    return PlanningRouteOperation(
        id=route_operation.id,
        sequence_number=route_operation.sequence_number,
        work_center_id=route_operation.work_center_id,
        work_center_name=route_operation.work_center.name,
        labor_hours_per_1000=route_operation.labor_hours_per_1000,
        min_transfer_quantity_to_next=route_operation.min_transfer_quantity_to_next,
    )


def map_scheduled_operation_to_orm(scheduled_operation: ScheduledOperation) -> PlannedOperation:
    """Convert a scheduled pure operation to an ORM planned operation aggregate."""
    return PlannedOperation(
        order_id=scheduled_operation.order_id,
        route_operation_id=scheduled_operation.route_operation_id,
        work_center_id=scheduled_operation.work_center_id,
        sequence_number=scheduled_operation.sequence_number,
        planned_start_date=scheduled_operation.planned_start_date,
        planned_end_date=scheduled_operation.planned_end_date,
        required_hours=scheduled_operation.required_hours,
        planned_hours=scheduled_operation.planned_hours,
        status=ORDER_STATUS_PLANNED,
    )


def map_scheduled_operation_days_to_orm(
    scheduled_operation: ScheduledOperation,
    planned_operation_id: int,
) -> list[PlannedOperationDay]:
    """Convert daily placements for a scheduled operation to ORM rows."""
    return [
        PlannedOperationDay(
            planned_operation_id=planned_operation_id,
            work_center_id=day.work_center_id,
            date=day.date,
            hours=day.hours,
            start_datetime=day.start_datetime,
            end_datetime=day.end_datetime,
            quantity_part=day.quantity_part,
        )
        for day in scheduled_operation.days
    ]


def map_conflict_to_orm(conflict: PlanningConflict) -> ORMPlanningConflict:
    """Convert a pure planning conflict to an ORM planning conflict."""
    blocking_order_ids = ",".join(str(order_id) for order_id in conflict.blocking_order_ids) or None
    return ORMPlanningConflict(
        order_id=conflict.order_id,
        shipment_date=conflict.shipment_date,
        work_center_id=conflict.work_center_id,
        required_hours=conflict.required_hours,
        available_hours=conflict.available_hours,
        deficit_hours=conflict.deficit_hours,
        blocking_order_ids=blocking_order_ids,
        reason=conflict.reason,
    )


def successful_operation_count(result: PlannedOrderResult) -> int:
    """Return the number of scheduled operations in a planning result."""
    return len(result.operations) if result.is_success else 0
