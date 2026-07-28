"""Atomic coordinator for applying session-scoped screen drafts."""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.constants import MANUAL_ORDER_STATUSES, ORDER_STATUS_NEW, PLANNING_MODE_SHIPMENT, PLANNING_MODE_START
from app.db.models import Order, Route
from app.repositories.orders_repository import OrdersRepository
from app.services.recalculation_service import RecalculationService, RecalculationSummary


@dataclass
class DraftBundle:
    """Serializable screen state; temporary ids are negative integers."""

    orders: list[dict[str, Any]] = field(default_factory=list)
    pending_delete_ids: set[int] = field(default_factory=set)
    routes: list[dict[str, Any]] = field(default_factory=list)
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
        sections = sections or {"orders", "routes", "work_centers"}
        errors = self.validate(draft, sections=sections)
        if errors:
            return DraftCommitResult(False, tuple(errors))
        try:
            if "orders" in sections:
                self._apply_orders(draft)
            # Route/work-center page adapters apply their rows before invoking
            # this coordinator; their validation is still section-isolated.
            summary = self.recalculation_factory(self.session).recalculate_plan()
            self.session.commit()
            return DraftCommitResult(True, summary=summary)
        except Exception as exc:
            self.session.rollback()
            return DraftCommitResult(False, (f"Техническая ошибка: {exc}",))

    def validate(self, draft: DraftBundle, *, sections: set[str]) -> list[str]:
        errors: list[str] = []
        if "orders" not in sections:
            return errors
        route_ids = set(self.session.scalars(select(Route.id)).all())
        numbers: dict[str, int] = {}
        for index, row in enumerate(draft.orders, 1):
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
            if row.get("route_id") not in route_ids:
                errors.append(f"{label}: поле route_id содержит неизвестный маршрут.")
            if row.get("status") not in MANUAL_ORDER_STATUSES:
                errors.append(f"{label}: поле status можно вручную задать только как Новый или Отменён.")
            mode = row.get("planning_mode", PLANNING_MODE_SHIPMENT)
            if mode == PLANNING_MODE_START and not isinstance(row.get("fixed_start_date"), date):
                errors.append(f"{label}: поле fixed_start_date обязательно.")
            if mode == PLANNING_MODE_SHIPMENT and not isinstance(row.get("shipment_date"), date):
                errors.append(f"{label}: поле shipment_date обязательно.")
        return errors

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
            payload["shipment_date"] = payload["shipment_date"] if payload["planning_mode"] == PLANNING_MODE_SHIPMENT else None
            payload["fixed_start_date"] = payload["fixed_start_date"] if payload["planning_mode"] == PLANNING_MODE_START else None
            if int(row.get("id", -1)) > 0 and int(row["id"]) in existing:
                repository.update_order(int(row["id"]), **payload)
            else:
                repository.create_order(**payload)
        repository.normalize_priorities()


def success_flash(summary: RecalculationSummary) -> str:
    return f"Изменения сохранены. План пересчитан: запланировано — {summary.planned_orders}, конфликтов — {summary.conflicts}."
