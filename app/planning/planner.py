"""Pure MVP planning engine."""

from datetime import date, datetime, timedelta

from app.config import MAX_BACKWARD_SEARCH_MONTHS
from app.planning.backward_scheduler import schedule_operation_backward
from app.planning.capacity_calendar import CapacityCalendar
from app.planning.entities import (
    PlannedOrderResult,
    PlanningConflict,
    PlanningOrder,
    PlanningRouteOperation,
    ScheduledOperation,
)
from app.planning.order_preparation import PreparedOrder, prepare_order
from app.planning.time_requirements import calculate_required_hours

DAYS_PER_SEARCH_MONTH = 31


class PlanningEngine:
    """Plan orders against an in-memory capacity calendar."""

    def __init__(
        self,
        capacity_calendar: CapacityCalendar,
        planning_start_date: date | None = None,
    ) -> None:
        self.capacity_calendar = capacity_calendar
        self.planning_start_date = planning_start_date or date.today()

    def plan_order(
        self,
        order: PlanningOrder,
        route_operations: (
            list[PlanningRouteOperation] | tuple[PlanningRouteOperation, ...]
        ),
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
        requirements = prepared_order.requirements

        if not requirements:
            self.capacity_calendar.restore(snapshot)
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
                    reason="Route has no operations.",
                ),
            )

        last_operation = requirements[-1].route_operation
        _, shipment_deadline = self.capacity_calendar.workday_bounds(
            last_operation.work_center_id, order.shipment_date
        )
        previous_operation = (
            requirements[-2].route_operation if len(requirements) > 1 else None
        )
        downstream_demands = [
            (quantity, shipment_deadline)
            for quantity in self._split_quantity(
                order.quantity,
                (
                    previous_operation.min_transfer_quantity_to_next
                    if previous_operation is not None
                    else None
                ),
            )
        ]

        for index in range(len(requirements) - 1, -1, -1):
            requirement = requirements[index]
            operation = requirement.route_operation
            operation_batches: list[ScheduledOperation] = []

            for quantity_part, deadline in reversed(downstream_demands):
                scheduled_or_conflict = schedule_operation_backward(
                    order_id=order.id,
                    shipment_date=order.shipment_date,
                    route_operation_id=operation.id,
                    work_center_id=operation.work_center_id,
                    sequence_number=operation.sequence_number,
                    required_hours=calculate_required_hours(
                        quantity_part, operation.labor_hours_per_1000
                    ),
                    quantity_part=quantity_part,
                    latest_allowed_datetime=deadline,
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
                        operations=tuple(
                            sorted(
                                scheduled_operations,
                                key=lambda scheduled: scheduled.sequence_number,
                            )
                        ),
                        conflict=scheduled_or_conflict,
                    )
                operation_batches.append(scheduled_or_conflict)

            scheduled_operations.extend(operation_batches)
            if index > 0:
                previous_operation = requirements[index - 1].route_operation
                produced_demands = [
                    (
                        batch.days
                        and sum(day.quantity_part or 0 for day in batch.days),
                        min(day.start_datetime for day in batch.days),
                    )
                    for batch in operation_batches
                ]
                produced_demands = [
                    (quantity, deadline)
                    for quantity, deadline in produced_demands
                    if quantity
                ]
                if previous_operation.min_transfer_quantity_to_next is None:
                    downstream_demands = [
                        (
                            sum(quantity for quantity, _ in produced_demands),
                            min(deadline for _, deadline in produced_demands),
                        )
                    ]
                else:
                    downstream_demands = sorted(
                        produced_demands, key=lambda item: item[1]
                    )

        ordered_operations = tuple(
            sorted(
                scheduled_operations,
                key=lambda scheduled: (
                    scheduled.sequence_number,
                    scheduled.planned_start_date,
                ),
            )
        )
        calculated_start_date = min(
            day.start_datetime
            for operation in ordered_operations
            for day in operation.days
        ).date()
        return PlannedOrderResult(
            order_id=order.id,
            calculated_start_date=calculated_start_date,
            operations=ordered_operations,
        )

    def calculate_ideal_start_datetime(
        self, prepared_order: PreparedOrder
    ) -> datetime | None:
        """Return the unconstrained latest start date used as planning priority."""
        snapshot = self.capacity_calendar.snapshot()
        result = self.plan_prepared_order(prepared_order)
        self.capacity_calendar.restore(snapshot)
        if not result.is_success or not result.operations:
            return None
        return min(
            day.start_datetime
            for operation in result.operations
            for day in operation.days
        )

    def _batch_quantities_by_sequence(
        self, prepared_order: PreparedOrder
    ) -> dict[int, list[float]]:
        requirements = prepared_order.requirements
        result: dict[int, list[float]] = {}
        previous_batches: list[float] | None = None
        for requirement in requirements:
            operation = requirement.route_operation
            if operation.min_transfer_quantity_to_next is not None:
                operation_batches = self._split_quantity(
                    prepared_order.order.quantity,
                    operation.min_transfer_quantity_to_next,
                )
            else:
                operation_batches = previous_batches or [prepared_order.order.quantity]
            result[operation.sequence_number] = operation_batches
            previous_batches = self._split_quantity(
                prepared_order.order.quantity, operation.min_transfer_quantity_to_next
            )
        return result

    def _split_quantity(
        self, quantity: float, min_transfer_quantity: float | None
    ) -> list[float]:
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
        technical_limit = shipment_date - timedelta(
            days=MAX_BACKWARD_SEARCH_MONTHS * DAYS_PER_SEARCH_MONTH
        )
        return max(self.planning_start_date, technical_limit)
