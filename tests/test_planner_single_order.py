from datetime import date

import pytest

from app.constants import ORDER_STATUS_DONE, ORDER_STATUS_NEW
from app.planning.capacity_calendar import CapacityCalendar
from app.planning.entities import (
    PlanningOrder,
    PlanningRouteOperation,
    PlanningWorkCenter,
)
from app.planning.planner import PlanningEngine


def test_planning_engine_plans_single_order_backwards() -> None:
    calendar = CapacityCalendar(
        [
            PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=248),
            PlanningWorkCenter(id=2, name="Высечка", available_hours_per_day=248),
        ]
    )
    engine = PlanningEngine(
        capacity_calendar=calendar, planning_start_date=date(2026, 7, 1)
    )
    order = PlanningOrder(
        id=101, quantity=1000, shipment_date=date(2026, 7, 10), status=ORDER_STATUS_NEW
    )
    route_operations = (
        PlanningRouteOperation(
            id=1,
            sequence_number=1,
            work_center_id=1,
            work_center_name="Печать",
            labor_hours_per_1000=8,
        ),
        PlanningRouteOperation(
            id=2,
            sequence_number=2,
            work_center_id=2,
            work_center_name="Высечка",
            labor_hours_per_1000=8,
        ),
    )

    result = engine.plan_order(order, route_operations)

    assert result.is_success
    assert result.calculated_start_date == date(2026, 7, 9)
    assert [operation.sequence_number for operation in result.operations] == [1, 2]
    assert max(day.end_datetime for day in result.operations[0].days) <= min(
        day.start_datetime for day in result.operations[1].days
    )


def test_planning_engine_returns_conflict_for_non_plannable_status() -> None:
    calendar = CapacityCalendar(
        [PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=248)]
    )
    engine = PlanningEngine(
        capacity_calendar=calendar, planning_start_date=date(2026, 7, 1)
    )
    order = PlanningOrder(
        id=101, quantity=1000, shipment_date=date(2026, 7, 10), status=ORDER_STATUS_DONE
    )

    result = engine.plan_order(order, [])

    assert not result.is_success
    assert result.conflict is not None
    assert "not plannable" in result.conflict.reason


def test_planning_engine_returns_conflict_when_capacity_window_is_insufficient() -> (
    None
):
    calendar = CapacityCalendar(
        [PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=1)]
    )
    engine = PlanningEngine(
        capacity_calendar=calendar, planning_start_date=date(2026, 7, 10)
    )
    order = PlanningOrder(
        id=101, quantity=3000, shipment_date=date(2026, 7, 10), status=ORDER_STATUS_NEW
    )
    route_operations = (
        PlanningRouteOperation(
            id=1,
            sequence_number=1,
            work_center_id=1,
            work_center_name="Печать",
            labor_hours_per_1000=1,
        ),
    )

    result = engine.plan_order(order, route_operations)

    assert not result.is_success
    assert result.conflict is not None
    assert result.conflict.deficit_hours == pytest.approx(3 - 1 / 31)
    assert result.conflict.shipment_date == date(2026, 7, 10)
    assert "партии или операции" in result.conflict.reason


def test_planning_engine_uses_min_transfer_quantity_batches_with_final_remainder() -> (
    None
):
    calendar = CapacityCalendar(
        [
            PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=248),
            PlanningWorkCenter(id=2, name="Высечка", available_hours_per_day=248),
        ]
    )
    engine = PlanningEngine(
        capacity_calendar=calendar, planning_start_date=date(2026, 7, 1)
    )
    order = PlanningOrder(
        id=102, quantity=2500, shipment_date=date(2026, 7, 10), status=ORDER_STATUS_NEW
    )
    route_operations = (
        PlanningRouteOperation(
            id=1,
            sequence_number=1,
            work_center_id=1,
            work_center_name="Печать",
            labor_hours_per_1000=1,
            min_transfer_quantity_to_next=1000,
        ),
        PlanningRouteOperation(
            id=2,
            sequence_number=2,
            work_center_id=2,
            work_center_name="Высечка",
            labor_hours_per_1000=1,
        ),
    )

    result = engine.plan_order(order, route_operations)

    assert result.is_success
    operation_quantities = {
        sequence: sorted(
            sum(day.quantity_part or 0 for day in operation.days)
            for operation in result.operations
            if operation.sequence_number == sequence
        )
        for sequence in (1, 2)
    }
    assert operation_quantities[1] == [500, 1000, 1000]
    assert operation_quantities[2] == [500, 1000, 1000]


def test_single_order_is_compacted_to_shipment_datetime_without_capacity_competition() -> (
    None
):
    calendar = CapacityCalendar(
        [
            PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=248),
            PlanningWorkCenter(id=2, name="Высечка", available_hours_per_day=248),
        ]
    )
    engine = PlanningEngine(
        capacity_calendar=calendar, planning_start_date=date(2026, 7, 1)
    )
    order = PlanningOrder(
        id=201, quantity=1000, shipment_date=date(2026, 7, 10), status=ORDER_STATUS_NEW
    )
    route_operations = (
        PlanningRouteOperation(
            id=1,
            sequence_number=1,
            work_center_id=1,
            work_center_name="Печать",
            labor_hours_per_1000=1,
        ),
        PlanningRouteOperation(
            id=2,
            sequence_number=2,
            work_center_id=2,
            work_center_name="Высечка",
            labor_hours_per_1000=1,
        ),
    )

    result = engine.plan_order(order, route_operations)

    assert result.is_success
    assert result.calculated_start_date == date(2026, 7, 10)
    assert (
        min(
            day.start_datetime
            for operation in result.operations
            for day in operation.days
        ).date()
        == order.shipment_date
    )
    assert (
        max(
            day.end_datetime
            for operation in result.operations
            for day in operation.days
        ).date()
        == order.shipment_date
    )


def test_previous_operation_finishes_before_exact_dependent_batch_start_datetime() -> (
    None
):
    calendar = CapacityCalendar(
        [
            PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=248),
            PlanningWorkCenter(id=2, name="Высечка", available_hours_per_day=248),
        ]
    )
    engine = PlanningEngine(
        capacity_calendar=calendar, planning_start_date=date(2026, 7, 1)
    )
    order = PlanningOrder(
        id=202, quantity=2500, shipment_date=date(2026, 7, 10), status=ORDER_STATUS_NEW
    )
    route_operations = (
        PlanningRouteOperation(
            id=1,
            sequence_number=1,
            work_center_id=1,
            work_center_name="Печать",
            labor_hours_per_1000=1,
            min_transfer_quantity_to_next=1000,
        ),
        PlanningRouteOperation(
            id=2,
            sequence_number=2,
            work_center_id=2,
            work_center_name="Высечка",
            labor_hours_per_1000=1,
        ),
    )

    result = engine.plan_order(order, route_operations)

    assert result.is_success
    previous_batches = sorted(
        (
            sum(day.quantity_part or 0 for day in op.days),
            max(day.end_datetime for day in op.days),
        )
        for op in result.operations
        if op.sequence_number == 1
    )
    next_batches = sorted(
        (
            sum(day.quantity_part or 0 for day in op.days),
            min(day.start_datetime for day in op.days),
        )
        for op in result.operations
        if op.sequence_number == 2
    )
    assert [quantity for quantity, _ in previous_batches] == [500, 1000, 1000]
    assert [quantity for quantity, _ in next_batches] == [500, 1000, 1000]
    assert all(
        prev_end <= next_start
        for (_, prev_end), (_, next_start) in zip(previous_batches, next_batches)
    )


def test_middle_operation_waits_for_its_own_minimum_batch_quantity() -> None:
    calendar = CapacityCalendar(
        [
            PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=248),
            PlanningWorkCenter(id=2, name="Высечка", available_hours_per_day=248),
        ]
    )
    engine = PlanningEngine(
        capacity_calendar=calendar, planning_start_date=date(2026, 7, 1)
    )
    order = PlanningOrder(
        id=205, quantity=2500, shipment_date=date(2026, 7, 10), status=ORDER_STATUS_NEW
    )
    route_operations = (
        PlanningRouteOperation(
            id=1,
            sequence_number=1,
            work_center_id=1,
            work_center_name="Печать",
            labor_hours_per_1000=1,
            min_transfer_quantity_to_next=500,
        ),
        PlanningRouteOperation(
            id=2,
            sequence_number=2,
            work_center_id=2,
            work_center_name="Высечка",
            labor_hours_per_1000=1,
            min_transfer_quantity_to_next=1000,
        ),
    )

    result = engine.plan_order(order, route_operations)

    assert result.is_success
    first_operation_batches = sorted(
        (
            sum(day.quantity_part or 0 for day in operation.days),
            max(day.end_datetime for day in operation.days),
        )
        for operation in result.operations
        if operation.sequence_number == 1
    )
    second_operation_batches = sorted(
        (
            sum(day.quantity_part or 0 for day in operation.days),
            min(day.start_datetime for day in operation.days),
        )
        for operation in result.operations
        if operation.sequence_number == 2
    )

    assert [quantity for quantity, _ in first_operation_batches] == [
        500,
        500,
        500,
        500,
        500,
    ]
    assert [quantity for quantity, _ in second_operation_batches] == [500, 1000, 1000]
    assert first_operation_batches[1][1] <= second_operation_batches[1][1]


def test_conflict_does_not_move_shipment_date_when_capacity_is_insufficient() -> None:
    calendar = CapacityCalendar(
        [PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=1)]
    )
    engine = PlanningEngine(
        capacity_calendar=calendar, planning_start_date=date(2026, 7, 10)
    )
    order = PlanningOrder(
        id=203, quantity=3000, shipment_date=date(2026, 7, 10), status=ORDER_STATUS_NEW
    )
    route_operations = (
        PlanningRouteOperation(
            id=1,
            sequence_number=1,
            work_center_id=1,
            work_center_name="Печать",
            labor_hours_per_1000=1,
        ),
    )

    result = engine.plan_order(order, route_operations)

    assert not result.is_success
    assert result.conflict is not None
    assert result.conflict.shipment_date == order.shipment_date
    assert result.calculated_start_date is None


def test_single_order_without_ideal_start_sorting_stays_compact() -> None:
    calendar = CapacityCalendar(
        [PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=248)]
    )
    engine = PlanningEngine(
        capacity_calendar=calendar, planning_start_date=date(2026, 7, 1)
    )
    order = PlanningOrder(
        id=204, quantity=1000, shipment_date=date(2026, 7, 10), status=ORDER_STATUS_NEW
    )
    route_operations = (
        PlanningRouteOperation(
            id=1,
            sequence_number=1,
            work_center_id=1,
            work_center_name="Печать",
            labor_hours_per_1000=1,
        ),
    )
    result = engine.plan_order(order, route_operations)

    assert result.is_success
    assert result.calculated_start_date == date(2026, 7, 10)


def test_successfully_planned_order_starts_and_finishes_no_later_than_shipment_date() -> (
    None
):
    calendar = CapacityCalendar(
        [PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=248)]
    )
    engine = PlanningEngine(
        capacity_calendar=calendar, planning_start_date=date(2026, 7, 1)
    )
    order = PlanningOrder(
        id=206, quantity=1000, shipment_date=date(2026, 7, 10), status=ORDER_STATUS_NEW
    )
    route_operations = (
        PlanningRouteOperation(
            id=1,
            sequence_number=1,
            work_center_id=1,
            work_center_name="Печать",
            labor_hours_per_1000=4,
        ),
    )

    result = engine.plan_order(order, route_operations)

    assert result.is_success
    assert result.calculated_start_date is not None
    assert result.calculated_start_date <= order.shipment_date
    assert (
        max(
            day.end_datetime
            for operation in result.operations
            for day in operation.days
        ).date()
        <= order.shipment_date
    )


def test_daily_capacity_larger_than_24_can_still_fit_in_shipment_calendar_date() -> (
    None
):
    calendar = CapacityCalendar(
        [PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=930)]
    )
    engine = PlanningEngine(
        capacity_calendar=calendar, planning_start_date=date(2026, 7, 10)
    )
    order = PlanningOrder(
        id=207, quantity=1000, shipment_date=date(2026, 7, 10), status=ORDER_STATUS_NEW
    )
    route_operations = (
        PlanningRouteOperation(
            id=1,
            sequence_number=1,
            work_center_id=1,
            work_center_name="Печать",
            labor_hours_per_1000=20,
        ),
    )

    result = engine.plan_order(order, route_operations)

    assert result.is_success
    assert result.calculated_start_date == order.shipment_date
    assert (
        max(day.end_datetime for op in result.operations for day in op.days).date()
        == order.shipment_date
    )


def test_high_monthly_capacity_can_finish_partial_day_need_on_shipment_date() -> None:
    calendar = CapacityCalendar(
        [PlanningWorkCenter(id=1, name="Копакинг", available_hours_per_day=7560)]
    )
    engine = PlanningEngine(
        capacity_calendar=calendar, planning_start_date=date(2026, 7, 10)
    )
    order = PlanningOrder(
        id=208, quantity=1000, shipment_date=date(2026, 7, 10), status=ORDER_STATUS_NEW
    )
    route_operations = (
        PlanningRouteOperation(
            id=1,
            sequence_number=1,
            work_center_id=1,
            work_center_name="Копакинг",
            labor_hours_per_1000=120,
        ),
    )

    result = engine.plan_order(order, route_operations)

    assert result.is_success
    assert result.calculated_start_date == order.shipment_date
    assert (
        max(day.end_datetime for op in result.operations for day in op.days).date()
        == order.shipment_date
    )


def test_insufficient_monthly_capacity_before_shipment_date_creates_conflict() -> None:
    calendar = CapacityCalendar(
        [PlanningWorkCenter(id=1, name="Копакинг", available_hours_per_day=31)]
    )
    engine = PlanningEngine(
        capacity_calendar=calendar, planning_start_date=date(2026, 7, 10)
    )
    order = PlanningOrder(
        id=209, quantity=1000, shipment_date=date(2026, 7, 10), status=ORDER_STATUS_NEW
    )
    route_operations = (
        PlanningRouteOperation(
            id=1,
            sequence_number=1,
            work_center_id=1,
            work_center_name="Копакинг",
            labor_hours_per_1000=2,
        ),
    )

    result = engine.plan_order(order, route_operations)

    assert not result.is_success
    assert result.calculated_start_date is None
    assert result.conflict is not None
    assert result.conflict.work_center_id == 1
    assert result.conflict.deficit_hours == pytest.approx(1)
