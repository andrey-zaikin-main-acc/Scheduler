"""Gantt chart page."""

import streamlit as st

from app.db.database import SessionLocal
from app.services.gantt_service import GanttService
from app.ui.components.gantt import build_gantt_figure


GANTT_MODE_BY_ORDERS = "По заказам"
GANTT_MODE_BY_WORK_CENTERS = "По участкам"


def render_gantt_page() -> None:
    """Render Gantt chart in order and work-center modes."""
    st.header("Диаграмма Ганта")
    mode = st.radio("Режим", [GANTT_MODE_BY_ORDERS, GANTT_MODE_BY_WORK_CENTERS], horizontal=True)

    with SessionLocal() as session:
        service = GanttService(session)
        if mode == GANTT_MODE_BY_ORDERS:
            rows = service.get_gantt_by_orders()
            color_by = "work_center"
        else:
            rows = service.get_gantt_by_work_centers()
            color_by = "order"

    if not rows:
        st.info("Нет плановых операций для отображения. Загрузите актуальные данные и пересчитайте план.")
        return

    fig = build_gantt_figure(rows, color_by=color_by)
    st.plotly_chart(fig, use_container_width=True)
    with st.expander("Данные диаграммы"):
        st.dataframe(rows, use_container_width=True, hide_index=True)
