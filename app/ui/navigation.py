"""Navigation shell for the MVP user interface."""

import streamlit as st

from app.ui.pages.common import render_bootstrap_controls
from app.ui.pages.conflicts_page import render_conflicts_page
from app.ui.pages.orders_page import render_orders_page
from app.ui.pages.production_plan_page import render_production_plan_page
from app.ui.pages.recalculation_results_page import render_recalculation_results_page


def render_navigation() -> None:
    """Render navigation and dispatch the selected MVP screen."""
    st.title("Production Planner MVP")
    st.caption("Локальный прототип планирования производства с SQLite")
    render_bootstrap_controls()

    page = st.sidebar.radio(
        "Раздел",
        [
            "Реестр заказов",
            "Маршруты",
            "Участки",
            "Производственный план",
            "Диаграмма Ганта",
            "Свободные слоты",
            "Конфликты",
            "Результаты пересчёта",
        ],
    )

    if page == "Реестр заказов":
        render_orders_page()
    elif page == "Производственный план":
        render_production_plan_page()
    elif page == "Конфликты":
        render_conflicts_page()
    elif page == "Результаты пересчёта":
        render_recalculation_results_page()
    else:
        st.info(f"Раздел «{page}» будет реализован в следующих итерациях.")
        st.markdown(
            """
            **Доступно сейчас:** загрузка demo-данных, пересчёт плана, реестр заказов,
            производственный план, конфликты и результаты пересчёта.
            """
        )
