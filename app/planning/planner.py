"""Pure MVP planning engine."""

from datetime import date, timedelta

from app.config import MAX_BACKWARD_SEARCH_MONTHS
from app.planning.backward_scheduler import schedule_operation_backward
from app.planning.capacity_calendar import CapacityCalendar
from app.planning.entities import OperationRequirement, PlannedOrderResult, PlanningConflict, PlanningOrder, PlanningRouteOperation, ScheduledOperation
from app.planning.order_preparation import PreparedOrder, prepare_order
from app.planning.partial_transfer import transfer_is_ready_before_next_start

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
        return self.plan_prepared_order(prepared_order)

    def plan_prepared_order(self, prepared_order: PreparedOrder) -> PlannedOrderResult:
        """Plan a prepared order and rollback its reservations if it conflicts."""
        snapshot = self.capacity_calendar.snapshot()
        order = prepared_order.order
        earliest_allowed_date = self._earliest_allowed_date(order.shipment_date)
        scheduled_operations: list[ScheduledOperation] = []

        for requirement in reversed(prepared_order.requirements):
            next_scheduled_operation = scheduled_operations[-1] if scheduled_operations else None
            if next_scheduled_operation is None:
                scheduled_or_conflict = self._schedule_operation(
                    order=order,
                    requirement=requirement,
                    latest_allowed_date=order.shipment_date,
                    earliest_allowed_date=earliest_allowed_date,
                )
            else:
                scheduled_or_conflict = self._schedule_operation_with_transfer(
                    order=order,
                    requirement=requirement,
                    next_scheduled_operation=next_scheduled_operation,
                    earliest_allowed_date=earliest_allowed_date,
                )

            if isinstance(scheduled_or_conflict, PlanningConflict):
                self.capacity_calendar.restore(snapshot)
                return PlannedOrderResult(
                    order_id=order.id,
                    calculated_start_date=None,
                    operations=tuple(sorted(scheduled_operations, key=lambda scheduled: scheduled.sequence_number)),
                    conflict=scheduled_or_conflict,
                )

            scheduled_operations.append(scheduled_or_conflict)

        ordered_operations = tuple(sorted(scheduled_operations, key=lambda scheduled: scheduled.sequence_number))
        calculated_start_date = min(operation.planned_start_date for operation in ordered_operations)
        return PlannedOrderResult(
            order_id=order.id,
            calculated_start_date=calculated_start_date,
            operations=ordered_operations,
        )

    def _schedule_operation(
        self,
        *,
        order: PlanningOrder,
        requirement: OperationRequirement,
        latest_allowed_date: date,
        earliest_allowed_date: date,
    ) -> ScheduledOperation | PlanningConflict:
        operation = requirement.route_operation
        return schedule_operation_backward(
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

    def _schedule_operation_with_transfer(
        self,
        *,
        order: PlanningOrder,
        requirement: OperationRequirement,
        next_scheduled_operation: ScheduledOperation,
        earliest_allowed_date: date,
    ) -> ScheduledOperation | PlanningConflict:
        operation = requirement.route_operation
        latest_allowed_date = next_scheduled_operation.planned_end_date
        last_conflict: PlanningConflict | None = None

        while latest_allowed_date >= earliest_allowed_date:
            attempt_snapshot = self.capacity_calendar.snapshot()
            scheduled_or_conflict = self._schedule_operation(
                order=order,
                requirement=requirement,
                latest_allowed_date=latest_allowed_date,
                earliest_allowed_date=earliest_allowed_date,
            )
            if isinstance(scheduled_or_conflict, PlanningConflict):
                self.capacity_calendar.restore(attempt_snapshot)
                last_conflict = scheduled_or_conflict
                break

            transfer_ready = transfer_is_ready_before_next_start(
                scheduled_operation=scheduled_or_conflict,
                next_operation_start=next_scheduled_operation.planned_start_date,
                order_quantity=order.quantity,
                min_transfer_quantity=operation.min_transfer_quantity_to_next,
                labor_hours_per_1000=operation.labor_hours_per_1000,
            )
            if transfer_ready:
                return scheduled_or_conflict

            self.capacity_calendar.restore(attempt_snapshot)
            latest_allowed_date -= timedelta(days=1)

        return last_conflict or PlanningConflict(
            order_id=order.id,
            shipment_date=order.shipment_date,
            work_center_id=operation.work_center_id,
            required_hours=requirement.required_hours,
            available_hours=0.0,
            deficit_hours=requirement.required_hours,
            blocking_order_ids=(),
            reason="Не удалось накопить передаточную партию до старта следующей операции.",
        )

    def _earliest_allowed_date(self, shipment_date: date) -> date:
        technical_limit = shipment_date - timedelta(days=MAX_BACKWARD_SEARCH_MONTHS * DAYS_PER_SEARCH_MONTH)
        return max(self.planning_start_date, technical_limit)
