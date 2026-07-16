"""Orders registry page."""

from datetime import date, timedelta
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
    "Номер",
    "Клиент",
    "Продукция",
    "Тираж",
    "Режим планирования",
    "Дата запуска",
    "Срок отгрузки",
    "Группа",
    "Связанная группа",
    "Маршрут",
    "Статус",
    "Конфликт",
]
DRAFT_ORDER_SESSION_KEY = "orders_page_show_new_order_form"
SELECTED_ORDER_SESSION_KEY = "orders_page_selected_order_id"
ORDER_EDITOR_KEY = "orders_page_editor"

ORDER_EEDITOR_COLUMNS = [
    "Выбран",
    "ID",
    "Номер",
    "Клиент",
    "Продукция",
    "Тираж",
    "Режим планирования",
    "Дата запуска",
    "Срок отгрузки",
    "Группа",
    "Связанная группа",
    "Маршрут",
    "Статус",
    "Конфликт",
]

DRAFT_ROW_SESSION_KEY = "orders_page_has_draft_row"
SELECTED_ORDER_SESSION_KEY = "orders_page_selected_order_id"


def render_orders_page() -> None:
    """Render an editable orders registry."""


def render_orders_page() -> None:
    """Render the orders registry with inline editing controls."""
    st.header("Реестр заказов")
    st.caption(
        "Редактируйте значения прямо в таблице. После нажатия кнопки «Сохранить изменения и пересчитать план» изменения сохраняются в реестре, затем запускается пересчёт производственного плана. Открытие страницы, выбор строки и редактирование ячеек без этой кнопки ничего не сохраняют и не пересчитывают."
    )

    with SessionLocal() as session:
        repository = OrdersRepository(session)
        routes = list(
            session.scalars(
                select(Route).where(Route.is_active.is_(True)).order_by(Route.name)
            ).all()
        )
        orders = list(
            session.scalars(
                select(Order)
                .options(selectinload(Order.route), selectinload(Order.conflicts))
                .order_by(Order.shipment_date, Order.id)
            ).all()
        )

        route_by_name = {route.name: route for route in routes}
        selected_order_id = st.session_state.get(SELECTED_ORDER_SESSION_KEY)
        if selected_order_id not in {order.id for order in orders}:
            selected_order_id = None
            st.session_state[SELECTED_ORDER_SESSION_KEY] = None

        add_col, delete_col = st.columns(2)
        with add_col:
            if st.button(
                "Добавить заказ", use_container_width=True, disabled=not routes
            ):
                st.session_state[DRAFT_ORDER_SESSION_KEY] = True
                st.rerun()
        with delete_col:
            if st.button(
                "Удалить заказ",
                use_container_width=True,
                disabled=selected_order_id is None,
            ):
                if selected_order_id is not None and repository.delete_order(
                    int(selected_order_id)
                ):
                    session.commit()
                    _clear_route_capacity_cache()
                    recalculate_after_save(session)
                    st.session_state[SELECTED_ORDER_SESSION_KEY] = None
                    st.rerun()
                st.error("Выбранный заказ не найден.")

        _render_route_capacity_check(session, routes)

        if not routes:
            st.warning(
                "Для добавления или редактирования заказа сначала создайте активный маршрут."
            )

        if bool(st.session_state.get(DRAFT_ORDER_SESSION_KEY)):
            _render_new_order_form(session, repository, routes, route_by_name)

        rows = build_order_editor_rows(
            orders, selected_order_id=selected_order_id, include_draft=False
        )
        if not rows:
            st.info(
                "Заказы пока не заведены. Нажмите «Добавить заказ» или загрузите demo-данные."
            )
            return

        _sync_order_editor_state(rows)

        edited_rows = st.data_editor(
            rows,
            key=ORDER_EDITOR_KEY,
            use_container_width=True,
            hide_index=True,
            disabled=["ID", "Конфликт", "Группа", "Связанная группа"],
            column_order=EDITOR_COLUMNS,
            num_rows="fixed",
            column_config={
                "Выбран": st.column_config.CheckboxColumn(
                    "Выбран", help="Отметьте один заказ для удаления."
                ),
                "ID": st.column_config.NumberColumn("ID", disabled=True),
                "Тираж": st.column_config.NumberColumn(
                    "Тираж", min_value=0.01, step=100.0
                ),
                "Срок отгрузки": st.column_config.DateColumn(
                    "Срок отгрузки", format="DD.MM.YYYY"
                ),
                "Маршрут": st.column_config.SelectboxColumn(
                    "Маршрут", options=list(route_by_name)
                ),
                "Статус": st.column_config.SelectboxColumn(
                    "Статус",
                    options=list(ORDER_STATUSES),
                    help=(
                        "Вручную можно сохранить только «Новый» или «Отменён». "
                        "«Запланирован» назначается системой после пересчёта."
                    ),
                ),
                "Режим планирования": st.column_config.SelectboxColumn("Режим планирования", options=list(PLANNING_MODES)),
                "Дата запуска": st.column_config.DateColumn("Дата запуска", format="DD.MM.YYYY"),
                "Группа": st.column_config.TextColumn("Группа", disabled=True),
                "Связанная группа": st.column_config.CheckboxColumn("Связанная группа", disabled=True),
                "Конфликт": st.column_config.CheckboxColumn("Конфликт", disabled=True),
            },
        )
        save_requested = st.button(
            "Сохранить изменения и пересчитать план",
            use_container_width=True,
            disabled=not routes,
        )
        _process_editor_changes(
            session,
            repository,
            orders,
            edited_rows,
            route_by_name,
            save_requested=save_requested,
        )


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
    state = st.session_state.setdefault("orders_page_new_order_form", dict(NEW_ORDER_DEFAULTS))
    for key, value in NEW_ORDER_DEFAULTS.items():
        state.setdefault(key, value)
    return state


def _render_new_order_form(session, repository: OrdersRepository, routes: list[Route], route_by_name: dict[str, Route]) -> None:
    st.subheader("Новый заказ")
    state = _new_order_state()
    c1, c2, c3 = st.columns(3)
    state["order_number"] = c1.text_input("Номер", value=state["order_number"], key="new_order_number")
    state["client_name"] = c2.text_input("Клиент", value=state["client_name"], key="new_client")
    state["product_name"] = c3.text_input("Продукция", value=state["product_name"], key="new_product")
    c4, c5, c6 = st.columns(3)
    state["quantity"] = c4.number_input("Тираж", min_value=0.0, step=100.0, value=float(state["quantity"] or 0.0), key="new_quantity")
    route_names = [route.name for route in routes]
    route_index = route_names.index(state["route_name"]) if state["route_name"] in route_names else None
    state["route_name"] = c5.selectbox("Маршрут", options=route_names, index=route_index, key="new_route")
    state["planning_mode"] = c6.radio("Режим планирования", options=list(PLANNING_MODES), index=list(PLANNING_MODES).index(state["planning_mode"]), horizontal=True, key="new_mode")
    if state["planning_mode"] == PLANNING_MODE_START:
        state["fixed_start_date"] = st.date_input("Дата запуска", value=state["fixed_start_date"], format="DD.MM.YYYY", key="new_fixed_start")
        state["shipment_date"] = state["fixed_start_date"]
    else:
        state["shipment_date"] = st.date_input("Срок отгрузки", value=state["shipment_date"], format="DD.MM.YYYY", key="new_ship_date")
        state["fixed_start_date"] = None
    state["split"] = st.checkbox("Разбить заказ на партии", value=bool(state["split"]), key="new_split")
    if state["split"]:
        s1, s2 = st.columns(2)
        state["child_size"] = s1.number_input("Размер одного дочернего заказа", min_value=0.0, step=100.0, value=float(state["child_size"] or 0.0), key="new_child_size")
        state["linked"] = s2.checkbox("Дочерние заказы связанные", value=bool(state["linked"]), key="new_linked")
    save_col, clear_col = st.columns(2)
    if save_col.button("Сохранить", use_container_width=True, key="new_save"):
        _save_new_order_form(session, repository, state, route_by_name)
    if clear_col.button("Очистить поле", use_container_width=True, key="new_clear"):
        st.session_state["orders_page_new_order_form"] = dict(NEW_ORDER_DEFAULTS)
        for key in ["new_order_number","new_client","new_product","new_quantity","new_route","new_mode","new_fixed_start","new_ship_date","new_split","new_child_size","new_linked"]:
            st.session_state.pop(key, None)
        st.rerun()


def _save_new_order_form(session, repository: OrdersRepository, state: dict[str, Any], route_by_name: dict[str, Route]) -> None:
    row = {"Номер": state["order_number"], "Клиент": state["client_name"], "Продукция": state["product_name"], "Тираж": state["quantity"], "Срок отгрузки": state["shipment_date"], "Маршрут": state["route_name"], "Статус": ORDER_STATUS_NEW}
    errors = validate_order_editor_row(row, route_names=set(route_by_name), existing_numbers={o.order_number: o.id for o in repository.list_orders()}, current_order_id=None)
    if state["planning_mode"] == PLANNING_MODE_START and not isinstance(state.get("fixed_start_date"), date):
        errors.append("Дата запуска обязательна.")
    if state.get("split"):
        child_size = _parse_quantity(state.get("child_size")) or 0
        if child_size <= 0:
            errors.append("Размер дочернего заказа должен быть больше нуля.")
        if child_size >= float(state.get("quantity") or 0):
            errors.append("Размер дочернего заказа должен быть меньше общего количества заказа")
    if errors:
        for error in errors: st.error(error)
        return
    payload = _row_to_order_payload(row, route_by_name)
    payload.update({"planning_mode": state["planning_mode"], "fixed_start_date": state.get("fixed_start_date")})
    if not state.get("split"):
        repository.create_order(**payload)
    else:
        total = float(state["quantity"]); size = float(state["child_size"]); base = str(state["order_number"]).strip()
        count = int((total + size - 1) // size)
        remaining = total
        for seq in range(1, count + 1):
            qty = size if remaining > size else remaining
            remaining -= qty
            child_payload = {**payload, "order_number": f"{base}.{seq}", "quantity": qty, "child_group_key": base, "child_sequence_number": seq, "is_child_order": True, "is_linked_child_group": bool(state.get("linked"))}
            repository.create_order(**child_payload)
    session.commit()
    _clear_route_capacity_cache()
    st.success("Заказ сохранён. Пересчёт плана не запускался.")
    st.session_state.pop(_ORDER_EDITOR_SIGNATURE_SESSION_KEY, None)


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
                "Номер": "",
                "Клиент": "",
                "Продукция": "",
                "Тираж": 0.0,
                "Режим планирования": PLANNING_MODE_SHIPMENT,
                "Дата запуска": None,
                "Срок отгрузки": None,
                "Группа": "",
                "Связанная группа": False,
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
    if row.get("Режим планирования") == PLANNING_MODE_START:
        if not isinstance(row.get("Дата запуска"), date):
            errors.append("Дата запуска обязательна.")
    elif not isinstance(row.get("Срок отгрузки"), date):
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
    existing_numbers = {order.order_number: order.id for order in orders}
    selected_ids = [
        int(row["ID"])
        for row in edited_rows
        if row.get("Выбран") and row.get("ID") is not None
    ]
    selected_id = selected_ids[-1] if selected_ids else None
    if selected_id != st.session_state.get(SELECTED_ORDER_SESSION_KEY):
        st.session_state[SELECTED_ORDER_SESSION_KEY] = selected_id
        st.rerun()

    if not save_requested:
        return

    saved_changes = False
    for row in edited_rows:
        order_id = row.get("ID")
        if order_id is None:
            if _is_blank_draft_row(row):
                st.warning(
                    "Новая строка ещё не заполнена: укажите обязательные поля, чтобы создать заказ."
                )
                return
            errors = validate_order_editor_row(
                row,
                route_names=set(route_by_name),
                existing_numbers=existing_numbers,
                current_order_id=None,
            )
            if errors:
                for error in errors:
                    st.error(error)
                return
            repository.create_order(**_row_to_order_payload(row, route_by_name))
            saved_changes = True
            st.session_state[DRAFT_ORDER_SESSION_KEY] = False
            continue

        order = original_by_id.get(int(order_id))
        if order is not None and _row_changed(row, order):
            errors = validate_order_editor_row(
                row,
                route_names=set(route_by_name),
                existing_numbers=existing_numbers,
                current_order_id=order.id,
                original_status=order.status,
            )
            if errors:
                for error in errors:
                    st.error(error)
                return
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
            saved_changes = True

    if saved_changes:
        session.commit()
        _clear_route_capacity_cache()
        recalculate_after_save(session)
        st.session_state.pop(_ORDER_EDITOR_SIGNATURE_SESSION_KEY, None)
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
        "shipment_date": row["Срок отгрузки"] or row.get("Дата запуска"),
        "planning_mode": row.get("Режим планирования") or PLANNING_MODE_SHIPMENT,
        "fixed_start_date": row.get("Дата запуска") if row.get("Режим планирования") == PLANNING_MODE_START else None,
        "child_group_key": row.get("Группа") or None,
        "is_linked_child_group": bool(row.get("Связанная группа")),
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
            row.get("Срок отгрузки") != order.shipment_date,
            row.get("Дата запуска") != (order.fixed_start_date or order.calculated_start_date),
            row.get("Режим планирования") != order.planning_mode,
            row.get("Маршрут") != route_name,
            row.get("Статус") != order.status,
        ]
    )


def _is_blank_draft_row(row: dict[str, Any]) -> bool:
    return not any(
        row.get(column)
        for column in ["Номер", "Клиент", "Продукция", "Срок отгрузки", "Маршрут"]
    )


def _parse_quantity(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
