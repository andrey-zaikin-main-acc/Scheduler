"""Production plan page."""

import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.database import SessionLocal
from app.db.models import PlannedOperation, PlannedOperationDay
from app.ui.components.tables import planned_operation_day_rows, planned_operation_rows


def render_production_plan_page() -> None:
    """Render planned operations and daily placements."""
    st.header("Производственный план")
    with SessionLocal() as session:
        planned_operations = session.scalars(
            select(PlannedOperation)
            .options(
                selectinload(PlannedOperation.order),
                selectinload(PlannedOperation.work_center),
            )
            .order_by(PlannedOperation.planned_start_date, PlannedOperation.order_id, PlannedOperation.sequence_number)
        ).all()
        planned_days = session.scalars(
            select(PlannedOperationDay)
            .options(selectinload(PlannedOperationDay.work_center))
            .order_by(PlannedOperationDay.date, PlannedOperationDay.work_center_id)
        ).all()

    st.subheader("Плановые операции")
    operation_rows = planned_operation_rows(list(planned_operations))
    if operation_rows:
        st.dataframe(operation_rows, use_container_width=True, hide_index=True)
    else:
        st.info("Плановых операций пока нет. Запустите пересчёт плана.")

    st.subheader("Дневные размещения")
    day_rows = planned_operation_day_rows(list(planned_days))
    if day_rows:
        st.dataframe(day_rows, use_container_width=True, hide_index=True)
    else:
        st.info("Дневных размещений пока нет.")
