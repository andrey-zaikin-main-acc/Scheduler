"""Build plan-change rows by comparing the previous and recalculated plans."""

from datetime import date

from app.db.models import PlanChange, PlannedOperation, PlanningConflict

CHANGE_ORDER_START_CHANGED = "order_start_changed"
CHANGE_OPERATION_MOVED = "operation_moved"
CHANGE_CONFLICT_APPEARED = "conflict_appeared"
CHANGE_CONFLICT_RESOLVED = "conflict_resolved"

OperationKey = tuple[int, int, int]


class PlanDiffService:
    """Compare saved plan snapshots and build `PlanChange` records."""

    def build_changes(
        self,
        *,
        recalculation_run_id: int,
        old_operations: list[PlannedOperation],
        new_operations: list[PlannedOperation],
        old_conflicts: list[PlanningConflict],
        new_conflicts: list[PlanningConflict],
    ) -> list[PlanChange]:
        """Return changes between old and new plan state."""
        changes: list[PlanChange] = []
        changes.extend(self._build_order_start_changes(recalculation_run_id, old_operations, new_operations))
        changes.extend(self._build_operation_changes(recalculation_run_id, old_operations, new_operations))
        changes.extend(self._build_conflict_changes(recalculation_run_id, old_conflicts, new_conflicts))
        return changes

    def _build_order_start_changes(
        self,
        recalculation_run_id: int,
        old_operations: list[PlannedOperation],
        new_operations: list[PlannedOperation],
    ) -> list[PlanChange]:
        old_starts = _order_start_dates(old_operations)
        new_starts = _order_start_dates(new_operations)
        changes: list[PlanChange] = []
        for order_id in sorted(set(old_starts) & set(new_starts)):
            old_start = old_starts[order_id]
            new_start = new_starts[order_id]
            if old_start != new_start:
                changes.append(
                    PlanChange(
                        recalculation_run_id=recalculation_run_id,
                        order_id=order_id,
                        change_type=CHANGE_ORDER_START_CHANGED,
                        old_start_date=old_start,
                        new_start_date=new_start,
                        description=f"Заказ {order_id}: дата запуска изменилась с {old_start} на {new_start}.",
                    )
                )
        return changes

    def _build_operation_changes(
        self,
        recalculation_run_id: int,
        old_operations: list[PlannedOperation],
        new_operations: list[PlannedOperation],
    ) -> list[PlanChange]:
        old_by_key = {_operation_key(operation): operation for operation in old_operations}
        new_by_key = {_operation_key(operation): operation for operation in new_operations}
        changes: list[PlanChange] = []
        for key in sorted(set(old_by_key) & set(new_by_key)):
            old_operation = old_by_key[key]
            new_operation = new_by_key[key]
            if (
                old_operation.planned_start_date != new_operation.planned_start_date
                or old_operation.planned_end_date != new_operation.planned_end_date
            ):
                changes.append(
                    PlanChange(
                        recalculation_run_id=recalculation_run_id,
                        order_id=new_operation.order_id,
                        planned_operation_id=new_operation.id,
                        change_type=CHANGE_OPERATION_MOVED,
                        old_start_date=old_operation.planned_start_date,
                        old_end_date=old_operation.planned_end_date,
                        new_start_date=new_operation.planned_start_date,
                        new_end_date=new_operation.planned_end_date,
                        description=(
                            f"Заказ {new_operation.order_id}: операция {new_operation.sequence_number} "
                            f"сдвинута с {old_operation.planned_start_date}–{old_operation.planned_end_date} "
                            f"на {new_operation.planned_start_date}–{new_operation.planned_end_date}."
                        ),
                    )
                )
        return changes

    def _build_conflict_changes(
        self,
        recalculation_run_id: int,
        old_conflicts: list[PlanningConflict],
        new_conflicts: list[PlanningConflict],
    ) -> list[PlanChange]:
        old_order_ids = {conflict.order_id for conflict in old_conflicts}
        new_order_ids = {conflict.order_id for conflict in new_conflicts}
        changes: list[PlanChange] = []
        for order_id in sorted(new_order_ids - old_order_ids):
            changes.append(
                PlanChange(
                    recalculation_run_id=recalculation_run_id,
                    order_id=order_id,
                    change_type=CHANGE_CONFLICT_APPEARED,
                    description=f"Заказ {order_id}: появился конфликт планирования.",
                )
            )
        for order_id in sorted(old_order_ids - new_order_ids):
            changes.append(
                PlanChange(
                    recalculation_run_id=recalculation_run_id,
                    order_id=order_id,
                    change_type=CHANGE_CONFLICT_RESOLVED,
                    description=f"Заказ {order_id}: конфликт планирования исчез.",
                )
            )
        return changes


def _operation_key(operation: PlannedOperation) -> OperationKey:
    return (operation.order_id, operation.route_operation_id, operation.sequence_number)


def _order_start_dates(operations: list[PlannedOperation]) -> dict[int, date]:
    starts: dict[int, date] = {}
    for operation in operations:
        current = starts.get(operation.order_id)
        if current is None or operation.planned_start_date < current:
            starts[operation.order_id] = operation.planned_start_date
    return starts
