"""Orders registry page."""

from datetime import date

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
from app.services.catalog_service import CatalogService
from app.ui.components.tables import order_rows

ORDER_STATUSES = [
    ORDER_STATUS_NEW,
    ORDER_STATUS_PLANNED,
    ORDER_STATUS_DONE,
    ORDER_STATUS_NOT_DONE,
    ORDER_STATUS_CONFLICT,
    ORDER_STATUS_CANCELLED,
]


def render_orders_page() -> None:
    """Render the orders registry and creation form."""
    st.header("Реестр заказов")
    with SessionLocal() as session:
        orders = session.scalars(select(Order).options(selectinload(Order.route)).order_by(Order.shipment_date, Order.id)).all()
        routes = session.scalars(select(Route).where(Route.is_active.is_(True)).order_by(Route.name)).all()

    rows = order_rows(list(orders))
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("Заказы пока не заведены. Загрузите demo-данные или добавьте заказ.")

    _render_create_order_form(list(routes))


def _render_create_order_form(routes: list[Route]) -> None:
    st.subheader("Добавить заказ")
    if not routes:
        st.info("Для создания заказа нужен хотя бы один активный маршрут.")
        return

    route_by_name = {route.name: route for route in routes}
    with st.form("create_order"):
        order_number = st.text_input("Номер заказа")
        client_name = st.text_input("Клиент")
        product_name = st.text_input("Продукция")
        quantity = st.number_input("Тираж", min_value=0.01, value=1000.0, step=100.0)
        shipment_date = st.date_input("Срок отгрузки", value=date.today())
        route_name = st.selectbox("Маршрут", list(route_by_name))
        status = st.selectbox("Статус", ORDER_STATUSES, index=0)
        submitted = st.form_submit_button("Создать заказ")

    if submitted:
        with SessionLocal() as session:
            try:
                CatalogService(session).create_order(
                    order_number=order_number,
                    client_name=client_name,
                    product_name=product_name,
                    quantity=float(quantity),
                    shipment_date=shipment_date,
                    route_id=route_by_name[route_name].id,
                    status=status,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.success("Заказ создан. Запустите пересчёт плана.")
                st.rerun()
