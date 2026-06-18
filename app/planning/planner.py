"""Pure MVP planning engine."""

from dataclasses import replace
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
    ScheduledOperationDay,
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
            return self._invalid_order_result(order, str(exc))
        return self.plan_prepared_order(prepared_order)

    def plan_prepared_order(self, prepared_order: PreparedOrder) -> PlannedOrderResult:
        """Plan a prepared order backwards from its fixed shipment date."""
        snapshot = self.capacity_calendar.snapshot()
        order = prepared_order.order
        requirements = prepared_order.requirements
        if not requirements:
            self.capacity_calendar.restore(snapshot)
            return self._invalid_order_result(order, "Route has no operations.")

        earliest_allowed_date = self._earliest_allowed_date(order.shipment_date)
        latest_deadline = self._shipment_deadline(
            requirements[-1].route_operation, order.shipment_date
        )
        scheduled_reversed: list[ScheduledOperation] = []

        for requirement in reversed(requirements):
            operation = requirement.route_operation
            scheduled_or_conflict = schedule_operation_backward(
                order_id=order.id,
                shipment_date=order.shipment_date,
                route_operation_id=operation.id,
                work_center_id=operation.work_center_id,
                sequence_number=operation.sequence_number,
                required_hours=requirement.required_hours,
                quantity_part=order.quantity,
                latest_allowed_datetime=latest_deadline,
                earliest_allowed_date=earliest_allowed_date,
                capacity_calendar=self.capacity_calendar,
            )
            if isinstance(scheduled_or_conflict, PlanningConflict):
                self.capacity_calendar.restore(snapshot)
                return PlannedOrderResult(
                    order_id=order.id,
                    calculated_start_date=None,
                    operations=tuple(
                        sorted(scheduled_reversed, key=lambda op: op.sequence_number)
                    ),
                    conflict=replace(
                        scheduled_or_conflict,
                        reason="Недостаточно мощности для размещения партии или операции в допустимом окне без переноса отгрузки.",
                    ),
                )
            scheduled_reversed.append(scheduled_or_conflict)
            latest_deadline = min(
                day.start_datetime for day in scheduled_or_conflict.days
            )

        split_operations: list[ScheduledOperation] = []
        for operation in sorted(scheduled_reversed, key=lambda op: op.sequence_number):
            split_operations.extend(
                self._split_scheduled_operation(prepared_order, operation)
            )
        scheduled_operations = tuple(split_operations)
        calculated_start_date = min(
            day.start_datetime
            for operation in scheduled_operations
            for day in operation.days
        ).date()
        return PlannedOrderResult(
            order_id=order.id,
            calculated_start_date=calculated_start_date,
            operations=scheduled_operations,
        )

    def _shipment_deadline(
        self, operation: PlanningRouteOperation, shipment_date: date
    ) -> datetime:
        _, shipment_deadline = self.capacity_calendar.workday_bounds(
            operation.work_center_id, shipment_date
        )
        return shipment_deadline

    def _split_scheduled_operation(
        self, prepared_order: PreparedOrder, scheduled_operation: ScheduledOperation
    ) -> list[ScheduledOperation]:
        """Split a placed operation into transfer-batch scheduled operations."""
        batch_quantities = self._batch_quantities_for_sequence(
            prepared_order, scheduled_operation.sequence_number
        )
        split_day_groups = self._split_days_by_quantities(
            scheduled_operation.days, batch_quantities, prepared_order.order.quantity
        )
        result: list[ScheduledOperation] = []
        for days in split_day_groups:
            if not days:
                continue
            result.append(
                replace(
                    scheduled_operation,
                    required_hours=sum(day.hours for day in days),
                    planned_hours=sum(day.hours for day in days),
                    planned_start_date=min(day.date for day in days),
                    planned_end_date=max(day.date for day in days),
                    days=tuple(days),
                )
            )
        return result

    def _batch_quantities_for_sequence(
        self, prepared_order: PreparedOrder, sequence_number: int
    ) -> list[float]:
        requirements = list(prepared_order.requirements)
        index = next(
            i
            for i, req in enumerate(requirements)
            if req.route_operation.sequence_number == sequence_number
        )
        operation = requirements[index].route_operation
        source_transfer_quantity = operation.min_transfer_quantity_to_next
        if source_transfer_quantity is None and index > 0:
            source_transfer_quantity = requirements[
                index - 1
            ].route_operation.min_transfer_quantity_to_next
        return self._split_quantity(
            prepared_order.order.quantity, source_transfer_quantity
        )

    def _split_days_by_quantities(
        self,
        days: tuple[ScheduledOperationDay, ...],
        quantities: list[float],
        total_quantity: float,
    ) -> list[list[ScheduledOperationDay]]:
        if not days:
            return []
        ordered_days = sorted(days, key=lambda day: day.start_datetime)
        total_seconds = sum(
            (day.end_datetime - day.start_datetime).total_seconds()
            for day in ordered_days
        )
        if total_seconds <= 0:
            return [list(ordered_days)]
        seconds_per_unit = total_seconds / total_quantity
        groups: list[list[ScheduledOperationDay]] = []
        day_index = 0
        cursor = ordered_days[0].start_datetime
        current_day = ordered_days[0]
        for quantity in quantities:
            remaining_seconds = quantity * seconds_per_unit
            group: list[ScheduledOperationDay] = []
            while remaining_seconds > 1e-6:
                available_seconds = (current_day.end_datetime - cursor).total_seconds()
                used_seconds = min(remaining_seconds, available_seconds)
                part_end = cursor + timedelta(seconds=used_seconds)
                group.append(
                    replace(
                        current_day,
                        date=cursor.date(),
                        hours=used_seconds / 3600,
                        start_datetime=cursor,
                        end_datetime=part_end,
                        quantity_part=quantity
                        * used_seconds
                        / (quantity * seconds_per_unit),
                    )
                )
                remaining_seconds -= used_seconds
                cursor = part_end
                if remaining_seconds > 1e-6:
                    day_index += 1
                    current_day = ordered_days[day_index]
                    cursor = current_day.start_datetime
            delta = quantity - sum(day.quantity_part or 0 for day in group)
            if abs(delta) > 1e-6 and group:
                group[-1] = replace(
                    group[-1], quantity_part=(group[-1].quantity_part or 0) + delta
                )
            groups.append(group)
        return groups

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

    def _invalid_order_result(
        self, order: PlanningOrder, reason: str
    ) -> PlannedOrderResult:
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
                reason=reason,
            ),
        )

    def _earliest_allowed_date(self, shipment_date: date) -> date:
        technical_limit = shipment_date - timedelta(
            days=MAX_BACKWARD_SEARCH_MONTHS * DAYS_PER_SEARCH_MONTH
        )
        return max(self.planning_start_date, technical_limit)
