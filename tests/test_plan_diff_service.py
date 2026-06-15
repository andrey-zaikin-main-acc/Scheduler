from datetime import date

import pytest

pytest.importorskip("sqlalchemy")
from app.db.models import PlannedOperation, PlanningConflict
from app.services.plan_diff_service import (
    CHANGE_CONFLICT_APPEARED,
    CHANGE_CONFLICT_RESOLVED,
    CHANGE_OPERATION_MOVED,
    CHANGE_ORDER_START_CHANGED,
    PlanDiffService,
)


def planned_operation(*, order_id: int, route_operation_id: int, sequence: int, start: date, end: date, op_id: int | None = None):
    return PlannedOperation(
        id=op_id,
        order_id=order_id,
        route_operation_id=route_operation_id,
        work_center_id=1,
        sequence_number=sequence,
        planned_start_date=start,
        planned_end_date=end,
        required_hours=8,
        planned_hours=8,
        status="Запланирован",
    )


def conflict(order_id: int) -> PlanningConflict:
    return PlanningConflict(
        order_id=order_id,
        shipment_date=date(2026, 7, 10),
        required_hours=8,
        available_hours=0,
        deficit_hours=8,
        reason="Недостаточно мощности",
    )


def test_plan_diff_detects_order_start_and_operation_move() -> None:
    old_operations = [
        planned_operation(
            order_id=1,
            route_operation_id=10,
            sequence=1,
            start=date(2026, 7, 8),
            end=date(2026, 7, 8),
        )
    ]
    new_operations = [
        planned_operation(
            order_id=1,
            route_operation_id=10,
            sequence=1,
            start=date(2026, 7, 9),
            end=date(2026, 7, 9),
            op_id=100,
        )
    ]

    changes = PlanDiffService().build_changes(
        recalculation_run_id=5,
        old_operations=old_operations,
        new_operations=new_operations,
        old_conflicts=[],
        new_conflicts=[],
    )

    assert [change.change_type for change in changes] == [
        CHANGE_ORDER_START_CHANGED,
        CHANGE_OPERATION_MOVED,
    ]
    assert changes[1].planned_operation_id == 100
    assert changes[1].old_start_date == date(2026, 7, 8)
    assert changes[1].new_start_date == date(2026, 7, 9)


def test_plan_diff_detects_conflict_appeared_and_resolved() -> None:
    changes = PlanDiffService().build_changes(
        recalculation_run_id=5,
        old_operations=[],
        new_operations=[],
        old_conflicts=[conflict(1)],
        new_conflicts=[conflict(2)],
    )

    assert [change.change_type for change in changes] == [
        CHANGE_CONFLICT_APPEARED,
        CHANGE_CONFLICT_RESOLVED,
    ]
    assert changes[0].order_id == 2
    assert changes[1].order_id == 1
