"""Pure MVP planning engine."""

from datetime import date, timedelta

from app.config import MAX_BACKWARD_SEARCH_MONTHS
from app.planning.backward_scheduler import schedule_operation_backward
from app.planning.capacity_calendar import CapacityCalendar
from app.planning.entities import PlannedOrderResult, PlanningConflict, PlanningOrder, PlanningRouteOperation, ScheduledOperation
from app.planning.order_preparation import PreparedOrder, prepare_order

DAYS_PER_SEARCH_MONTH = 31


class PlanningEngine:
    """Plan orders against an in-memory capacity calendar."""

    def __init__(self, capacity_calendar: CapacityCalendar, planning_start_date: date | None = None) -> None:
        self.capacity_calendar = capacity_calendar
        self.planning_start_date = planning_start_date or date.today()

    def plan_order(
        self,
        order: PlanningOrder,
        route_operations: list[PlanningRouteOperation] | tuple[PlanningRouteOperation, ...],
    ) -> PlannedOrderResult:
        """Plan one order from shipment date backwards."""
        try:
            prepared_order = prepare_order(order, route_operations)
        except ValueError as exc:
            return PlannedOrderResult(
                order_id=order.id,
                calculated_start_date=None,
                conflict=PlanningConflict(
                    order_id=order.id,
                    shipment_date=order.shipment_date,
                    work_center_id=None,
                    required_hours=0.0,
                    available_hours=0.0,
                    deficit_hours=0.0,
                    blocking_order_ids=(),
                    reason=str(exc),
                ),
            )
        return self._plan_prepared_order(prepared_order)

    def _plan_prepared_order(self, prepared_order: PreparedOrder) -> PlannedOrderResult:
        order = prepared_order.order
        earliest_allowed_date = self._earliest_allowed_date(order.shipment_date)
        latest_allowed_date = order.shipment_date
        scheduled_operations: list[ScheduledOperation] = []

        for requirement in reversed(prepared_order.requirements):
            operation = requirement.route_operation
            scheduled_or_conflict = schedule_operation_backward(
                order_id=order.id,
                shipment_date=order.shipment_date,
                route_operation_id=operation.id,
                work_center_id=operation.work_center_id,
                sequence_number=operation.sequence_number,
                required_hours=requirement.required_hours,
                latest_allowed_date=latest_allowed_date,
                earliest_allowed_date=earliest_allowed_date,
                capacity_calendar=self.capacity_calendar,
            )
            if isinstance(scheduled_or_conflict, PlanningConflict):
                return PlannedOrderResult(
                    order_id=order.id,
                    calculated_start_date=None,
                    operations=tuple(sorted(scheduled_operations, key=lambda scheduled: scheduled.sequence_number)),
                    conflict=scheduled_or_conflict,
                )

            scheduled_operations.append(scheduled_or_conflict)
            latest_allowed_date = scheduled_or_conflict.planned_start_date

        ordered_operations = tuple(sorted(scheduled_operations, key=lambda scheduled: scheduled.sequence_number))
        calculated_start_date = min(operation.planned_start_date for operation in ordered_operations)
        return PlannedOrderResult(
            order_id=order.id,
            calculated_start_date=calculated_start_date,
            operations=ordered_operations,
        )

    def _earliest_allowed_date(self, shipment_date: date) -> date:
        technical_limit = shipment_date - timedelta(days=MAX_BACKWARD_SEARCH_MONTHS * DAYS_PER_SEARCH_MONTH)
        return max(self.planning_start_date, technical_limit)
