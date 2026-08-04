"""Application service that recalculates and persists the production plan."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, selectinload

from app.constants import (
    ORDER_STATUS_CANCELLED,
    PLANNING_MODE_START,
    ORDER_STATUS_NEW,
    ORDER_STATUS_PLANNED,
    PLANNABLE_ORDER_STATUSES,
)
from app.db.models import (
    Order,
    PlanChange,
    PlannedOperation,
    PlanningConflict as PlanningConflictModel,
    RecalculationRun,
    Route,
    RouteOperation,
    utc_now,
)
from app.planning.capacity_calendar import CapacityCalendar
from app.planning.entities import PlannedOrderResult, PlanningConflict
from app.planning.order_preparation import (
    PreparedOrder,
    prepare_order,
    sort_prepared_orders,
)
from app.planning.planner import PlanningEngine
from app.repositories.conflicts_repository import ConflictsRepository
from app.repositories.orders_repository import OrdersRepository
from app.repositories.plan_repository import PlanRepository
from app.repositories.routes_repository import RoutesRepository
from app.repositories.work_centers_repository import WorkCentersRepository
from app.services.order_queue_service import build_queue_snapshot, validate_priorities
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

    def __init__(
        self, session: Session, planning_start_date: date | None = None
    ) -> None:
        self.session = session
        self.planning_start_date = planning_start_date
        self.orders_repository = OrdersRepository(session)
        self.routes_repository = RoutesRepository(session)
        self.work_centers_repository = WorkCentersRepository(session)
        self.plan_repository = PlanRepository(session)
        self.conflicts_repository = ConflictsRepository(session)

    def recalculate_plan(self) -> RecalculationSummary:
        """Fully rebuild all non-cancelled results from an immutable queue snapshot."""
        run = RecalculationRun(status="running", summary="Пересчёт плана запущен")
        self.session.add(run); self.session.flush()
        previous_plan = self._current_plan_snapshot()
        planned_ids = {key[0] for key in previous_plan}
        conflict_ids = set(self.session.scalars(select(PlanningConflictModel.order_id)).all())
        orders = list(self.session.scalars(select(Order).order_by(Order.id)).all())
        priority_errors = validate_priorities(orders)
        if priority_errors:
            raise ValueError("\n".join(priority_errors))
        snapshot = build_queue_snapshot(orders, planned_ids, conflict_ids)
        by_id = {order.id: order for order in orders}

        # Old results are replaced inside the caller-owned transaction.
        self.plan_repository.clear_plan()
        self.session.execute(delete(PlanningConflictModel))
        for order in orders:
            if order.status == ORDER_STATUS_CANCELLED:
                order.priority = 0
                order.calculated_start_date = None
                order.calculated_shipment_date = None

        work_centers = [map_work_center_to_planning(item) for item in self.work_centers_repository.list_work_centers() if item.is_active]
        engine = PlanningEngine(CapacityCalendar(work_centers), planning_start_date=self.planning_start_date)
        prepared, invalid = self._prepare_orders({}, set(snapshot.order_ids), set())
        prepared_by_id = {item.order.id: item for item in prepared}
        invalid_by_id = {item.order_id: item for item in invalid}
        planned_count = conflict_count = operation_count = 0
        for final_priority, order_id in enumerate(snapshot.order_ids, 1):
            order = by_id[order_id]
            order.priority = final_priority
            # A linked flag without a system group is normalized only after all validation succeeded.
            if order.is_linked_child_group and not order.child_group_key:
                order.is_linked_child_group = False
            result = invalid_by_id.get(order_id)
            if result is None:
                result = engine.plan_prepared_order(prepared_by_id[order_id])
                if result.is_success:
                    result = self._guard_successful_result(result, order)
            if result.is_success:
                self._persist_successful_result(result, order)
                planned_count += 1; operation_count += len(result.operations)
            else:
                self._persist_conflict_result(result, order)
                conflict_count += 1
        self.session.flush()
        self._persist_plan_changes(run.id, previous_plan, self._current_plan_snapshot())
        run.finished_at = utc_now(); run.status = "completed"
        run.summary = f"Запланировано заказов: {planned_count}; конфликтов: {conflict_count}; операций: {operation_count}."
        self.session.flush()
        return RecalculationSummary(planned_count, conflict_count, operation_count, conflict_count, run.id)

    def _prepare_orders(
        self,
        orders_by_id: dict[int, Order],
        previously_planned_ids: set[int] | None = None,
        previously_conflicted_ids: set[int] | None = None,
    ) -> tuple[list[PreparedOrder], list[PlannedOrderResult]]:
        prepared_orders: list[PreparedOrder] = []
        invalid_results: list[PlannedOrderResult] = []

        orders = self.session.scalars(
            select(Order)
            .where(Order.id.in_(previously_planned_ids or set()))
            .order_by(Order.priority, Order.id)
        ).all()
        orders_by_id.update((order.id, order) for order in orders)
        route_ids = {order.route_id for order in orders}
        routes_by_id = {
            route.id: route
            for route in self.session.scalars(
                select(Route)
                .where(Route.id.in_(route_ids))
                .options(
                    selectinload(Route.operations).selectinload(
                        RouteOperation.work_center
                    )
                )
            ).all()
        }

        for order in orders:
            planning_order = map_order_to_planning(order)
            route = routes_by_id.get(order.route_id)
            route_operations = (
                tuple(
                    map_route_operation_to_planning(operation)
                    for operation in route.operations
                )
                if route and route.is_active and all(op.is_active and op.work_center and op.work_center.is_active for op in route.operations)
                else ()
            )
            try:
                if route is None:
                    raise ValueError("Маршрут не найден")
                if not route.is_active:
                    raise ValueError("Маршрут неактивен")
                if not route.operations:
                    raise ValueError("Маршрут не содержит операций")
                if any(not op.is_active for op in route.operations):
                    raise ValueError("Операция маршрута неактивна")
                if any(not op.work_center or not op.work_center.is_active for op in route.operations):
                    raise ValueError("Участок неактивен")
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

    def _guard_successful_result(
        self, result: PlannedOrderResult, order: Order
    ) -> PlannedOrderResult:
        """Prevent persisting a planned order that misses its shipment date."""
        last_finish = None
        if result.operations:
            last_finish = max(
                day.end_datetime
                for operation in result.operations
                for day in operation.days
            )
        if order.planning_mode == PLANNING_MODE_START:
            misses_start_deadline = (
                order.fixed_start_date is None
                or result.calculated_start_date is None
                or result.calculated_start_date != order.fixed_start_date
            )
            misses_finish_deadline = False
        else:
            misses_start_deadline = (
                order.shipment_date is None
                or
                result.calculated_start_date is None
                or result.calculated_start_date > order.shipment_date
            )
            misses_finish_deadline = (
                order.shipment_date is None
                or last_finish is None
                or last_finish.date() > order.shipment_date
            )
        if not misses_start_deadline and not misses_finish_deadline:
            return result

        return PlannedOrderResult(
            order_id=order.id,
            calculated_start_date=None,
            conflict=PlanningConflict(
                order_id=order.id,
                shipment_date=order.shipment_date,
                work_center_id=None,
                required_hours=sum(
                    operation.required_hours for operation in result.operations
                ),
                available_hours=0.0,
                deficit_hours=0.0,
                blocking_order_ids=(),
                reason=(
                    "Заказ не может быть сохранён как запланированный: "
                    "дата запуска или фактическое окончание последней операции "
                    "позже срока отгрузки."
                ),
            ),
        )

    def _persist_successful_result(
        self, result: PlannedOrderResult, order: Order
    ) -> None:
        order.status = ""
        if order.planning_mode == PLANNING_MODE_START:
            order.shipment_date = None
        else:
            order.fixed_start_date = None
        order.calculated_start_date = (
            None if order.planning_mode == PLANNING_MODE_START
            else result.calculated_start_date
        )
        order.calculated_shipment_date = None
        if order.planning_mode == PLANNING_MODE_START and result.operations:
            order.calculated_shipment_date = max(
                day.end_datetime
                for operation in result.operations
                for day in operation.days
            ).date()
        for scheduled_operation in result.operations:
            planned_operation = map_scheduled_operation_to_orm(scheduled_operation)
            self.plan_repository.add_planned_operation(planned_operation)
            days = map_scheduled_operation_days_to_orm(
                scheduled_operation, planned_operation.id
            )
            self.plan_repository.add_planned_operation_days(days)

    def _persist_conflict_result(
        self, result: PlannedOrderResult, order: Order | None = None
    ) -> None:
        if result.conflict is None:
            return
        if order is None:
            order = self.orders_repository.get_order(result.order_id)
        if order is not None:
            order.status = ""
            order.calculated_start_date = None
            order.calculated_shipment_date = None
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
                description = (
                    f"Операция {sequence_number} заказа {order_id} добавлена в план."
                )
            elif new_dates is None:
                change_type = "removed"
                description = (
                    f"Операция {sequence_number} заказа {order_id} удалена из плана."
                )
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
                    operation_sequence_number=sequence_number,
                    change_type=change_type,
                    old_start_date=old_dates[0] if old_dates else None,
                    old_end_date=old_dates[1] if old_dates else None,
                    new_start_date=new_dates[0] if new_dates else None,
                    new_end_date=new_dates[1] if new_dates else None,
                    description=description,
                )
            )
