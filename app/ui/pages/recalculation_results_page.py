"""Recalculation results page."""

import streamlit as st
from sqlalchemy import select

from app.db.database import SessionLocal
from app.db.models import PlanChange, RecalculationRun
from app.ui.components.tables import plan_change_rows, recalculation_rows


def render_recalculation_results_page() -> None:
    """Render recalculation runs and changes for the latest run."""
    st.header("Результаты пересчёта")
    with SessionLocal() as session:
        runs = session.scalars(select(RecalculationRun).order_by(RecalculationRun.id.desc())).all()
        latest_run_id = runs[0].id if runs else None
        changes = (
            session.scalars(
                select(PlanChange)
                .where(PlanChange.recalculation_run_id == latest_run_id)
                .order_by(PlanChange.id)
            ).all()
            if latest_run_id is not None
            else []
        )

    rows = recalculation_rows(list(runs))
    if rows:
        st.subheader("Запуски пересчёта")
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("Пересчётов пока не было.")

    st.subheader("Изменения последнего пересчёта")
    change_rows = plan_change_rows(list(changes))
    if change_rows:
        st.dataframe(change_rows, use_container_width=True, hide_index=True)
    else:
        st.info("Для последнего пересчёта изменения не зафиксированы.")
