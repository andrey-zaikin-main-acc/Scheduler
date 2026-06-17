from datetime import date

from app.constants import ORDER_STATUS_DONE, ORDER_STATUS_NEW
from app.planning.capacity_calendar import CapacityCalendar
from app.planning.entities import PlanningOrder, PlanningRouteOperation, PlanningWorkCenter
from app.planning.planner import PlanningEngine


def test_planning_engine_plans_single_order_backwards() -> None:
    calendar = CapacityCalendar(
        [
            PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=8),
            PlanningWorkCenter(id=2, name="Высечка", available_hours_per_day=8),
        ]
    )
    engine = PlanningEngine(capacity_calendar=calendar, planning_start_date=date(2026, 7, 1))
    order = PlanningOrder(id=101, quantity=1000, shipment_date=date(2026, 7, 10), status=ORDER_STATUS_NEW)
    route_operations = (
        PlanningRouteOperation(id=1, sequence_number=1, work_center_id=1, work_center_name="Печать", labor_hours_per_1000=8),
        PlanningRouteOperation(id=2, sequence_number=2, work_center_id=2, work_center_name="Высечка", labor_hours_per_1000=8),
    )

    result = engine.plan_order(order, route_operations)

    assert result.is_success
    assert result.calculated_start_date == date(2026, 7, 10)
    assert [operation.sequence_number for operation in result.operations] == [1, 2]
    assert result.operations[0].planned_end_date <= result.operations[1].planned_start_date


def test_planning_engine_returns_conflict_for_non_plannable_status() -> None:
    calendar = CapacityCalendar([PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=8)])
    engine = PlanningEngine(capacity_calendar=calendar, planning_start_date=date(2026, 7, 1))
    order = PlanningOrder(id=101, quantity=1000, shipment_date=date(2026, 7, 10), status=ORDER_STATUS_DONE)

    result = engine.plan_order(order, [])

    assert not result.is_success
    assert result.conflict is not None
    assert "not plannable" in result.conflict.reason


def test_planning_engine_returns_conflict_when_capacity_window_is_insufficient() -> None:
    calendar = CapacityCalendar([PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=1)])
    engine = PlanningEngine(capacity_calendar=calendar, planning_start_date=date(2026, 7, 10))
    order = PlanningOrder(id=101, quantity=3000, shipment_date=date(2026, 7, 10), status=ORDER_STATUS_NEW)
    route_operations = (
        PlanningRouteOperation(id=1, sequence_number=1, work_center_id=1, work_center_name="Печать", labor_hours_per_1000=1),
    )

    result = engine.plan_order(order, route_operations)

    assert not result.is_success
    assert result.conflict is not None
    assert result.conflict.deficit_hours == 2
    assert result.conflict.shipment_date == date(2026, 7, 10)
    assert "партии или операции" in result.conflict.reason


def test_planning_engine_uses_min_transfer_quantity_batches_with_final_remainder() -> None:
    calendar = CapacityCalendar(
        [
            PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=8),
            PlanningWorkCenter(id=2, name="Высечка", available_hours_per_day=8),
        ]
    )
    engine = PlanningEngine(capacity_calendar=calendar, planning_start_date=date(2026, 7, 1))
    order = PlanningOrder(id=102, quantity=2500, shipment_date=date(2026, 7, 10), status=ORDER_STATUS_NEW)
    route_operations = (
        PlanningRouteOperation(
            id=1,
            sequence_number=1,
            work_center_id=1,
            work_center_name="Печать",
            labor_hours_per_1000=1,
            min_transfer_quantity_to_next=1000,
        ),
        PlanningRouteOperation(id=2, sequence_number=2, work_center_id=2, work_center_name="Высечка", labor_hours_per_1000=1),
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
