"""Orders registry page."""

import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.database import SessionLocal
from app.db.models import Order
from app.ui.components.tables import order_rows


def render_orders_page() -> None:
    """Render the orders registry."""
    st.header("Реестр заказов")
    with SessionLocal() as session:
        orders = session.scalars(select(Order).options(selectinload(Order.route)).order_by(Order.shipment_date, Order.id)).all()
    rows = order_rows(list(orders))
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("Заказы пока не заведены. Загрузите demo-данные или добавьте заказы позже.")
