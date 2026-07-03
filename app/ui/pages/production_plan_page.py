"""Production plan page."""

from datetime import date, timedelta

import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.database import SessionLocal
from app.db.models import Order, PlannedOperation, PlannedOperationDay, WorkCenter
from app.ui.components.tables import planned_operation_day_rows, planned_operation_rows
from app.ui.pages.page_utils import normalize_date_range


def render_production_plan_page() -> None:
    """Render planned operations and daily placements with filters."""
    st.header("Производственный план")
    default_start = date.today() - timedelta(days=30)
    default_end = date.today() + timedelta(days=60)

    with SessionLocal() as session:
        work_centers = list(session.scalars(select(WorkCenter).order_by(WorkCenter.name)).all())
        orders = list(session.scalars(select(Order).order_by(Order.order_number)).all())

        with st.expander("Фильтры", expanded=True):
            period = st.date_input("Период", value=(default_start, default_end))
            start_date, end_date = normalize_date_range(period, default_start, default_end)
            work_center_id = st.selectbox(
                "Участок",
                options=[None, *[item.id for item in work_centers]],
                format_func=lambda item_id: "Все" if item_id is None else next(item.name for item in work_centers if item.id == item_id),
            )
            order_id = st.selectbox(
                "Заказ",
                options=[None, *[item.id for item in orders]],
                format_func=lambda item_id: "Все" if item_id is None else next(item.order_number for item in orders if item.id == item_id),
            )
            statuses = sorted({order.status for order in orders})
            status = st.selectbox("Статус заказа", options=[None, *statuses], format_func=lambda value: "Все" if value is None else value)

        operation_query = (
            select(PlannedOperation)
            .join(Order)
            .options(
                selectinload(PlannedOperation.order),
                selectinload(PlannedOperation.work_center),
            )
            .where(PlannedOperation.planned_end_date >= start_date, PlannedOperation.planned_start_date <= end_date)
            .order_by(PlannedOperation.planned_start_date, PlannedOperation.order_id, PlannedOperation.sequence_number)
        )
        day_query = (
            select(PlannedOperationDay)
            .join(PlannedOperation)
            .join(Order)
            .options(selectinload(PlannedOperationDay.work_center))
            .where(PlannedOperationDay.date >= start_date, PlannedOperationDay.date <= end_date)
            .order_by(PlannedOperationDay.date, PlannedOperationDay.work_center_id)
        )

        if work_center_id is not None:
            operation_query = operation_query.where(PlannedOperation.work_center_id == work_center_id)
            day_query = day_query.where(PlannedOperationDay.work_center_id == work_center_id)
        if order_id is not None:
            operation_query = operation_query.where(PlannedOperation.order_id == order_id)
            day_query = day_query.where(PlannedOperation.order_id == order_id)
        if status is not None:
            operation_query = operation_query.where(Order.status == status)
            day_query = day_query.where(Order.status == status)

        planned_operations = session.scalars(operation_query).all()
        planned_days = session.scalars(day_query).all()

    st.subheader("Плановые операции")
    operation_rows = planned_operation_rows(list(planned_operations))
    if operation_rows:
        st.dataframe(operation_rows, use_container_width=True, hide_index=True)
    else:
        st.info("Плановых операций по выбранным фильтрам нет.")

    st.subheader("Дневные размещения")
    day_rows = planned_operation_day_rows(list(planned_days))
    if day_rows:
        st.dataframe(day_rows, use_container_width=True, hide_index=True)
    else:
        st.info("Дневных размещений по выбранным фильтрам нет.")
