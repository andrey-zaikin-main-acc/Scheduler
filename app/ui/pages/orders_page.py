"""Orders registry page."""

from datetime import date, datetime, timedelta
import math
from typing import Any

import streamlit as st
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.constants import (
    CALCULATED_ORDER_STATUSES,
    MANUAL_ORDER_STATUSES,
    ORDER_STATUSES,
    PLANNING_MODE_SHIPMENT,
    PLANNING_MODE_START,
    PLANNING_MODES,
    ORDER_STATUS_NEW,
)
from app.db.database import SessionLocal
from app.db.models import Order, RecalculationRun, Route, RouteOperation, WorkCenter
from app.repositories.orders_repository import OrdersRepository
from app.services.route_capacity_service import RouteCapacityService
from app.ui.components.tables import order_rows
from app.ui.pages.page_utils import recalculate_after_save

EDITOR_COLUMNS = [
    "Выбран",
    "ID",
    "Приоритет",
    "Номер",
    "Клиент",
    "Продукция",
    "Тираж",
    "Режим планирования",
    "Заданная дата запуска",
    "Заданная дата отгрузки",
    "Расчётная дата запуска",
    "Расчётная дата отгрузки",
    "Группа",
    "Связанные заказы",
    "Маршрут",
    "Статус",
    "Запланирован",
    "Конфликт планирования",
]
DRAFT_ORDER_SESSION_KEY = "orders_page_show_new_order_form"
SELECTED_ORDER_SESSION_KEY = "orders_page_selected_order_id"
ORDER_EDITOR_KEY = "orders_page_editor"
READ_ONLY_EDITOR_COLUMNS = [
    "ID",
    "Расчётная дата запуска",
    "Расчётная дата отгрузки",
    "Запланирован",
    "Конфликт планирования",
    "Группа",
]


def render_orders_page() -> None:
    """Render the registry over a session draft; SQLite is read only on load."""
    st.header("Реестр заказов")
    flash = st.session_state.pop("draft_flash", None)
    if flash:
        st.success(flash)
    with SessionLocal() as session:
        all_routes = list(session.scalars(select(Route).options(selectinload(Route.operations)).order_by(Route.name)).all())
        routes = [route for route in all_routes if route.is_active and route.operations and all(op.is_active and op.work_center and op.work_center.is_active for op in route.operations)]
        route_by_name = {route.name: route for route in all_routes}
        orders = list(session.scalars(select(Order).options(selectinload(Order.route), selectinload(Order.conflicts), selectinload(Order.planned_operations)).order_by(Order.id)).all())
        _render_route_capacity_check(session, routes)
        if st.button("Добавить заказ", disabled=not routes, key="show_add_order"):
            st.session_state[DRAFT_ORDER_SESSION_KEY] = True
        if st.session_state.get(DRAFT_ORDER_SESSION_KEY):
            _render_new_order_form(session, OrdersRepository(session), routes, route_by_name)

        if "orders_draft_rows" not in st.session_state:
            st.session_state.orders_draft_rows = build_order_editor_rows(orders, selected_order_id=None, include_draft=False)
            st.session_state.orders_pending_delete_ids = set()
        rows = st.session_state.orders_draft_rows
        _sync_order_editor_state(rows)
        edited = st.data_editor(rows, key=ORDER_EDITOR_KEY, use_container_width=True, hide_index=True,
            disabled=READ_ONLY_EDITOR_COLUMNS, column_order=EDITOR_COLUMNS, num_rows="fixed",
            column_config={
                "Выбран": st.column_config.CheckboxColumn("Выбран"),
                "Статус": st.column_config.SelectboxColumn("Статус", options=list(MANUAL_ORDER_STATUSES)),
                "Маршрут": st.column_config.SelectboxColumn("Маршрут", options=[route.name for route in routes]),
                "Режим планирования": st.column_config.SelectboxColumn("Режим планирования", options=list(PLANNING_MODES)),
                "Заданная дата запуска": st.column_config.DateColumn("Заданная дата запуска", format="DD.MM.YYYY"),
                "Заданная дата отгрузки": st.column_config.DateColumn("Заданная дата отгрузки", format="DD.MM.YYYY"),
            }) if rows else []
        # Capture the current editor value on every rerun. Navigation deliberately
        # handles the recalculation button after this page has rendered.
        st.session_state.orders_draft_rows = edited
        selected = [row for row in edited if row.get("Выбран")]
        if st.button("Удалить выбранные заказы", disabled=not selected, use_container_width=True):
            pending = st.session_state.orders_pending_delete_ids
            for row in selected:
                if isinstance(row.get("ID"), int) and row["ID"] > 0:
                    pending.add(row["ID"])
            st.session_state.orders_draft_rows = [row for row in edited if not row.get("Выбран")]
            st.rerun()


def _editor_row_to_draft(row: dict[str, Any], route_by_name: dict[str, Route]) -> dict[str, Any]:
    route = route_by_name.get(row.get("Маршрут"))
    return {
        "id": row.get("ID"), "priority": row.get("Приоритет"),
        "order_number": row.get("Номер"), "client_name": row.get("Клиент"),
        "product_name": row.get("Продукция"), "quantity": row.get("Тираж"),
        "planning_mode": row.get("Режим планирования"),
        "fixed_start_date": row.get("Заданная дата запуска", row.get("Фиксированная дата запуска")),
        "shipment_date": row.get("Заданная дата отгрузки", row.get("Срок отгрузки")),
        "route_id": route.id if route else row.get("_route_id"), "status": row.get("Статус") or "",
        "child_group_key": row.get("Группа") or None,
        "child_sequence_number": row.get("_child_sequence_number"),
        "is_child_order": bool(row.get("_is_child_order", row.get("Группа"))),
        "is_linked_child_group": bool(row.get("Связанные заказы")),
    }


NEW_ORDER_DEFAULTS = {
    "order_number": "",
    "client_name": "",
    "product_name": "",
    "quantity": 0.0,
    "route_name": None,
    "planning_mode": PLANNING_MODE_SHIPMENT,
    "shipment_date": None,
    "fixed_start_date": None,
    "split": False,
    "child_size": 0.0,
    "linked": False,
}


def _new_order_state() -> dict[str, Any]:
    state = st.session_state.setdefault(
        "orders_page_new_order_form", dict(NEW_ORDER_DEFAULTS)
    )
    for key, value in NEW_ORDER_DEFAULTS.items():
        state.setdefault(key, value)
    return state


def _render_new_order_form(
    session,
    repository: OrdersRepository,
    routes: list[Route],
    route_by_name: dict[str, Route],
) -> None:
    st.subheader("Новый заказ")
    state = _new_order_state()
    c1, c2, c3 = st.columns(3)
    state["order_number"] = c1.text_input(
        "Номер", value=state["order_number"], key="new_order_number"
    )
    state["client_name"] = c2.text_input(
        "Клиент", value=state["client_name"], key="new_client"
    )
    state["product_name"] = c3.text_input(
        "Продукция", value=state["product_name"], key="new_product"
    )
    c4, c5, c6 = st.columns(3)
    state["quantity"] = c4.number_input(
        "Тираж",
        min_value=0.0,
        step=100.0,
        value=float(state["quantity"] or 0.0),
        key="new_quantity",
    )
    route_names = [route.name for route in routes]
    route_index = (
        route_names.index(state["route_name"])
        if state["route_name"] in route_names
        else None
    )
    state["route_name"] = c5.selectbox(
        "Маршрут", options=route_names, index=route_index, key="new_route"
    )
    state["planning_mode"] = c6.radio(
        "Режим планирования",
        options=list(PLANNING_MODES),
        index=list(PLANNING_MODES).index(state["planning_mode"]),
        horizontal=True,
        key="new_mode",
    )
    if state["planning_mode"] == PLANNING_MODE_START:
        state["fixed_start_date"] = st.date_input(
            "Дата запуска",
            value=state["fixed_start_date"],
            format="DD.MM.YYYY",
            key="new_fixed_start",
        )
        state["shipment_date"] = None
    else:
        state["shipment_date"] = st.date_input(
            "Срок отгрузки",
            value=state["shipment_date"],
            format="DD.MM.YYYY",
            key="new_ship_date",
        )
        state["fixed_start_date"] = None
    state["split"] = st.checkbox(
        "Разбить заказ на партии", value=bool(state["split"]), key="new_split"
    )
    if state["split"]:
        s1, s2 = st.columns(2)
        state["child_size"] = s1.number_input(
            "Размер одного дочернего заказа",
            min_value=0.0,
            step=100.0,
            value=float(state["child_size"] or 0.0),
            key="new_child_size",
        )
        state["linked"] = s2.checkbox(
            "Дочерние заказы связанные", value=bool(state["linked"]), key="new_linked"
        )
    save_col, clear_col = st.columns(2)
    if save_col.button("Добавить заказ", use_container_width=True, key="new_save"):
        _save_new_order_form(session, repository, state, route_by_name)
    if clear_col.button("Очистить поле", use_container_width=True, key="new_clear"):
        st.session_state["orders_page_new_order_form"] = dict(NEW_ORDER_DEFAULTS)
        for key in [
            "new_order_number",
            "new_client",
            "new_product",
            "new_quantity",
            "new_route",
            "new_mode",
            "new_fixed_start",
            "new_ship_date",
            "new_split",
            "new_child_size",
            "new_linked",
        ]:
            st.session_state.pop(key, None)
        st.rerun()


def _save_new_order_form(session, repository: OrdersRepository, state: dict[str, Any], route_by_name: dict[str, Route]) -> None:
    """Append form values to the screen draft without validation or DB writes."""
    rows = st.session_state.setdefault("orders_draft_rows", [])
    next_id = min([int(row.get("ID")) for row in rows if isinstance(row.get("ID"), int) and row.get("ID") < 0] or [0]) - 1
    quantities = [state.get("quantity")]
    numbers = [str(state.get("order_number") or "")]
    if state.get("split") and float(state.get("child_size") or 0) > 0:
        quantities = _split_child_quantities(float(state.get("quantity") or 0), float(state["child_size"]))
        numbers = [f"{state.get('order_number')}.{i}" for i in range(1, len(quantities) + 1)]
    priority = max((_parse_priority(row.get("Приоритет")) or 0 for row in rows
                    if row.get("Статус") != "Отменён"), default=0) + 1
    for sequence, (number, quantity) in enumerate(zip(numbers, quantities, strict=True), 1):
        rows.append({
            "Выбран": False, "ID": next_id, "Приоритет": priority,
            "Номер": number, "Клиент": state.get("client_name", ""),
            "Продукция": state.get("product_name", ""), "Тираж": quantity,
            "Режим планирования": state.get("planning_mode"),
            "Заданная дата запуска": state.get("fixed_start_date") if state.get("planning_mode") == PLANNING_MODE_START else None,
            "Заданная дата отгрузки": state.get("shipment_date") if state.get("planning_mode") == PLANNING_MODE_SHIPMENT else None,
            "Расчётная дата запуска": None, "Расчётная дата отгрузки": None,
            "Группа": str(state.get("order_number") or "") if len(numbers) > 1 else "",
            "_child_sequence_number": sequence if len(numbers) > 1 else None,
            "_is_child_order": len(numbers) > 1,
            "Связанные заказы": bool(state.get("linked")), "Маршрут": state.get("route_name"),
            "Статус": ORDER_STATUS_NEW, "Запланирован": False, "Конфликт планирования": False,
        })
        next_id -= 1; priority += 1
    st.session_state[DRAFT_ORDER_SESSION_KEY] = False
    st.rerun()


def _split_child_quantities(total: float, size: float) -> list[float]:
    """Split a float quantity without losing or inventing a final remainder."""
    quotient = total / size
    nearest = round(quotient)
    count = (
        nearest
        if math.isclose(quotient, nearest, rel_tol=1e-12, abs_tol=1e-12)
        else math.ceil(quotient)
    )
    quantities = [size] * max(0, count - 1)
    quantities.append(total - math.fsum(quantities))
    return quantities


_ORDER_EDITOR_SIGNATURE_SESSION_KEY = "orders_page_editor_signature"


def _sync_order_editor_state(rows: list[dict[str, Any]]) -> None:
    """Reset stale data-editor widget state when database-backed rows change."""
    signature = _order_editor_rows_signature(rows)
    if st.session_state.get(_ORDER_EDITOR_SIGNATURE_SESSION_KEY) != signature:
        st.session_state.pop(ORDER_EDITOR_KEY, None)
        st.session_state[_ORDER_EDITOR_SIGNATURE_SESSION_KEY] = signature


def _order_editor_rows_signature(
    rows: list[dict[str, Any]],
) -> tuple[tuple[Any, ...], ...]:
    """Return a stable signature for persisted order data, excluding UI selection."""
    data_columns = [column for column in EDITOR_COLUMNS if column != "Выбран"]
    return tuple(tuple(row.get(column) for column in data_columns) for row in rows)


def reconcile_priority_move(
    previous: list[dict[str, Any]], edited: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Interpret one changed priority as a queue/block move and renumber it."""
    old_by_id = {row.get("ID"): row for row in previous}
    returned = [row for row in edited if row.get("Статус") == ORDER_STATUS_NEW
                and old_by_id.get(row.get("ID"), {}).get("Статус") != ORDER_STATUS_NEW]
    changed = [
        row for row in edited
        if row.get("Статус") == ORDER_STATUS_NEW
        and _parse_priority(row.get("Приоритет")) is not None
        and _parse_priority(row.get("Приоритет"))
        != _parse_priority(old_by_id.get(row.get("ID"), {}).get("Приоритет"))
    ]
    queue = [row for row in edited if row.get("Статус") == ORDER_STATUS_NEW and row not in returned]
    queue.sort(key=lambda row: (_parse_priority(old_by_id.get(row.get("ID"), {}).get("Приоритет")) or 10**9,
                                list(edited).index(row)))
    if len(changed) == 1:
        moving = changed[0]
        group = moving.get("Группа") if moving.get("Связанные заказы") else None
        block = [r for r in queue if group and r.get("Связанные заказы") and r.get("Группа") == group] or [moving]
        block.sort(key=lambda r: (r.get("_child_sequence_number") or 0, r.get("ID") or 0))
        remaining = [r for r in queue if r not in block]
        target = max(0, min(_parse_priority(moving.get("Приоритет")) - 1, len(remaining)))
        queue = remaining[:target] + block + remaining[target:]
    queue.extend(returned)
    for priority, row in enumerate(queue, 1):
        row["Приоритет"] = priority
    for row in edited:
        if row.get("Статус") != ORDER_STATUS_NEW:
            row["Приоритет"] = None
    return edited


def normalize_scheduling_cells(previous, edited):
    """Apply the row mode contract immediately to the single table draft.

    The incompatible cell is cleared rather than copied, so switching back never
    resurrects a stale constraint.  Validation repeats this contract at commit.
    """
    result = []
    for row in edited:
        item = dict(row)
        if item.get("Режим планирования") == PLANNING_MODE_START:
            item["Заданная дата отгрузки"] = None
        elif item.get("Режим планирования") == PLANNING_MODE_SHIPMENT:
            item["Заданная дата запуска"] = None
        result.append(item)
    return result


PLANNING_FIELDS = {
    "Приоритет", "Тираж", "Маршрут", "Режим планирования",
    "Заданная дата запуска", "Заданная дата отгрузки", "Группа",
    "Связанные заказы", "_child_sequence_number", "_is_child_order",
}


def disabled_order_cells(row: dict[str, Any]) -> set[str]:
    """Describe row-specific cells which the single-table contract locks."""
    disabled = {"Расчётная дата запуска", "Расчётная дата отгрузки"}
    if row.get("Статус") != ORDER_STATUS_NEW and (
        row.get("Статус") in CALCULATED_ORDER_STATUSES
        or row.get("Запланирован") or row.get("Конфликт планирования")
    ):
        disabled.update(PLANNING_FIELDS)
    elif row.get("Режим планирования") == PLANNING_MODE_START:
        disabled.add("Заданная дата отгрузки")
    else:
        disabled.add("Заданная дата запуска")
    return disabled


def protect_calculated_order_fields(previous, edited):
    """Reject planning-cell edits until a calculated row is returned to New."""
    old_by_id = {row.get("ID"): row for row in previous}
    protected_rows = []
    for row in edited:
        item = dict(row)
        old = old_by_id.get(item.get("ID"), {})
        if item.get("Статус") != ORDER_STATUS_NEW:
            for field in disabled_order_cells(old):
                if field in PLANNING_FIELDS:
                    item[field] = old.get(field)
        protected_rows.append(item)
    return protected_rows


def apply_scheduling_overrides(rows, overrides):
    """Backward-compatible pure helper for older callers and stored sessions."""
    patched = []
    for index, row in enumerate(rows):
        item = dict(row)
        if index in overrides:
            mode, value = overrides[index]
            item["Режим планирования"] = mode
            item["Заданная дата запуска"] = value if mode == PLANNING_MODE_START else None
            item["Заданная дата отгрузки"] = value if mode == PLANNING_MODE_SHIPMENT else None
        patched.append(item)
    return normalize_scheduling_cells(rows, patched)


def order_status_options_for_row(status: str) -> list[str]:
    """Return status choices displayed by the orders data editor."""
    return list(ORDER_STATUSES)


def render_order_status_selectors(rows: list[dict[str, Any]]) -> dict[int, str]:
    """Render per-row status selectboxes because data_editor has column-wide options only."""
    if not rows:
        return {}
    st.caption(
        "Ручное изменение статусов: расчётный статус показан только как текущее значение строки; вручную доступны «Новый» и «Отменён»."
    )
    overrides: dict[int, str] = {}
    for index, row in enumerate(rows):
        current_status = str(row.get("Статус") or ORDER_STATUS_NEW)
        options = order_status_options_for_row(current_status)
        order_label = row.get("Номер") or "новый заказ"
        overrides[index] = st.selectbox(
            f"Статус заказа {order_label}",
            options=options,
            index=options.index(current_status) if current_status in options else 0,
            key=f"orders_page_status_{row.get('ID') or f'draft_{index}'}",
            help="Системные статусы нельзя назначить вручную; они обновятся после пересчёта.",
        )
    return overrides


def apply_order_status_overrides(
    rows: list[dict[str, Any]], overrides: dict[int, str]
) -> list[dict[str, Any]]:
    """Apply status values selected in row-specific controls to edited table rows."""
    return [
        {**row, "Статус": overrides.get(index, row.get("Статус"))}
        for index, row in enumerate(rows)
    ]


def build_order_editor_rows(
    orders: list[Order], *, selected_order_id: int | None, include_draft: bool
) -> list[dict[str, Any]]:
    """Build rows for the editable orders table."""
    rows = [
        {"Выбран": order.id == selected_order_id, **row}
        for order, row in zip(orders, order_rows(orders), strict=True)
    ]
    if include_draft:
        rows.append(
            {
                "Выбран": False,
                "ID": None,
                "Приоритет": len(orders) + 1,
                "Номер": "",
                "Клиент": "",
                "Продукция": "",
                "Тираж": 0.0,
                "Режим планирования": PLANNING_MODE_SHIPMENT,
                "Фиксированная дата запуска": None,
                "Расчётная дата запуска": None,
                "Срок отгрузки": None,
                "Группа": "",
                "Связанные заказы": False,
                "Маршрут": None,
                "Статус": ORDER_STATUS_NEW,
                "Конфликт": False,
            }
        )
    return rows


def validate_order_editor_row(
    row: dict[str, Any],
    *,
    route_names: set[str],
    existing_numbers: dict[str, int],
    current_order_id: int | None,
    original_status: str | None = None,
) -> list[str]:
    """Validate an edited order table row."""
    errors: list[str] = []
    order_number = str(row.get("Номер") or "").strip()
    client_name = str(row.get("Клиент") or "").strip()
    product_name = str(row.get("Продукция") or "").strip()
    route_name = row.get("Маршрут")
    status = row.get("Статус")
    quantity = _parse_quantity(row.get("Тираж"))
    priority = _parse_priority(row.get("Приоритет"))

    if not order_number:
        errors.append("Номер заказа обязателен.")
    duplicate_id = existing_numbers.get(order_number)
    if duplicate_id is not None and duplicate_id != current_order_id:
        errors.append("Заказ с таким номером уже существует.")
    if not client_name:
        errors.append("Клиент обязателен.")
    if not product_name:
        errors.append("Продукция обязательна.")
    if quantity is None or quantity <= 0:
        errors.append("Тираж должен быть больше 0.")
    if current_order_id is not None and "Приоритет" in row and priority is None:
        errors.append("Приоритет должен быть целым числом не меньше 1.")
    if row.get("Режим планирования") == PLANNING_MODE_START:
        if normalize_editor_date(_scheduling_value(row, "Заданная дата запуска", "Фиксированная дата запуска")) is None:
            errors.append("Фиксированная дата запуска обязательна.")
    elif normalize_editor_date(_scheduling_value(row, "Заданная дата отгрузки", "Срок отгрузки")) is None:
        errors.append("Срок отгрузки обязателен.")
    if not route_name or route_name not in route_names:
        errors.append("Маршрут обязателен.")
    if current_order_id is None and status != ORDER_STATUS_NEW:
        errors.append("Новый заказ можно создать только со статусом «Новый».")
    elif (
        current_order_id is not None
        and status not in MANUAL_ORDER_STATUSES
        and not (status == original_status and status in CALCULATED_ORDER_STATUSES)
    ):
        errors.append(
            "Статус «Запланирован» назначается только после пересчёта; вручную можно сохранить только «Новый» или «Отменён»."
        )
    return errors


def _process_editor_changes(
    session,
    repository: OrdersRepository,
    orders: list[Order],
    edited_rows: list[dict[str, Any]],
    route_by_name: dict[str, Route],
    *,
    save_requested: bool,
) -> None:
    original_by_id = {order.id: order for order in orders}
    original_priorities = {
        order.id: (order.priority or index)
        for index, order in enumerate(orders, start=1)
    }
    selected_ids = [
        int(row["ID"])
        for row in edited_rows
        if row.get("Выбран") and row.get("ID") is not None
    ]
    selected_id = selected_ids[-1] if selected_ids else None
    if selected_id != st.session_state.get(SELECTED_ORDER_SESSION_KEY):
        st.session_state[SELECTED_ORDER_SESSION_KEY] = selected_id
        if not save_requested:
            st.rerun()

    if not save_requested:
        return

    # Uniqueness is the only validation that intentionally considers the whole
    # final snapshot. Duplicate priorities are move commands, not errors.
    number_rows: dict[str, list[dict[str, Any]]] = {}
    for row in edited_rows:
        number = str(row.get("Номер") or "").strip()
        if number:
            number_rows.setdefault(number, []).append(row)
    final_number_owners = {
        number: rows_for_number[0].get("ID")
        for number, rows_for_number in number_rows.items()
        if len(rows_for_number) == 1
    }

    validation_errors: list[str] = []
    for number, duplicate_rows in number_rows.items():
        if len(duplicate_rows) > 1:
            for row in duplicate_rows:
                validation_errors.append(
                    f"{_row_label(row)}: номер заказа {number!r} должен быть уникальным."
                )

    changed_rows: list[tuple[dict[str, Any], Order | None]] = []
    for row in edited_rows:
        order_id = row.get("ID")
        if order_id is not None and "Приоритет" not in row:
            row["Приоритет"] = original_priorities[int(order_id)]
        if order_id is None:
            if _is_blank_draft_row(row):
                continue
            changed_rows.append((row, None))
            errors = validate_order_editor_row(
                row,
                route_names=set(route_by_name),
                existing_numbers=final_number_owners,
                current_order_id=None,
            )
            validation_errors.extend(
                f"{_row_label(row)}: {error[0].lower() + error[1:]}" for error in errors
            )
            continue
        order = original_by_id.get(int(order_id)) if order_id is not None else None
        if order is not None and _row_changed(row, order):
            changed_rows.append((row, order))
            errors = validate_order_editor_row(
                row,
                route_names=set(route_by_name),
                existing_numbers=final_number_owners,
                current_order_id=order.id,
                original_status=order.status,
            )
        else:
            errors = []
        validation_errors.extend(
            f"{_row_label(row)}: {error[0].lower() + error[1:]}" for error in errors
        )

    if validation_errors:
        for error in validation_errors:
            st.error(error)
        # Validation happened before writes; expiring protects callers that had
        # unrelated autoflush changes from observing a partially prepared state.
        if hasattr(session, "rollback"):
            session.rollback()
        return

    try:
        for row, order in changed_rows:
            if order is None:
                repository.create_order(**_row_to_order_payload(row, route_by_name))
                st.session_state[DRAFT_ORDER_SESSION_KEY] = False
                continue
            payload = _row_to_order_payload(
                row, route_by_name, original_status=order.status
            )
            payload.update(
                {
                    "child_group_key": order.child_group_key,
                    "child_sequence_number": order.child_sequence_number,
                    "is_child_order": order.is_child_order,
                    "is_linked_child_group": order.is_linked_child_group,
                }
            )
            repository.update_order(order.id, **payload)

        # Apply explicit moves against the immutable editor-opening sequence. This
        # prevents shifts caused by an earlier move from being mistaken for another
        # user request while iterating through the remaining rows.
        for row in edited_rows:
            order_id = row.get("ID")
            requested = _parse_priority(row.get("Приоритет"))
            if (
                order_id is not None
                and requested is not None
                and requested != original_priorities.get(int(order_id))
            ):
                repository.move_order(int(order_id), requested)

        if hasattr(repository, "normalize_priorities"):
            repository.normalize_priorities()
        # The planner must start only after all editor writes are durably committed.
        session.commit()
    except Exception:
        if hasattr(session, "rollback"):
            session.rollback()
        raise
    if hasattr(session, "expire_all"):
        session.expire_all()
    _clear_route_capacity_cache()
    recalculate_after_save(session)
    _clear_orders_page_state()
    st.rerun()


def _row_to_order_payload(
    row: dict[str, Any],
    route_by_name: dict[str, Route],
    *,
    original_status: str | None = None,
) -> dict[str, Any]:
    status = str(row["Статус"])
    return {
        "order_number": str(row["Номер"]).strip(),
        "client_name": str(row["Клиент"]).strip(),
        "product_name": str(row["Продукция"]).strip(),
        "quantity": float(row["Тираж"]),
        "shipment_date": normalize_editor_date(_scheduling_value(row, "Заданная дата отгрузки", "Срок отгрузки")),
        "planning_mode": row.get("Режим планирования") or PLANNING_MODE_SHIPMENT,
        "fixed_start_date": (
            normalize_editor_date(_scheduling_value(row, "Заданная дата запуска", "Фиксированная дата запуска"))
            if row.get("Режим планирования") == PLANNING_MODE_START
            else None
        ),
        "child_group_key": row.get("Группа") or None,
        "is_linked_child_group": bool(row.get("Связанные заказы")),
        "route_id": route_by_name[str(row["Маршрут"])].id,
        "status": status,
    }


def _row_changed(row: dict[str, Any], order: Order) -> bool:
    route_name = order.route.name if order.route else None
    return any(
        [
            str(row.get("Номер") or "").strip() != order.order_number,
            str(row.get("Клиент") or "").strip() != order.client_name,
            str(row.get("Продукция") or "").strip() != order.product_name,
            _parse_quantity(row.get("Тираж")) != float(order.quantity),
            normalize_editor_date(_scheduling_value(row, "Заданная дата отгрузки", "Срок отгрузки")) != order.shipment_date,
            normalize_editor_date(_scheduling_value(row, "Заданная дата запуска", "Фиксированная дата запуска"))
            != order.fixed_start_date,
            row.get("Режим планирования") != order.planning_mode,
            row.get("Маршрут") != route_name,
            row.get("Статус") != order.status,
            _parse_priority(row.get("Приоритет")) != order.priority,
        ]
    )


def _is_blank_draft_row(row: dict[str, Any]) -> bool:
    return not any(
        row.get(column)
        for column in ["Номер", "Клиент", "Продукция", "Заданная дата запуска", "Заданная дата отгрузки", "Маршрут"]
    )


def _scheduling_value(row: dict[str, Any], current: str, legacy: str) -> Any:
    """Read current table keys while accepting drafts created before the rename."""
    return row[current] if current in row else row.get(legacy)


def _parse_quantity(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_editor_date(value: Any) -> date | None:
    """Convert values emitted by Streamlit/pandas into a plain database date."""
    if value is None:
        return None
    try:
        if value != value:  # NaN / pandas.NaT
            return None
    except (TypeError, ValueError):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    # pandas.Timestamp and compatible scalar types expose this method.
    to_python = getattr(value, "to_pydatetime", None)
    if callable(to_python):
        try:
            converted = to_python()
            if isinstance(converted, datetime):
                return converted.date()
            return converted if isinstance(converted, date) else None
        except (TypeError, ValueError, OverflowError):
            return None
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except (TypeError, ValueError):
            return None
    return None


def _row_label(row: dict[str, Any]) -> str:
    order_id = row.get("ID")
    number = str(row.get("Номер") or "без номера").strip()
    return (
        f"Заказ ID {order_id} / № {number}"
        if order_id is not None
        else f"Новый заказ / № {number}"
    )


def _parse_priority(value: Any) -> int | None:
    try:
        parsed = int(value)
        return parsed if parsed >= 1 and float(value) == parsed else None
    except (TypeError, ValueError):
        return None


def _clear_orders_page_state(*, close_form: bool = False) -> None:
    """Discard DB-dependent widget snapshots before the next Streamlit run."""
    _clear_route_capacity_cache()
    st.session_state.pop(ORDER_EDITOR_KEY, None)
    st.session_state.pop(_ORDER_EDITOR_SIGNATURE_SESSION_KEY, None)
    st.session_state[SELECTED_ORDER_SESSION_KEY] = None
    if close_form:
        st.session_state[DRAFT_ORDER_SESSION_KEY] = False


ROUTE_CAPACITY_RESULT_SESSION_KEY = "orders_route_capacity_result"
ROUTE_CAPACITY_SLOTS_SESSION_KEY = "orders_route_capacity_slots"


def _planning_data_version(session) -> tuple[int | None, int, int, int, int]:
    """Return a cache version that changes when planning inputs or runs change."""
    try:
        latest_run_id = session.scalar(select(func.max(RecalculationRun.id)))
        order_version = session.execute(
            select(func.count(Order.id), func.max(Order.updated_at))
        ).one()
        route_version = session.execute(
            select(func.count(Route.id), func.max(Route.updated_at))
        ).one()
        operation_version = session.execute(
            select(func.count(RouteOperation.id), func.max(RouteOperation.updated_at))
        ).one()
        work_center_version = session.execute(
            select(func.count(WorkCenter.id), func.max(WorkCenter.updated_at))
        ).one()
    except AttributeError:
        latest_run_id = None
        order_version = route_version = operation_version = work_center_version = None
    return (
        latest_run_id,
        hash(order_version),
        hash(route_version),
        hash(operation_version),
        hash(work_center_version),
    )


def _route_capacity_params(
    route_id: int, period_start: date, period_end: date
) -> tuple[int, date, date]:
    """Return a stable key for the selected route and period."""
    return route_id, period_start, period_end


def _get_current_capacity_result(
    session, route_id: int, period_start: date, period_end: date
):
    """Return saved capacity only when it matches current route and period."""
    saved = st.session_state.get(ROUTE_CAPACITY_RESULT_SESSION_KEY)
    params = _route_capacity_params(route_id, period_start, period_end)
    version = _planning_data_version(session)
    if (
        isinstance(saved, dict)
        and saved.get("params") == params
        and saved.get("version") == version
    ):
        return saved.get("result")
    return None


def _get_current_slots(
    session, route_id: int, period_start: date, period_end: date, quantity: float
):
    """Return saved slots only when they match current route, period and quantity."""
    saved = st.session_state.get(ROUTE_CAPACITY_SLOTS_SESSION_KEY)
    params = (*_route_capacity_params(route_id, period_start, period_end), quantity)
    version = _planning_data_version(session)
    if (
        isinstance(saved, dict)
        and saved.get("params") == params
        and saved.get("version") == version
    ):
        return saved.get("slots")
    return None


def _clear_route_capacity_cache() -> None:
    """Clear saved capacity and shipment slots after planning data changes."""
    st.session_state.pop(ROUTE_CAPACITY_RESULT_SESSION_KEY, None)
    st.session_state.pop(ROUTE_CAPACITY_SLOTS_SESSION_KEY, None)


def _clear_route_capacity_slots() -> None:
    """Clear saved shipment slots after input changes or stale calculations."""
    st.session_state.pop(ROUTE_CAPACITY_SLOTS_SESSION_KEY, None)


def _render_route_capacity_check(session, routes: list[Route]) -> None:
    """Render preliminary capacity and shipment slot check without order creation."""
    st.subheader("Проверка доступного тиража и слотов отгрузки")
    st.caption(
        "Предварительный расчёт не создаёт заказ и не изменяет текущий производственный план. "
        "Нажмите «Рассчитать доступный тираж», чтобы выполнить проверку мощности."
    )

    today = date.today()
    default_start = today.replace(day=1)
    next_month = (default_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    default_end = next_month - timedelta(days=1)

    period_col, route_col, qty_col = st.columns(3)
    with period_col:
        period = st.date_input(
            "Период расчёта",
            value=(default_start, default_end),
            format="DD.MM.YYYY",
            key="orders_route_capacity_period",
        )
    with route_col:
        route_names = [route.name for route in routes]
        selected_route_name = st.selectbox(
            "Маршрут",
            options=route_names,
            index=0 if route_names else None,
            key="orders_route_capacity_route",
            disabled=not route_names,
        )
    with qty_col:
        quantity = st.number_input(
            "Желаемый тираж",
            min_value=0.0,
            step=100.0,
            value=0.0,
            key="orders_route_capacity_quantity",
        )

    period_start, period_end = _normalize_period_input(period)
    route_by_name = {route.name: route for route in routes}
    selected_route = (
        route_by_name.get(selected_route_name) if selected_route_name else None
    )

    capacity = None
    if selected_route is None or period_start is None or period_end is None:
        st.info("Выберите дату начала, дату окончания периода и маршрут.")
    else:
        capacity = _get_current_capacity_result(
            session, selected_route.id, period_start, period_end
        )
        if capacity is None:
            _clear_route_capacity_slots()

    if st.button(
        "Рассчитать доступный тираж",
        disabled=selected_route is None or period_start is None or period_end is None,
    ):
        if selected_route is None or period_start is None or period_end is None:
            st.error("Выберите период и маршрут.")
            return
        capacity = RouteCapacityService(session).calculate_route_capacity(
            selected_route.id, period_start, period_end
        )
        st.session_state[ROUTE_CAPACITY_RESULT_SESSION_KEY] = {
            "params": _route_capacity_params(
                selected_route.id, period_start, period_end
            ),
            "version": _planning_data_version(session),
            "result": capacity,
        }
        _clear_route_capacity_slots()

    if capacity is not None:
        if capacity.warnings:
            for warning in capacity.warnings:
                st.warning(warning)
        metric_col, bottleneck_col = st.columns(2)
        metric_col.metric(
            "Максимальный реально размещаемый тираж",
            f"{capacity.max_quantity:,.0f}".replace(",", " "),
        )
        bottleneck_col.metric(
            "Ограничивающий участок", capacity.bottleneck_work_center or "—"
        )
        if capacity.max_quantity == 0 and not capacity.warnings:
            st.info(
                "В выбранном периоде нет доступного тиража, который можно реально отгрузить по этому маршруту."
            )

    if st.button(
        "Показать свободные слоты отгрузки",
        disabled=selected_route is None or period_start is None or period_end is None,
    ):
        if quantity <= 0:
            st.error("Тираж должен быть больше 0")
            return
        if selected_route is None or period_start is None or period_end is None:
            st.error("Выберите период и маршрут.")
            return
        capacity = _get_current_capacity_result(
            session, selected_route.id, period_start, period_end
        )
        if capacity is None:
            st.error("Сначала рассчитайте доступный тираж.")
            return
        if quantity > capacity.max_quantity:
            st.error(
                "Введённый тираж превышает максимальный доступный тираж для выбранного маршрута и периода."
            )
            return
        slots = RouteCapacityService(
            session
        ).find_available_shipment_slots_for_capacity(
            capacity, quantity, period_start, period_end
        )
        st.session_state[ROUTE_CAPACITY_SLOTS_SESSION_KEY] = {
            "params": (
                *_route_capacity_params(selected_route.id, period_start, period_end),
                quantity,
            ),
            "version": _planning_data_version(session),
            "slots": slots,
        }
    elif (
        selected_route is not None
        and period_start is not None
        and period_end is not None
    ):
        slots = _get_current_slots(
            session, selected_route.id, period_start, period_end, quantity
        )
    else:
        slots = None

    if slots is not None:
        if not slots:
            st.info(
                "Для выбранного маршрута и тиража нет свободных слотов отгрузки в выбранном периоде."
            )
        else:
            st.write("Возможные даты отгрузки:")
            st.dataframe(
                [{"Дата отгрузки": slot.strftime("%d.%m.%Y")} for slot in slots],
                hide_index=True,
                use_container_width=True,
            )

    if capacity is not None and capacity.details:
        with st.expander("Детализация по операциям"):
            st.dataframe(
                [
                    {
                        "Операция": detail.sequence_number,
                        "Участок": detail.work_center_name,
                        "Доступно часов": round(detail.available_hours, 2),
                        "Занято часов": round(detail.occupied_hours, 2),
                        "Свободно часов": round(detail.free_hours, 2),
                        "Часов на 1000": round(detail.labor_hours_per_1000, 2),
                        "Доступный тираж": round(detail.available_quantity),
                        "Предупреждение": detail.warning or "",
                    }
                    for detail in capacity.details
                ],
                hide_index=True,
                use_container_width=True,
            )


def _normalize_period_input(period: Any) -> tuple[date | None, date | None]:
    """Normalize Streamlit date range value to start/end dates."""
    if (
        isinstance(period, tuple)
        and len(period) == 2
        and all(isinstance(item, date) for item in period)
    ):
        return period[0], period[1]
    if (
        isinstance(period, list)
        and len(period) == 2
        and all(isinstance(item, date) for item in period)
    ):
        return period[0], period[1]
    if isinstance(period, date):
        return period, period
    return None, None
