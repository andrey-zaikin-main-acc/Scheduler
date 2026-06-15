"""Recalculation results page."""

import streamlit as st
from sqlalchemy import select

from app.db.database import SessionLocal
from app.db.models import RecalculationRun
from app.ui.components.tables import recalculation_rows


def render_recalculation_results_page() -> None:
    """Render the latest recalculation runs."""
    st.header("Результаты пересчёта")
    with SessionLocal() as session:
        runs = session.scalars(select(RecalculationRun).order_by(RecalculationRun.id.desc())).all()
    rows = recalculation_rows(list(runs))
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("Пересчётов пока не было.")
