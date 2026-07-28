"""Navigation shell for the MVP user interface."""

import streamlit as st

from app.ui.pages.common import render_bootstrap_controls
from app.ui.pages.conflicts_page import render_conflicts_page
from app.ui.pages.free_slots_page import render_free_slots_page
from app.ui.pages.gantt_page import render_gantt_page
from app.ui.pages.production_plan_page import render_production_plan_page
from app.ui.pages.orders_page import render_orders_page
from app.ui.pages.recalculation_results_page import render_recalculation_results_page
from app.ui.pages.routes_page import render_routes_page
from app.ui.pages.work_centers_page import render_work_centers_page


def render_navigation() -> None:
    """Render navigation and dispatch the selected MVP screen."""
    st.title("Production Planner MVP")
    st.caption("Локальный прототип планирования производства с SQLite")
    render_bootstrap_controls()
    if st.sidebar.button("Сохранить все изменения и пересчитать план", use_container_width=True):
        from app.ui.pages.page_utils import commit_all_session_drafts
        commit_all_session_drafts()

    page = st.sidebar.radio(
        "Раздел",
        [
            "Реестр заказов",
            "Маршруты",
            "Участки",
            "Производственный план",
            "Свободные слоты",
            "Диаграмма Ганта",
            "Конфликты",
            "Результаты пересчёта",
        ],
    )

    if page == "Реестр заказов":
        render_orders_page()
    elif page == "Маршруты":
        render_routes_page()
    elif page == "Участки":
        render_work_centers_page()
    elif page == "Производственный план":
        render_production_plan_page()
    elif page == "Свободные слоты":
        render_free_slots_page()
    elif page == "Диаграмма Ганта":
        render_gantt_page()
    elif page == "Конфликты":
        render_conflicts_page()
    elif page == "Результаты пересчёта":
        render_recalculation_results_page()
