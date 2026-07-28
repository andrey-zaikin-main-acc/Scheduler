"""Common Streamlit page helpers."""

import streamlit as st

from app.db.database import SessionLocal
from app.services.bootstrap_service import initialize_database, load_demo_data


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
            from app.ui.pages.page_utils import commit_all_session_drafts
            commit_all_session_drafts()
