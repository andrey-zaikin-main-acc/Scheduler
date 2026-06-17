"""Application service that recalculates and persists the production plan."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.constants import ORDER_STATUS_CONFLICT, ORDER_STATUS_PLANNED, PLANNABLE_ORDER_STATUSES
from app.db.models import Order, PlanChange, PlannedOperation, RecalculationRun, utc_now
from app.planning.capacity_calendar import CapacityCalendar
from app.planning.entities import PlannedOrderResult, PlanningConflict, PlanningRouteOperation
from app.planning.order_preparation import PreparedOrder, prepare_order, sort_prepared_orders
from app.planning.planner import PlanningEngine
from app.repositories.conflicts_repository import ConflictsRepository
from app.repositories.orders_repository import OrdersRepository
from app.repositories.plan_repository import PlanRepository
from app.repositories.routes_repository import RoutesRepository
from app.repositories.work_centers_repository import WorkCentersRepository
from app.services.planning_mapper import (
    map_conflict_to_orm,
    map_order_to_planning,
    map_route_operation_to_planning,
    map_scheduled_operation_days_to_orm,
    map_scheduled_operation_to_orm,
    map_work_center_to_planning,
)


@dataclass(frozen=True)
class RecalculationSummary:
    """Summary returned after a plan recalculation."""

    planned_orders: int
    conflicted_orders: int
    planned_operations: int
    conflicts: int
    recalculation_run_id: int


class RecalculationService:
    """Coordinates ORM repositories and the pure planning engine."""

    def __init__(self, session: Session, planning_start_date: date | None = None) -> None:
        self.session = session
        self.planning_start_date = planning_start_date
        self.orders_repository = OrdersRepository(session)
        self.routes_repository = RoutesRepository(session)
        self.work_centers_repository = WorkCentersRepository(session)
        self.plan_repository = PlanRepository(session)
        self.conflicts_repository = ConflictsRepository(session)

    def recalculate_plan(self) -> RecalculationSummary:
        """Rebuild the production plan and persist planned operations and conflicts."""
        run = RecalculationRun(status="running", summary="Пересчёт плана запущен")
        self.session.add(run)
        self.session.flush()

        previous_plan = self._current_plan_snapshot()
        self.plan_repository.clear_plan()
        self.conflicts_repository.clear_conflicts()

        work_centers = [
            map_work_center_to_planning(work_center)
            for work_center in self.work_centers_repository.list_work_centers()
            if work_center.is_active
        ]
        capacity_calendar = CapacityCalendar(work_centers)
        planning_engine = PlanningEngine(capacity_calendar, planning_start_date=self.planning_start_date)

        prepared_orders, invalid_results = self._prepare_orders()
        sorted_orders = sort_prepared_orders(prepared_orders)

        planned_order_count = 0
        conflicted_order_count = 0
        planned_operation_count = 0
        conflict_count = 0

        for invalid_result in invalid_results:
            self._persist_conflict_result(invalid_result)
            conflicted_order_count += 1
            conflict_count += 1

        for prepared_order in sorted_orders:
            result = planning_engine.plan_prepared_order(prepared_order)
            order = self.orders_repository.get_order(prepared_order.order.id)
            if order is None:
                continue

            if result.is_success:
                self._persist_successful_result(result, order)
                planned_order_count += 1
                planned_operation_count += len(result.operations)
            else:
                self._persist_conflict_result(result)
                conflicted_order_count += 1
                conflict_count += 1

        self.session.flush()
        self._persist_plan_changes(run.id, previous_plan, self._current_plan_snapshot())

        run.finished_at = utc_now()
        run.status = "completed"
        run.summary = (
            f"Запланировано заказов: {planned_order_count}; "
            f"конфликтов: {conflicted_order_count}; "
            f"операций: {planned_operation_count}."
        )
        self.session.commit()

        return RecalculationSummary(
            planned_orders=planned_order_count,
            conflicted_orders=conflicted_order_count,
            planned_operations=planned_operation_count,
            conflicts=conflict_count,
            recalculation_run_id=run.id,
        )

    def _prepare_orders(self) -> tuple[list[PreparedOrder], list[PlannedOrderResult]]:
        prepared_orders: list[PreparedOrder] = []
        invalid_results: list[PlannedOrderResult] = []

        for order in self.orders_repository.list_orders():
            if order.status not in PLANNABLE_ORDER_STATUSES:
                continue
            planning_order = map_order_to_planning(order)
            route = self.routes_repository.get_route_with_operations(order.route_id)
            route_operations = tuple(map_route_operation_to_planning(operation) for operation in route.operations) if route else ()
            try:
                prepared_orders.append(prepare_order(planning_order, route_operations))
            except ValueError as exc:
                invalid_results.append(
                    PlannedOrderResult(
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
                )
        return prepared_orders, invalid_results

    def _persist_successful_result(self, result: PlannedOrderResult, order: Order) -> None:
        order.status = ORDER_STATUS_PLANNED
        order.calculated_start_date = result.calculated_start_date
        for scheduled_operation in result.operations:
            planned_operation = map_scheduled_operation_to_orm(scheduled_operation)
            self.plan_repository.add_planned_operation(planned_operation)
            days = map_scheduled_operation_days_to_orm(scheduled_operation, planned_operation.id)
            self.plan_repository.add_planned_operation_days(days)

    def _persist_conflict_result(self, result: PlannedOrderResult) -> None:
        if result.conflict is None:
            return
        order = self.orders_repository.get_order(result.order_id)
        if order is not None:
            order.status = ORDER_STATUS_CONFLICT
            order.calculated_start_date = None
        self.conflicts_repository.add_conflict(map_conflict_to_orm(result.conflict))

    def _current_plan_snapshot(self) -> dict[tuple[int, int], tuple[date, date]]:
        operations = self.session.query(PlannedOperation).all()
        return {
            (operation.order_id, operation.sequence_number): (
                operation.planned_start_date,
                operation.planned_end_date,
            )
            for operation in operations
        }

    def _persist_plan_changes(
        self,
        recalculation_run_id: int,
        previous_plan: dict[tuple[int, int], tuple[date, date]],
        new_plan: dict[tuple[int, int], tuple[date, date]],
    ) -> None:
        all_keys = sorted(set(previous_plan) | set(new_plan))
        for order_id, sequence_number in all_keys:
            old_dates = previous_plan.get((order_id, sequence_number))
            new_dates = new_plan.get((order_id, sequence_number))
            if old_dates == new_dates:
                continue
            if old_dates is None:
                change_type = "created"
                description = f"Операция {sequence_number} заказа {order_id} добавлена в план."
            elif new_dates is None:
                change_type = "removed"
                description = f"Операция {sequence_number} заказа {order_id} удалена из плана."
            else:
                change_type = "rescheduled"
                description = (
                    f"Операция {sequence_number} заказа {order_id} перенесена "
                    f"с {old_dates[0]}–{old_dates[1]} на {new_dates[0]}–{new_dates[1]}."
                )
            self.session.add(
                PlanChange(
                    recalculation_run_id=recalculation_run_id,
                    order_id=order_id,
                    change_type=change_type,
                    old_start_date=old_dates[0] if old_dates else None,
                    old_end_date=old_dates[1] if old_dates else None,
                    new_start_date=new_dates[0] if new_dates else None,
                    new_end_date=new_dates[1] if new_dates else None,
                    description=description,
                )
            )
