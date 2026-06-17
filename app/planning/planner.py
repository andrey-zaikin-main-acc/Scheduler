"""Pure MVP planning engine."""

from datetime import date, datetime, timedelta

from app.config import MAX_BACKWARD_SEARCH_MONTHS
from app.planning.backward_scheduler import schedule_operation_backward
from app.planning.capacity_calendar import CapacityCalendar
from app.planning.entities import PlannedOrderResult, PlanningConflict, PlanningOrder, PlanningRouteOperation, ScheduledOperation
from app.planning.order_preparation import PreparedOrder, prepare_order
from app.planning.time_requirements import calculate_required_hours

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
        latest_allowed_date = order.shipment_date
        scheduled_operations: list[ScheduledOperation] = []

        batch_quantities_by_sequence = self._batch_quantities_by_sequence(prepared_order)
        next_operation_start_dates: dict[int, list[date]] = {}

        for index, requirement in reversed(list(enumerate(prepared_order.requirements))):
            operation = requirement.route_operation
            operation_batches: list[ScheduledOperation] = []
            successor_sequence = (
                prepared_order.requirements[index + 1].route_operation.sequence_number
                if index + 1 < len(prepared_order.requirements)
                else None
            )
            batch_latest_dates = next_operation_start_dates.get(successor_sequence) if successor_sequence is not None else None
            for batch_index, quantity_part in reversed(list(enumerate(batch_quantities_by_sequence[operation.sequence_number]))):
                batch_latest_allowed_date = latest_allowed_date
                if batch_latest_dates is not None and batch_index < len(batch_latest_dates):
                    batch_latest_allowed_date = min(batch_latest_allowed_date, batch_latest_dates[batch_index])
                scheduled_or_conflict = schedule_operation_backward(
                    order_id=order.id,
                    shipment_date=order.shipment_date,
                    route_operation_id=operation.id,
                    work_center_id=operation.work_center_id,
                    sequence_number=operation.sequence_number,
                    required_hours=calculate_required_hours(quantity_part, operation.labor_hours_per_1000),
                    quantity_part=quantity_part,
                    latest_allowed_date=batch_latest_allowed_date,
                    earliest_allowed_date=earliest_allowed_date,
                    capacity_calendar=self.capacity_calendar,
                )
                if isinstance(scheduled_or_conflict, PlanningConflict):
                    self.capacity_calendar.restore(snapshot)
                    scheduled_or_conflict = PlanningConflict(
                        order_id=scheduled_or_conflict.order_id,
                        shipment_date=scheduled_or_conflict.shipment_date,
                        work_center_id=scheduled_or_conflict.work_center_id,
                        required_hours=scheduled_or_conflict.required_hours,
                        available_hours=scheduled_or_conflict.available_hours,
                        deficit_hours=scheduled_or_conflict.deficit_hours,
                        blocking_order_ids=scheduled_or_conflict.blocking_order_ids,
                        reason="Недостаточно мощности для размещения партии или операции в допустимом окне.",
                    )
                    return PlannedOrderResult(
                        order_id=order.id,
                        calculated_start_date=None,
                        operations=tuple(sorted(scheduled_operations, key=lambda scheduled: scheduled.sequence_number)),
                        conflict=scheduled_or_conflict,
                    )
                operation_batches.append(scheduled_or_conflict)

            scheduled_operations.extend(operation_batches)
            next_operation_start_dates[operation.sequence_number] = [
                scheduled.planned_start_date for scheduled in sorted(operation_batches, key=lambda scheduled: scheduled.planned_start_date)
            ]
            if index == 0 and operation_batches:
                latest_allowed_date = min(batch.planned_start_date for batch in operation_batches)

        ordered_operations = tuple(sorted(scheduled_operations, key=lambda scheduled: scheduled.sequence_number))
        calculated_start_date = min(operation.planned_start_date for operation in ordered_operations)
        return PlannedOrderResult(
            order_id=order.id,
            calculated_start_date=calculated_start_date,
            operations=ordered_operations,
        )

    def calculate_ideal_start_datetime(self, prepared_order: PreparedOrder) -> datetime | None:
        """Return the unconstrained latest start date used as planning priority."""
        snapshot = self.capacity_calendar.snapshot()
        result = self.plan_prepared_order(prepared_order)
        self.capacity_calendar.restore(snapshot)
        if not result.is_success or not result.operations:
            return None
        return min(day.start_datetime for operation in result.operations for day in operation.days)

    def _batch_quantities_by_sequence(self, prepared_order: PreparedOrder) -> dict[int, list[float]]:
        requirements = prepared_order.requirements
        result: dict[int, list[float]] = {}
        previous_batches: list[float] | None = None
        for requirement in requirements:
            operation = requirement.route_operation
            if operation.min_transfer_quantity_to_next is not None:
                operation_batches = self._split_quantity(prepared_order.order.quantity, operation.min_transfer_quantity_to_next)
            else:
                operation_batches = previous_batches or [prepared_order.order.quantity]
            result[operation.sequence_number] = operation_batches
            previous_batches = self._split_quantity(prepared_order.order.quantity, operation.min_transfer_quantity_to_next)
        return result

    def _split_quantity(self, quantity: float, min_transfer_quantity: float | None) -> list[float]:
        if min_transfer_quantity is None:
            return [quantity]
        batches: list[float] = []
        remaining = quantity
        while remaining > 0:
            quantity_part = min(min_transfer_quantity, remaining)
            batches.append(quantity_part)
            remaining -= quantity_part
        return batches

    def _earliest_allowed_date(self, shipment_date: date) -> date:
        technical_limit = shipment_date - timedelta(days=MAX_BACKWARD_SEARCH_MONTHS * DAYS_PER_SEARCH_MONTH)
        return max(self.planning_start_date, technical_limit)
