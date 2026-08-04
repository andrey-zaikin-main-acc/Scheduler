"""Atomic coordinator for applying session-scoped screen drafts."""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import MANUAL_ORDER_STATUSES, ORDER_STATUS_NEW, PLANNING_MODE_SHIPMENT, PLANNING_MODE_START
from app.db.models import Order, Route, RouteOperation
from app.repositories.orders_repository import OrdersRepository
from app.services.recalculation_service import RecalculationService, RecalculationSummary


@dataclass
class DraftBundle:
    """Serializable screen state; temporary ids are negative integers."""

    orders: list[dict[str, Any]] = field(default_factory=list)
    pending_delete_ids: set[int] = field(default_factory=set)
    routes: list[dict[str, Any]] = field(default_factory=list)
    operations: list[dict[str, Any]] = field(default_factory=list)
    work_centers: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class DraftCommitResult:
    ok: bool
    errors: tuple[str, ...] = ()
    summary: RecalculationSummary | None = None


class DraftCommitService:
    """Validate first, then apply and recalculate under exactly one commit."""

    def __init__(self, session: Session, recalculation_factory: Callable[[Session], RecalculationService] = RecalculationService):
        self.session = session
        self.recalculation_factory = recalculation_factory

    def commit(self, draft: DraftBundle, *, sections: set[str] | None = None) -> DraftCommitResult:
        """Compatibility alias for the only global, recalculating operation."""
        return self.commit_and_recalculate(draft, sections=sections)

    def commit_and_recalculate(self, draft: DraftBundle, *, sections: set[str] | None = None) -> DraftCommitResult:
        sections = sections or {"orders", "routes", "work_centers"}
        errors = self.validate(draft, sections=sections)
        if errors:
            return DraftCommitResult(False, tuple(errors))
        try:
            if "orders" in sections:
                self._apply_orders(draft)
            if "work_centers" in sections:
                self._apply_work_centers(draft)
            if "routes" in sections:
                self._apply_routes(draft)
            summary = self.recalculation_factory(self.session).recalculate_plan()
            self.session.commit()
            return DraftCommitResult(True, summary=summary)
        except Exception as exc:
            self.session.rollback()
            return DraftCommitResult(False, (f"Техническая ошибка: {exc}",))

    def save_reference_section(self, draft: DraftBundle, section: str) -> DraftCommitResult:
        """Validate and save one reference section without touching the plan."""
        if section not in {"routes", "work_centers"}:
            return DraftCommitResult(False, ("Локально сохраняются только справочники.",))
        errors = self.validate(draft, sections={section})
        if errors:
            return DraftCommitResult(False, tuple(errors))
        try:
            if section == "routes":
                self._apply_routes(draft)
            else:
                self._apply_work_centers(draft)
            self.session.commit()
            return DraftCommitResult(True)
        except Exception as exc:
            self.session.rollback()
            return DraftCommitResult(False, (f"Техническая ошибка: {exc}",))

    def validate(self, draft: DraftBundle, *, sections: set[str]) -> list[str]:
        errors: list[str] = []
        if "work_centers" in sections:
            errors.extend(self._validate_work_centers(draft.work_centers))
        if "routes" in sections:
            errors.extend(self._validate_routes(draft.routes, draft.operations))
        if "orders" not in sections:
            return errors
        persisted_routes = list(self.session.scalars(select(Route)).all())
        route_ids = {route.id for route in persisted_routes}
        # Global validation observes one virtual final model rather than a mix
        # of draft orders and persisted reference data.
        center_active = {item.name: item.is_active for item in __import__(
            "app.repositories.work_centers_repository", fromlist=["WorkCentersRepository"]
        ).WorkCentersRepository(self.session).list_work_centers()}
        if "work_centers" in sections:
            center_active.update({str(row.get("Название") or "").strip(): bool(row.get("Активен"))
                                  for row in draft.work_centers})
        route_active = {route.id: route.is_active for route in persisted_routes}
        if "routes" in sections:
            route_active.update({int(row["ID"]): bool(row.get("Активен")) for row in draft.routes
                                 if isinstance(row.get("ID"), int) and row["ID"] > 0})
        operations_by_route: dict[int, list[tuple[bool, str]]] = {
            route.id: [(op.is_active, op.work_center.name if op.work_center else "") for op in route.operations]
            for route in persisted_routes
        }
        if "routes" in sections:
            drafted_route_ids = {int(row["_route_id"]) for row in draft.operations
                                 if isinstance(row.get("_route_id"), int)}
            for route_id in drafted_route_ids:
                operations_by_route[route_id] = [
                    (bool(row.get("Активна")), str(row.get("Участок") or ""))
                    for row in draft.operations if row.get("_route_id") == route_id
                ]
        eligible_route_ids = {
            route_id for route_id in route_ids if route_active.get(route_id, False)
            and operations_by_route.get(route_id)
            and all(active and center_active.get(center, False)
                    for active, center in operations_by_route[route_id])
        }
        existing_orders = {order.id: order for order in self.session.scalars(select(Order)).all()}
        existing_statuses = {
            order.id: order.status for order in self.session.scalars(select(Order)).all()
        }
        numbers: dict[str, int] = {}
        priorities: dict[int, int] = {}
        final_order_rows = [row for row in draft.orders if not (
            isinstance(row.get("id"), int) and row["id"] in draft.pending_delete_ids)]
        for index, row in enumerate(final_order_rows, 1):
            label = f"Заказ, строка {index} (ID {row.get('id', 'новый')})"
            for field_name in ("order_number", "client_name", "product_name"):
                if not str(row.get(field_name) or "").strip():
                    errors.append(f"{label}: поле {field_name} обязательно.")
            try:
                if float(row.get("quantity")) <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append(f"{label}: поле quantity должно быть больше 0.")
            number = str(row.get("order_number") or "").strip()
            if number in numbers:
                errors.append(f"{label}: поле order_number дублирует строку {numbers[number]}.")
            numbers[number] = index
            status = row.get("status")
            if status != "Отменён":
                from app.services.order_queue_service import positive_integer
                priority = positive_integer(row.get("priority"))
                if priority is None:
                    errors.append(f"{label}, поле «Приоритет»: требуется положительное целое число.")
                elif priority in priorities:
                    errors.append(f"{label}, поле «Приоритет»: значение {priority} дублирует строку {priorities[priority]}.")
                else:
                    priorities[priority] = index
            if row.get("route_id") not in route_ids:
                errors.append(f"{label}: поле route_id содержит неизвестный маршрут.")
            elif status == ORDER_STATUS_NEW and row.get("route_id") not in eligible_route_ids:
                errors.append(f"{label}: маршрут, его операции и участки должны быть активны для нового или возвращённого в «Новый» заказа.")
            unchanged_system_status = status == existing_statuses.get(row.get("id"))
            if status not in MANUAL_ORDER_STATUSES and not unchanged_system_status:
                errors.append(f"{label}: поле status можно вручную задать только как Новый или Отменён.")
            mode = row.get("planning_mode", PLANNING_MODE_SHIPMENT)
            if mode == PLANNING_MODE_START:
                if not isinstance(row.get("fixed_start_date"), date):
                    errors.append(f"{label}: поле fixed_start_date обязательно.")
            elif mode == PLANNING_MODE_SHIPMENT:
                if not isinstance(row.get("shipment_date"), date):
                    errors.append(f"{label}: поле shipment_date обязательно.")
            else:
                errors.append(f"{label}: неизвестный режим планирования.")
        return errors

    def _validate_work_centers(self, rows: list[dict[str, Any]]) -> list[str]:
        existing = {item.name: item.id for item in __import__(
            "app.repositories.work_centers_repository", fromlist=["WorkCentersRepository"]
        ).WorkCentersRepository(self.session).list_work_centers()}
        owners: dict[str, int | None] = dict(existing)
        errors: list[str] = []
        for index, row in enumerate(rows, 1):
            label = f"Участки, строка {index}"
            name = str(row.get("Название") or "").strip()
            try:
                hours = float(row.get("Доступное время в месяц"))
            except (TypeError, ValueError):
                hours = 0
            if not name:
                errors.append(f"{label}, поле «Название»: обязательное поле.")
            elif name in owners and owners[name] != row.get("ID"):
                errors.append(f"{label}, поле «Название»: название должно быть уникальным.")
            else:
                owners[name] = row.get("ID")
            if hours <= 0:
                errors.append(f"{label}, поле «Доступное время в месяц»: значение должно быть больше нуля.")
            for field in ("Активен", "Нельзя прерывать заказ при планировании"):
                if not isinstance(row.get(field), bool):
                    errors.append(f"{label}, поле «{field}»: ожидается флаг да/нет.")
        return errors

    def _validate_routes(self, routes: list[dict[str, Any]], operations: list[dict[str, Any]]) -> list[str]:
        existing_routes = {item.name: item.id for item in self.session.scalars(select(Route)).all()}
        names: dict[str, int | None] = dict(existing_routes)
        errors: list[str] = []
        for index, row in enumerate(routes, 1):
            label = f"Маршруты, строка {index}"
            name = str(row.get("Название") or "").strip()
            if not name:
                errors.append(f"{label}, поле «Название»: обязательное поле.")
            elif name in names and names[name] != row.get("ID"):
                errors.append(f"{label}, поле «Название»: название должно быть уникальным.")
            else:
                names[name] = row.get("ID")
            if not isinstance(row.get("Активен"), bool):
                errors.append(f"{label}, поле «Активен»: ожидается флаг да/нет.")

        active_centers = {item.name for item in __import__(
            "app.repositories.work_centers_repository", fromlist=["WorkCentersRepository"]
        ).WorkCentersRepository(self.session).list_work_centers() if item.is_active}
        seen_numbers: dict[tuple[int, int], int] = {}
        for index, row in enumerate(operations, 1):
            label = f"Операции, строка {index}"
            try:
                route_id, number = int(row.get("_route_id")), int(row.get("№"))
            except (TypeError, ValueError):
                route_id, number = 0, 0
            key = (route_id, number)
            if number <= 0:
                errors.append(f"{label}, поле «№»: номер должен быть положительным целым числом.")
            elif key in seen_numbers:
                errors.append(f"{label}, поле «№»: номер должен быть уникальным внутри маршрута.")
            else:
                seen_numbers[key] = index
            if row.get("Участок") not in active_centers:
                errors.append(f"{label}, поле «Участок»: выберите активный участок.")
            for field, allow_zero in (("Трудоёмкость на 1000", False), ("Мин. передаточная партия", True)):
                try:
                    value = float(row.get(field))
                except (TypeError, ValueError):
                    value = -1
                if value < 0 or (not allow_zero and value == 0):
                    reason = "неотрицательным" if allow_zero else "больше нуля"
                    errors.append(f"{label}, поле «{field}»: значение должно быть {reason}.")
            if not isinstance(row.get("Активна"), bool):
                errors.append(f"{label}, поле «Активна»: ожидается флаг да/нет.")
        return errors

    def _apply_work_centers(self, draft: DraftBundle) -> None:
        from datetime import time
        from app.repositories.work_centers_repository import WorkCentersRepository
        repository = WorkCentersRepository(self.session)
        existing = {item.id: item for item in repository.list_work_centers()}
        for row in draft.work_centers:
            name = str(row.get("Название") or "").strip()
            hours = float(row.get("Доступное время в месяц") or 0)
            if not name or hours <= 0:
                raise ValueError("Участок: название и доступное время обязательны.")
            payload = dict(name=name, available_hours_per_day=hours,
                           workday_start_time=time(9), is_active=bool(row.get("Активен", True)),
                           prevent_order_interruption=bool(row.get("Нельзя прерывать заказ при планировании")))
            if row.get("ID") in existing:
                repository.update_work_center(int(row["ID"]), **payload)
            else:
                repository.create_work_center(**payload)

    def _apply_routes(self, draft: DraftBundle) -> None:
        from app.repositories.routes_repository import RoutesRepository
        repository = RoutesRepository(self.session)
        existing = {item.id: item for item in repository.list_routes_with_operations()}
        for row in draft.routes:
            name = str(row.get("Название") or "").strip()
            if not name:
                raise ValueError("Маршрут: название обязательно.")
            payload = dict(name=name, description=str(row.get("Описание") or "").strip() or None,
                           is_active=bool(row.get("Активен", True)))
            if row.get("ID") in existing:
                repository.update_route(int(row["ID"]), **payload)
            else:
                repository.create_route(**payload)
        work_centers = {item.name: item for item in __import__(
            "app.repositories.work_centers_repository", fromlist=["WorkCentersRepository"]
        ).WorkCentersRepository(self.session).list_work_centers() if item.is_active}
        from app.db.models import RouteOperation
        existing_operations = {op.id: op for op in self.session.scalars(select(RouteOperation)).all()}
        for row in draft.operations:
            center = work_centers.get(row.get("Участок"))
            if center is None:
                raise ValueError("Операция: выберите активный участок.")
            payload = dict(sequence_number=int(row.get("№") or 0), work_center_id=center.id,
                           labor_hours_per_1000=float(row.get("Трудоёмкость на 1000") or 0),
                           min_transfer_quantity_to_next=float(row.get("Мин. передаточная партия") or 0) or None,
                           is_active=bool(row.get("Активна", True)))
            if payload["sequence_number"] < 1 or payload["labor_hours_per_1000"] <= 0:
                raise ValueError("Операция: номер и трудоёмкость должны быть больше нуля.")
            if row.get("ID") in existing_operations:
                repository.update_operation(int(row["ID"]), **payload)
            else:
                repository.add_operation(route_id=int(row["_route_id"]), **payload)

    def _apply_orders(self, draft: DraftBundle) -> None:
        repository = OrdersRepository(self.session)
        for order_id in draft.pending_delete_ids:
            repository.delete_order(order_id)
        existing = {order.id: order for order in repository.list_orders()}
        for row in draft.orders:
            payload = {key: row.get(key) for key in (
                "order_number", "client_name", "product_name", "quantity", "shipment_date",
                "route_id", "status", "planning_mode", "fixed_start_date", "child_group_key",
                "child_sequence_number", "is_child_order", "is_linked_child_group", "priority"
            )}
            payload["status"] = payload["status"] or ""
            row_id = int(row.get("id") or -1)
            if row_id > 0 and row_id in existing:
                repository.update_order(row_id, **payload)
            else:
                repository.create_order(**payload)


def success_flash(summary: RecalculationSummary) -> str:
    return f"Изменения сохранены. План пересчитан: запланировано — {summary.planned_orders}, конфликтов — {summary.conflicts}."
