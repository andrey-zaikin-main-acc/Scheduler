"""Pure MVP planning engine."""

from dataclasses import replace
from datetime import date, datetime, timedelta

from app.config import MAX_BACKWARD_SEARCH_MONTHS
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
        """Plan one order as a flow before its shipment deadline."""
        try:
            prepared_order = prepare_order(order, route_operations)
        except ValueError as exc:
            return self._invalid_order_result(order, str(exc))
        return self.plan_prepared_order(prepared_order)

    def plan_prepared_order(self, prepared_order: PreparedOrder) -> PlannedOrderResult:
        """Plan a prepared order as a forward batch flow before shipment deadline."""
        order = prepared_order.order
        if not prepared_order.requirements:
            return self._invalid_order_result(order, "Route has no operations.")

        latest_finish = self._shipment_deadline(
            prepared_order.requirements[-1].route_operation, order.shipment_date
        )
        earliest_start = datetime.combine(
            self._earliest_allowed_date(order.shipment_date), datetime.min.time()
        )
        cursor = latest_finish
        best_result: PlannedOrderResult | None = None
        last_conflict: PlanningConflict | None = None

        while cursor >= earliest_start:
            snapshot = self.capacity_calendar.snapshot()
            try:
                planned_or_conflict = self._try_place_forward_flow(
                    prepared_order, cursor
                )
            except ValueError as exc:
                self.capacity_calendar.restore(snapshot)
                return self._invalid_order_result(order, str(exc))
            if isinstance(planned_or_conflict, PlannedOrderResult):
                finish = max(
                    day.end_datetime
                    for operation in planned_or_conflict.operations
                    for day in operation.days
                )
                if finish <= latest_finish:
                    best_result = planned_or_conflict
                    break
            else:
                last_conflict = planned_or_conflict
            self.capacity_calendar.restore(snapshot)
            cursor -= timedelta(hours=1)

        if best_result is not None:
            return best_result
        if last_conflict is not None:
            return PlannedOrderResult(
                order_id=order.id,
                calculated_start_date=None,
                conflict=replace(
                    last_conflict,
                    reason="Невозможно разместить потоковый заказ до даты отгрузки после попытки оптимизации расписания.",
                ),
            )
        first_requirement = prepared_order.requirements[0]
        available_hours = self.capacity_calendar.total_free_hours(
            work_center_id=first_requirement.route_operation.work_center_id,
            start_date=self._earliest_allowed_date(order.shipment_date),
            end_date=order.shipment_date,
        )
        return PlannedOrderResult(
            order_id=order.id,
            calculated_start_date=None,
            conflict=PlanningConflict(
                order_id=order.id,
                shipment_date=order.shipment_date,
                work_center_id=first_requirement.route_operation.work_center_id,
                required_hours=first_requirement.required_hours,
                available_hours=available_hours,
                deficit_hours=max(
                    0.0, first_requirement.required_hours - available_hours
                ),
                blocking_order_ids=self.capacity_calendar.blocking_order_ids(
                    work_center_id=first_requirement.route_operation.work_center_id,
                    start_date=self._earliest_allowed_date(order.shipment_date),
                    end_date=order.shipment_date,
                ),
                reason="Недостаточно мощности для размещения партии или операции в допустимом окне без переноса отгрузки.",
            ),
        )

    def _try_place_forward_flow(
        self, prepared_order: PreparedOrder, first_operation_not_before: datetime
    ) -> PlannedOrderResult | PlanningConflict:
        order = prepared_order.order
        placed_operations: list[ScheduledOperation] = []
        incoming_ready: list[tuple[float, datetime, bool]] = [
            (order.quantity, first_operation_not_before, True)
        ]

        for index, requirement in enumerate(prepared_order.requirements):
            route_operation = requirement.route_operation
            operation_batches = self._build_operation_input_batches(
                incoming_ready,
                route_operation.min_transfer_quantity_to_next,
                order.quantity,
                first_operation_not_before if index == 0 else None,
            )
            previous_batch_finish: datetime | None = None
            next_incoming_ready: list[tuple[float, datetime, bool]] = []

            for batch_quantity, input_ready, is_last_batch in operation_batches:
                batch_hours = (
                    batch_quantity * route_operation.labor_hours_per_1000 / 1000
                )
                requested_start = input_ready
                if previous_batch_finish is not None:
                    requested_start = max(requested_start, previous_batch_finish)
                start = self.capacity_calendar.find_earliest_contiguous_start(
                    route_operation.work_center_id,
                    requested_start,
                    batch_hours,
                )
                scheduled_days = self.capacity_calendar.reserve_contiguous_forward(
                    order_id=order.id,
                    work_center_id=route_operation.work_center_id,
                    start_datetime=start,
                    hours=batch_hours,
                    quantity_part=batch_quantity,
                )
                scheduled = ScheduledOperation(
                    order_id=order.id,
                    route_operation_id=route_operation.id,
                    work_center_id=route_operation.work_center_id,
                    sequence_number=route_operation.sequence_number,
                    required_hours=batch_hours,
                    planned_hours=sum(day.hours for day in scheduled_days),
                    planned_start_date=min(day.date for day in scheduled_days),
                    planned_end_date=max(day.date for day in scheduled_days),
                    days=tuple(scheduled_days),
                )
                placed_operations.append(scheduled)
                previous_batch_finish = max(day.end_datetime for day in scheduled_days)
                next_incoming_ready.append(
                    (batch_quantity, previous_batch_finish, is_last_batch)
                )

            incoming_ready = next_incoming_ready

        calculated_start_date = min(
            day.start_datetime for operation in placed_operations for day in operation.days
        ).date()
        return PlannedOrderResult(
            order_id=order.id,
            calculated_start_date=calculated_start_date,
            operations=tuple(placed_operations),
        )

    def _operation_output_batches(
        self,
        scheduled_operation: ScheduledOperation,
        min_transfer_quantity: float | None,
        order_quantity: float,
    ) -> list[tuple[float, datetime, bool]]:
        quantities = self._split_quantity(order_quantity, min_transfer_quantity)
        total_seconds = sum(
            (day.end_datetime - day.start_datetime).total_seconds()
            for day in scheduled_operation.days
        )
        seconds_per_unit = total_seconds / order_quantity
        batches: list[tuple[float, datetime, bool]] = []
        elapsed = 0.0
        days = sorted(scheduled_operation.days, key=lambda day: day.start_datetime)
        for batch_index, quantity in enumerate(quantities):
            elapsed += quantity * seconds_per_unit
            ready = self._datetime_after_processing_seconds(days, elapsed)
            batches.append((quantity, ready, batch_index == len(quantities) - 1))
        return batches

    def _build_operation_input_batches(
        self,
        incoming_ready: list[tuple[float, datetime, bool]],
        min_batch_quantity: float | None,
        order_quantity: float,
        first_operation_not_before: datetime | None = None,
    ) -> list[tuple[float, datetime, bool]]:
        """Build physically available input batches for one route operation.

        The batch size is controlled by the current route operation.  Middle
        operations therefore wait until enough product has been transferred by
        the previous operation before starting their own batch.  The final
        batch may be smaller than the minimum batch size.
        """
        if min_batch_quantity is None:
            if first_operation_not_before is None:
                return sorted(incoming_ready, key=lambda item: item[1])
            min_batch_quantity = order_quantity
        if min_batch_quantity <= 0:
            raise ValueError(
                "Minimum transfer quantity must be greater than 0 when provided."
            )

        ordered_inputs = sorted(incoming_ready, key=lambda item: item[1])
        batches: list[tuple[float, datetime, bool]] = []
        buffered_quantity = 0.0
        buffered_ready: datetime | None = first_operation_not_before
        remaining_order_quantity = sum(quantity for quantity, _, _ in ordered_inputs)

        for quantity, ready_datetime, _ in ordered_inputs:
            unallocated_quantity = quantity
            while unallocated_quantity > 1e-9:
                needed_quantity = min_batch_quantity - buffered_quantity
                taken_quantity = min(unallocated_quantity, needed_quantity)
                buffered_quantity += taken_quantity
                unallocated_quantity -= taken_quantity
                remaining_order_quantity -= taken_quantity
                buffered_ready = (
                    ready_datetime
                    if buffered_ready is None
                    else max(buffered_ready, ready_datetime)
                )

                is_full_batch = buffered_quantity >= min_batch_quantity - 1e-9
                is_final_remainder = remaining_order_quantity <= 1e-9
                if is_full_batch or is_final_remainder:
                    batches.append(
                        (
                            buffered_quantity,
                            buffered_ready or ready_datetime,
                            is_final_remainder,
                        )
                    )
                    buffered_quantity = 0.0
                    buffered_ready = first_operation_not_before

        return batches

    def _datetime_after_processing_seconds(
        self, days: list[ScheduledOperationDay], seconds: float
    ) -> datetime:
        remaining = seconds
        for day in days:
            duration = (day.end_datetime - day.start_datetime).total_seconds()
            if remaining <= duration + 1e-6:
                return day.start_datetime + timedelta(seconds=remaining)
            remaining -= duration
        return days[-1].end_datetime

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
