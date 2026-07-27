"""Common Streamlit page helpers."""

import streamlit as st

from app.db.database import SessionLocal
from app.services.bootstrap_service import initialize_database, load_demo_data
from app.services.recalculation_service import RecalculationService


def render_bootstrap_controls() -> None:
    """Render database bootstrap and recalculation controls."""
    with st.sidebar.expander("База данных", expanded=True):
        if st.button("Создать таблицы"):
            initialize_database()
            st.success("Таблицы SQLite созданы или уже существовали.")
        if st.button("Загрузить актуальные данные"):
            initialize_database()
            with SessionLocal() as session:
                load_demo_data(session)
            st.success("Актуальные seed-данные загружены.")

    with st.sidebar.expander("Планирование", expanded=True):
        if st.button("Пересчитать план"):
            initialize_database()
            with SessionLocal() as session:
                summary = RecalculationService(session).recalculate_plan()
            # Every page is rendered again from the committed database instead
            # of reusing a data_editor/capacity snapshot from the previous run.
            for key in (
                "orders_page_editor",
                "orders_page_editor_signature",
                "orders_route_capacity_result",
                "orders_route_capacity_slots",
            ):
                st.session_state.pop(key, None)
            st.success(
                "План пересчитан: "
                f"заказов запланировано — {summary.planned_orders}, "
                f"конфликтов — {summary.conflicts}, "
                f"операций — {summary.planned_operations}."
            )
            st.rerun()
