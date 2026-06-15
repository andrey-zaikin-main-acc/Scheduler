from datetime import date

from app.constants import ORDER_STATUS_NEW
from app.planning.capacity_calendar import CapacityCalendar
from app.planning.entities import PlanningOrder, PlanningRouteOperation, PlanningWorkCenter
from app.planning.partial_transfer import calculate_transfer_ready_date
from app.planning.planner import PlanningEngine


def test_partial_transfer_allows_previous_operation_to_overlap_next_operation() -> None:
    calendar = CapacityCalendar(
        [
            PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=8),
            PlanningWorkCenter(id=2, name="Высечка", available_hours_per_day=8),
        ]
    )
    engine = PlanningEngine(capacity_calendar=calendar, planning_start_date=date(2026, 7, 1))
    order = PlanningOrder(id=101, quantity=2000, shipment_date=date(2026, 7, 10), status=ORDER_STATUS_NEW)
    route_operations = (
        PlanningRouteOperation(
            id=1,
            sequence_number=1,
            work_center_id=1,
            work_center_name="Печать",
            labor_hours_per_1000=8,
            min_transfer_quantity_to_next=1000,
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
    first_operation, second_operation = result.operations
    assert first_operation.planned_start_date == second_operation.planned_start_date
    assert first_operation.planned_end_date == second_operation.planned_end_date
    ready_date = calculate_transfer_ready_date(
        scheduled_operation=first_operation,
        order_quantity=order.quantity,
        min_transfer_quantity=route_operations[0].min_transfer_quantity_to_next,
        labor_hours_per_1000=route_operations[0].labor_hours_per_1000,
    )
    assert ready_date <= second_operation.planned_start_date


def test_without_transfer_batch_previous_operation_is_scheduled_earlier() -> None:
    calendar = CapacityCalendar(
        [
            PlanningWorkCenter(id=1, name="Печать", available_hours_per_day=8),
            PlanningWorkCenter(id=2, name="Высечка", available_hours_per_day=8),
        ]
    )
    engine = PlanningEngine(capacity_calendar=calendar, planning_start_date=date(2026, 7, 1))
    order = PlanningOrder(id=101, quantity=2000, shipment_date=date(2026, 7, 10), status=ORDER_STATUS_NEW)
    route_operations = (
        PlanningRouteOperation(
            id=1,
            sequence_number=1,
            work_center_id=1,
            work_center_name="Печать",
            labor_hours_per_1000=8,
            min_transfer_quantity_to_next=None,
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
    first_operation, second_operation = result.operations
    assert first_operation.planned_start_date < second_operation.planned_start_date
    assert first_operation.planned_end_date == second_operation.planned_start_date
