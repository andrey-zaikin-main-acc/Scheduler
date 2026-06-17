"""Orders registry page."""

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


def render_orders_page() -> None:
    """Render the orders registry and order editing controls."""
    st.header("Реестр заказов")
    st.caption("Редактируйте значения прямо в таблице. После изменения заказ автоматически сохраняется, а план пересчитывается.")

    with SessionLocal() as session:
        repository = OrdersRepository(session)
        routes = list(session.scalars(select(Route).where(Route.is_active.is_(True)).order_by(Route.name)).all())
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
