"""Table row builders for Streamlit pages."""

from app.db.models import (
    Order,
    PlanChange,
    PlannedOperation,
    PlannedOperationDay,
    PlanningConflict,
    RecalculationRun,
    Route,
    RouteOperation,
    WorkCenter,
)


def order_rows(orders: list[Order]) -> list[dict[str, object]]:
    """Build display rows for the orders registry."""
    return [
        {
            "ID": order.id,
            "Номер": order.order_number,
            "Клиент": order.client_name,
            "Продукция": order.product_name,
            "Тираж": order.quantity,
            "Срок отгрузки": order.shipment_date,
            "Маршрут": order.route.name if order.route else None,
            "Статус": order.status,
            "Дата запуска": order.calculated_start_date,
            "Конфликт": bool(order.conflicts),
        }
        for order in orders
    ]


def work_center_rows(work_centers: list[WorkCenter]) -> list[dict[str, object]]:
    """Build display rows for work centers."""
    return [
        {
            "ID": item.id,
            "Название": item.name,
            "Доступное время в месяц": item.available_hours_per_day,
            "Время начала рабочего дня": item.workday_start_time.strftime("%H:%M"),
            "Активен": item.is_active,
            "Нельзя прерывать заказ при планировании": item.prevent_order_interruption,
        }
        for item in work_centers
    ]


def route_rows(routes: list[Route]) -> list[dict[str, object]]:
    """Build display rows for routes."""
    return [
        {
            "ID": route.id,
            "Название": route.name,
            "Описание": route.description or "",
            "Активен": route.is_active,
            "Операций": len(route.operations),
        }
        for route in routes
    ]


def route_operation_rows(operations: list[RouteOperation]) -> list[dict[str, object]]:
    """Build display rows for route operations."""
    return [
        {
            "ID": operation.id,
            "№": operation.sequence_number,
            "Участок": operation.work_center.name if operation.work_center else None,
            "Трудоёмкость на 1000": operation.labor_hours_per_1000,
            "Мин. передаточная партия": operation.min_transfer_quantity_to_next or 0.0,
        }
        for operation in operations
    ]


def planned_operation_rows(
    planned_operations: list[PlannedOperation],
) -> list[dict[str, object]]:
    """Build display rows for planned operation aggregates."""
    return [
        {
            "Заказ": (
                operation.order.order_number if operation.order else operation.order_id
            ),
            "Операция": operation.sequence_number,
            "Участок": (
                operation.work_center.name
                if operation.work_center
                else operation.work_center_id
            ),
            "Дата начала": operation.planned_start_date,
            "Дата окончания": operation.planned_end_date,
            "Требуется часов": round(operation.required_hours, 2),
            "Запланировано часов": round(operation.planned_hours, 2),
            "Статус": operation.status,
        }
        for operation in planned_operations
    ]


def planned_operation_day_rows(
    days: list[PlannedOperationDay],
) -> list[dict[str, object]]:
    """Build display rows for daily operation placements."""
    return [
        {
            "Плановая операция": day.planned_operation_id,
            "Участок": day.work_center.name if day.work_center else day.work_center_id,
            "Дата": day.date,
            "Часы": round(day.hours, 2),
        }
        for day in days
    ]


def conflict_rows(conflicts: list[PlanningConflict]) -> list[dict[str, object]]:
    """Build display rows for planning conflicts."""
    return [
        {
            "Заказ": (
                conflict.order.order_number if conflict.order else conflict.order_id
            ),
            "Срок отгрузки": conflict.shipment_date,
            "Ограничивающий участок": (
                conflict.work_center.name
                if conflict.work_center
                else conflict.work_center_id
            ),
            "Требуется часов": round(conflict.required_hours, 2),
            "Доступно часов": round(conflict.available_hours, 2),
            "Дефицит часов": round(conflict.deficit_hours, 2),
            "Мешающие заказы": conflict.blocking_order_ids,
            "Причина": conflict.reason,
        }
        for conflict in conflicts
    ]


def recalculation_rows(runs: list[RecalculationRun]) -> list[dict[str, object]]:
    """Build display rows for recalculation runs."""
    return [
        {
            "ID": run.id,
            "Старт": run.started_at,
            "Завершение": run.finished_at,
            "Статус": run.status,
            "Итог": run.summary,
        }
        for run in runs
    ]


def plan_change_rows(changes: list[PlanChange]) -> list[dict[str, object]]:
    """Build display rows for saved recalculation changes."""
    return [
        {
            "Тип": change.change_type,
            "Заказ": change.order_id,
            "Операция": change.planned_operation_id,
            "Старый старт": change.old_start_date,
            "Старое окончание": change.old_end_date,
            "Новый старт": change.new_start_date,
            "Новое окончание": change.new_end_date,
            "Описание": change.description,
        }
        for change in changes
    ]
