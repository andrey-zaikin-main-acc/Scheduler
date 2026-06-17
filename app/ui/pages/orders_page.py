"""Orders registry page."""

from datetime import date
from typing import Any
from datetime import date, timedelta

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
    """Render the orders registry and order editing controls."""
    st.header("Реестр заказов")
    st.caption("Редактируйте значения прямо в таблице. После изменения заказ автоматически сохраняется, а план пересчитывается.")

    with SessionLocal() as session:
        repository = OrdersRepository(session)
        routes = list(session.scalars(select(Route).where(Route.is_active.is_(True)).order_by(Route.name)).all())
        orders = _load_orders(session)

        button_left, button_right = st.columns([1, 1])
        with button_left:
            if st.button("Добавить заказ"):
                st.session_state[DRAFT_ROW_SESSION_KEY] = True
                st.rerun()
        with button_right:
            selected_order_id = st.session_state.get(SELECTED_ORDER_SESSION_KEY)
            if st.button("Удалить заказ", disabled=selected_order_id is None):
                if selected_order_id is not None:
                    repository.delete_order(int(selected_order_id))
                    session.commit()
                    st.session_state[SELECTED_ORDER_SESSION_KEY] = None
                    recalculate_after_save(session)
                    st.rerun()

        if not routes:
            st.warning("Для создания или редактирования заказов сначала создайте активный маршрут.")
            return

        editor_rows = build_order_editor_rows(
            orders,
            selected_order_id=st.session_state.get(SELECTED_ORDER_SESSION_KEY),
            include_draft=bool(st.session_state.get(DRAFT_ROW_SESSION_KEY)),
        )
        edited_rows = _normalize_editor_rows(
            st.data_editor(
                editor_rows,
                key="orders_editor",
                column_order=ORDER_EDITOR_COLUMNS,
                column_config=_order_editor_column_config(routes),
                disabled=["ID", "Конфликт", "Дата запуска"],  # Calculated start date is produced by planner recalculation.
                hide_index=True,
                use_container_width=True,
                num_rows="fixed",
            )
        )

        _sync_selected_order(edited_rows)
        _persist_editor_changes(
            repository=repository,
            routes=routes,
            original_orders=orders,
            edited_rows=edited_rows,
        )


def _load_orders(session) -> list[Order]:
    return list(
        session.scalars(
            select(Order)
            .options(selectinload(Order.route), selectinload(Order.conflicts))
            .order_by(Order.shipment_date, Order.id)
        ).all()
    )


def _normalize_editor_rows(value: Any) -> list[dict[str, Any]]:
    if hasattr(value, "to_dict"):
        return value.to_dict("records")
    return list(value)


def build_order_editor_rows(
    orders: list[Order],
    *,
    selected_order_id: int | None = None,
    include_draft: bool = False,
) -> list[dict[str, Any]]:
    """Build rows for the editable orders table."""
    rows = [dict(row, Выбран=row["ID"] == selected_order_id) for row in order_rows(orders)]
    if include_draft:
        rows.append(_empty_draft_row())
    return rows


def validate_order_editor_row(
    row: dict[str, Any],
    *,
    route_names: set[str],
    existing_numbers: dict[str, int],
    current_order_id: int | None = None,
) -> list[str]:
    """Validate one edited table row before it is persisted."""
    errors: list[str] = []
    order_number = _clean_text(row.get("Номер"))
    client_name = _clean_text(row.get("Клиент"))
    product_name = _clean_text(row.get("Продукция"))
    quantity = _parse_quantity(row.get("Тираж"))
    shipment_date = _parse_date(row.get("Срок отгрузки"))
    route_name = _clean_text(row.get("Маршрут"))
    status = _clean_text(row.get("Статус"))

    if not order_number:
        errors.append("Номер заказа обязателен.")
    elif order_number in existing_numbers and existing_numbers[order_number] != current_order_id:
        errors.append("Заказ с таким номером уже существует.")
    if not client_name:
        errors.append("Клиент обязателен.")
    if not product_name:
        errors.append("Продукция обязательна.")
    if quantity is None or quantity <= 0:
        errors.append("Тираж должен быть больше 0.")
    if shipment_date is None:
        errors.append("Срок отгрузки обязателен.")
    if not route_name:
        errors.append("Маршрут обязателен.")
    elif route_name not in route_names:
        errors.append("Выбранный маршрут не найден или не активен.")
    if status not in ORDER_STATUSES:
        errors.append("Статус должен быть выбран из списка допустимых статусов.")
    return errors


def _persist_editor_changes(
    *,
    repository: OrdersRepository,
    routes: list[Route],
    original_orders: list[Order],
    edited_rows: list[dict[str, Any]],
) -> None:
    original_by_id = {order.id: order for order in original_orders}
    route_by_name = {route.name: route for route in routes}
    existing_numbers = {order.order_number: order.id for order in original_orders}

    for row in edited_rows:
        order_id = row.get("ID")
        if order_id is None:
            if _draft_row_is_empty(row):
                continue
            errors = validate_order_editor_row(
                row,
                route_names=set(route_by_name),
                existing_numbers=existing_numbers,
                current_order_id=None,
            )
            if errors:
                st.warning("Новая строка ещё не сохранена: " + " ".join(errors))
                return
            repository.create_order(**_row_to_order_payload(row, route_by_name))
            repository.session.commit()
            st.session_state[DRAFT_ROW_SESSION_KEY] = False
            recalculate_after_save(repository.session)
            st.rerun()

        order_id = int(order_id)
        original_order = original_by_id.get(order_id)
        if original_order is None or not _row_changed(row, original_order):
            continue
        errors = validate_order_editor_row(
            row,
            route_names=set(route_by_name),
            existing_numbers=existing_numbers,
            current_order_id=order_id,
        )
        if errors:
            st.error(f"Заказ {original_order.order_number} не сохранён: " + " ".join(errors))
            return
        repository.update_order(order_id, **_row_to_order_payload(row, route_by_name))
        repository.session.commit()
        recalculate_after_save(repository.session)
        st.rerun()


def _sync_selected_order(rows: list[dict[str, Any]]) -> None:
    selected_ids = [int(row["ID"]) for row in rows if row.get("ID") is not None and row.get("Выбран")]
    if len(selected_ids) > 1:
        st.warning("Выберите только один заказ для удаления.")
        st.session_state[SELECTED_ORDER_SESSION_KEY] = None
    else:
        st.session_state[SELECTED_ORDER_SESSION_KEY] = selected_ids[0] if selected_ids else None


def _row_to_order_payload(row: dict[str, Any], route_by_name: dict[str, Route]) -> dict[str, Any]:
    route_name = _clean_text(row.get("Маршрут"))
    return {
        "order_number": _clean_text(row.get("Номер")),
        "client_name": _clean_text(row.get("Клиент")),
        "product_name": _clean_text(row.get("Продукция")),
        "quantity": float(_parse_quantity(row.get("Тираж")) or 0),
        "shipment_date": _parse_date(row.get("Срок отгрузки")),
        "route_id": route_by_name[route_name].id,
        "status": _clean_text(row.get("Статус")),
    }


def _row_changed(row: dict[str, Any], order: Order) -> bool:
    return any(
        [
            _clean_text(row.get("Номер")) != order.order_number,
            _clean_text(row.get("Клиент")) != order.client_name,
            _clean_text(row.get("Продукция")) != order.product_name,
            _parse_quantity(row.get("Тираж")) != order.quantity,
            _parse_date(row.get("Срок отгрузки")) != order.shipment_date,
            _clean_text(row.get("Маршрут")) != (order.route.name if order.route else ""),
            _clean_text(row.get("Статус")) != order.status,
        ]
    )


def _empty_draft_row() -> dict[str, Any]:
    return {
        "Выбран": False,
        "ID": None,
        "Номер": "",
        "Клиент": "",
        "Продукция": "",
        "Тираж": None,
        "Срок отгрузки": None,
        "Маршрут": None,
        "Статус": ORDER_STATUS_NEW,
        "Дата запуска": None,
        "Конфликт": False,
    }


def _draft_row_is_empty(row: dict[str, Any]) -> bool:
    return not any(
        [
            _clean_text(row.get("Номер")),
            _clean_text(row.get("Клиент")),
            _clean_text(row.get("Продукция")),
            _parse_quantity(row.get("Тираж")) is not None,
            _parse_date(row.get("Срок отгрузки")) is not None,
            _clean_text(row.get("Маршрут")),
        ]
    )


def _order_editor_column_config(routes: list[Route]) -> dict[str, Any]:
    return {
        "Выбран": st.column_config.CheckboxColumn("Выбран", help="Выберите один заказ для удаления."),
        "ID": st.column_config.NumberColumn("ID", disabled=True),
        "Номер": st.column_config.TextColumn("Номер", required=True),
        "Клиент": st.column_config.TextColumn("Клиент", required=True),
        "Продукция": st.column_config.TextColumn("Продукция", required=True),
        "Тираж": st.column_config.NumberColumn("Тираж", min_value=0.01, step=100.0, required=True),
        "Срок отгрузки": st.column_config.DateColumn("Срок отгрузки", required=True),
        "Маршрут": st.column_config.SelectboxColumn("Маршрут", options=[route.name for route in routes], required=True),
        "Статус": st.column_config.SelectboxColumn("Статус", options=ORDER_STATUSES, required=True),
        "Дата запуска": st.column_config.DateColumn("Дата запуска", disabled=True),
        "Конфликт": st.column_config.CheckboxColumn("Конфликт", disabled=True),
    }


def _clean_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _parse_quantity(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None
        orders = list(
            session.scalars(
                select(Order)
                .options(selectinload(Order.route), selectinload(Order.conflicts))
                .order_by(Order.shipment_date, Order.id)
            ).all()
        )
        rows = order_rows(orders)
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("Заказы пока не заведены. Загрузите demo-данные или добавьте заказы.")

        if not routes:
            st.warning("Для создания заказа сначала создайте активный маршрут.")
            return

        with st.expander("Создать заказ", expanded=not orders):
            with st.form("create_order"):
                order_number = st.text_input("Номер заказа")
                client_name = st.text_input("Клиент")
                product_name = st.text_input("Продукция")
                quantity = st.number_input("Тираж", min_value=0.01, value=1000.0, step=100.0)
                shipment_date = st.date_input("Срок отгрузки", value=date.today() + timedelta(days=14))
                route_id = st.selectbox(
                    "Маршрут",
                    options=[route.id for route in routes],
                    format_func=lambda item_id: next(route.name for route in routes if route.id == item_id),
                )
                status = st.selectbox("Статус", ORDER_STATUSES, index=ORDER_STATUSES.index(ORDER_STATUS_NEW))
                submitted = st.form_submit_button("Создать и пересчитать")
            if submitted:
                errors = _validate_order_form(order_number, client_name, product_name, quantity, route_id)
                if repository.get_by_number(order_number.strip()) is not None:
                    errors.append("Заказ с таким номером уже существует.")
                if errors:
                    for error in errors:
                        st.error(error)
                else:
                    repository.create_order(
                        order_number=order_number.strip(),
                        client_name=client_name.strip(),
                        product_name=product_name.strip(),
                        quantity=float(quantity),
                        shipment_date=shipment_date,
                        route_id=int(route_id),
                        status=status,
                    )
                    session.commit()
                    recalculate_after_save(session)
                    st.rerun()

        if orders:
            with st.expander("Редактировать заказ"):
                selected_id = st.selectbox(
                    "Заказ",
                    options=[order.id for order in orders],
                    format_func=lambda item_id: next(order.order_number for order in orders if order.id == item_id),
                )
                selected = next(order for order in orders if order.id == selected_id)
                with st.form("edit_order"):
                    order_number = st.text_input("Номер заказа", value=selected.order_number)
                    client_name = st.text_input("Клиент", value=selected.client_name)
                    product_name = st.text_input("Продукция", value=selected.product_name)
                    quantity = st.number_input("Тираж", min_value=0.01, value=float(selected.quantity), step=100.0)
                    shipment_date = st.date_input("Срок отгрузки", value=selected.shipment_date)
                    route_ids = [route.id for route in routes]
                    route_id = st.selectbox(
                        "Маршрут",
                        options=route_ids,
                        index=route_ids.index(selected.route_id) if selected.route_id in route_ids else 0,
                        format_func=lambda item_id: next(route.name for route in routes if route.id == item_id),
                    )
                    status = st.selectbox(
                        "Статус",
                        ORDER_STATUSES,
                        index=ORDER_STATUSES.index(selected.status) if selected.status in ORDER_STATUSES else 0,
                    )
                    cancel = st.checkbox("Отменить заказ")
                    submitted = st.form_submit_button("Сохранить и пересчитать")
                if submitted:
                    errors = _validate_order_form(order_number, client_name, product_name, quantity, route_id)
                    duplicate = repository.get_by_number(order_number.strip())
                    if duplicate is not None and duplicate.id != selected.id:
                        errors.append("Заказ с таким номером уже существует.")
                    if errors:
                        for error in errors:
                            st.error(error)
                    else:
                        repository.update_order(
                            selected.id,
                            order_number=order_number.strip(),
                            client_name=client_name.strip(),
                            product_name=product_name.strip(),
                            quantity=float(quantity),
                            shipment_date=shipment_date,
                            route_id=int(route_id),
                            status=ORDER_STATUS_CANCELLED if cancel else status,
                        )
                        session.commit()
                        recalculate_after_save(session)
                        st.rerun()


def _validate_order_form(
    order_number: str,
    client_name: str,
    product_name: str,
    quantity: float,
    route_id: int | None,
) -> list[str]:
    errors: list[str] = []
    if not order_number.strip():
        errors.append("Номер заказа обязателен.")
    if not client_name.strip():
        errors.append("Клиент обязателен.")
    if not product_name.strip():
        errors.append("Продукция обязательна.")
    if quantity <= 0:
        errors.append("Тираж должен быть больше 0.")
    if route_id is None:
        errors.append("Маршрут обязателен.")
    return errors
