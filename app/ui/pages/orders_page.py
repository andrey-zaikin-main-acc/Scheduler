"""Orders registry page."""

from datetime import date
from typing import Any

import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.constants import (
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_CONFLICT,
    ORDER_STATUS_DONE,
    ORDER_STATUS_NEW,
    ORDER_STATUS_NOT_DONE,
    ORDER_STATUS_PLANNED,
)
from app.db.database import SessionLocal
from app.db.models import Order, Route
from app.repositories.orders_repository import OrdersRepository
from app.ui.components.tables import order_rows
from app.ui.pages.page_utils import recalculate_after_save

ORDER_STATUSES = [
    ORDER_STATUS_NEW,
    ORDER_STATUS_PLANNED,
    ORDER_STATUS_DONE,
    ORDER_STATUS_NOT_DONE,
    ORDER_STATUS_CONFLICT,
    ORDER_STATUS_CANCELLED,
]
EDITOR_COLUMNS = [
    "Выбран",
    "ID",
    "Номер",
    "Клиент",
    "Продукция",
    "Тираж",
    "Срок отгрузки",
    "Маршрут",
    "Статус",
    "Дата запуска",
    "Конфликт",
]
DRAFT_ORDER_SESSION_KEY = "orders_page_show_draft_row"
SELECTED_ORDER_SESSION_KEY = "orders_page_selected_order_id"
ORDER_EDITOR_KEY = "orders_page_editor"

ORDER_EDITOR_COLUMNS = [
    "Выбран",
    "ID",
    "Номер",
    "Клиент",
    "Продукция",
    "Тираж",
    "Срок отгрузки",
    "Маршрут",
    "Статус",
    "Дата запуска",
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
        "Редактируйте значения прямо в таблице. После изменения заказ автоматически сохраняется, а план пересчитывается."
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
                    recalculate_after_save(session)
                    st.session_state[SELECTED_ORDER_SESSION_KEY] = None
                    st.session_state[DRAFT_ORDER_SESSION_KEY] = False
                    st.rerun()
                st.error("Выбранный заказ не найден.")

        if not routes:
            st.warning(
                "Для добавления или редактирования заказа сначала создайте активный маршрут."
            )

        include_draft = bool(st.session_state.get(DRAFT_ORDER_SESSION_KEY))
        rows = build_order_editor_rows(
            orders, selected_order_id=selected_order_id, include_draft=include_draft
        )
        if not rows:
            st.info(
                "Заказы пока не заведены. Нажмите «Добавить заказ» или загрузите demo-данные."
            )
            return

        edited_rows = st.data_editor(
            rows,
            key=ORDER_EDITOR_KEY,
            use_container_width=True,
            hide_index=True,
            disabled=["ID", "Конфликт", "Дата запуска"],
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
                    "Статус", options=ORDER_STATUSES
                ),
                # Дата запуска рассчитывается планировщиком при пересчёте плана, поэтому ручное редактирование отключено.
                "Дата запуска": st.column_config.DateColumn(
                    "Дата запуска", disabled=True, format="DD.MM.YYYY"
                ),
                "Конфликт": st.column_config.CheckboxColumn("Конфликт", disabled=True),
            },
        )
        _process_editor_changes(session, repository, orders, edited_rows, route_by_name)


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
                "Срок отгрузки": None,
                "Маршрут": None,
                "Статус": ORDER_STATUS_NEW,
                "Дата запуска": None,
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
    if not isinstance(row.get("Срок отгрузки"), date):
        errors.append("Срок отгрузки обязателен.")
    if not route_name or route_name not in route_names:
        errors.append("Маршрут обязателен.")
    if status not in ORDER_STATUSES:
        errors.append("Статус обязателен.")
    return errors


def _process_editor_changes(
    session,
    repository: OrdersRepository,
    orders: list[Order],
    edited_rows: list[dict[str, Any]],
    route_by_name: dict[str, Route],
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
            session.commit()
            recalculate_after_save(session)
            st.session_state[DRAFT_ORDER_SESSION_KEY] = False
            st.rerun()

        order = original_by_id.get(int(order_id))
        if order is not None and _row_changed(row, order):
            errors = validate_order_editor_row(
                row,
                route_names=set(route_by_name),
                existing_numbers=existing_numbers,
                current_order_id=order.id,
            )
            if errors:
                for error in errors:
                    st.error(error)
                return
            repository.update_order(
                order.id, **_row_to_order_payload(row, route_by_name)
            )
            session.commit()
            recalculate_after_save(session)
            st.rerun()


def _row_to_order_payload(
    row: dict[str, Any], route_by_name: dict[str, Route]
) -> dict[str, Any]:
    return {
        "order_number": str(row["Номер"]).strip(),
        "client_name": str(row["Клиент"]).strip(),
        "product_name": str(row["Продукция"]).strip(),
        "quantity": float(row["Тираж"]),
        "shipment_date": row["Срок отгрузки"],
        "route_id": route_by_name[str(row["Маршрут"])].id,
        "status": str(row["Статус"]),
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
