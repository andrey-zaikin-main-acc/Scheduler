"""Recalculation results page."""

import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.database import SessionLocal
from app.db.models import RecalculationRun
from app.ui.components.tables import plan_change_rows, recalculation_rows


def render_recalculation_results_page() -> None:
    """Render the latest recalculation runs and saved plan changes."""
    st.header("Результаты пересчёта")
    with SessionLocal() as session:
        runs = list(
            session.scalars(
                select(RecalculationRun).options(selectinload(RecalculationRun.changes)).order_by(RecalculationRun.id.desc())
            ).all()
        )
    rows = recalculation_rows(runs)
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
        latest = runs[0]
        st.subheader(f"Изменения последнего пересчёта #{latest.id}")
        changes = plan_change_rows(list(latest.changes))
        if changes:
            st.dataframe(changes, use_container_width=True, hide_index=True)
        else:
            st.info("Последний пересчёт не изменил плановые даты операций.")
    else:
        st.info("Пересчётов пока не было.")
