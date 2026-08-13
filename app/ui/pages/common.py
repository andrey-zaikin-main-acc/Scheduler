"""Common Streamlit page helpers."""

from uuid import uuid4

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
        requested = st.session_state.get("orders_recalculation_requested")
        flush_request = st.session_state.get("orders_component_flush_request")
        if requested and flush_request == st.session_state.get("orders_component_flush_ack"):
            st.session_state.pop("orders_recalculation_requested", None)
            st.session_state.pop("orders_component_flush_request", None)
            initialize_database()
            from app.ui.pages.page_utils import commit_all_session_drafts
            commit_all_session_drafts()
        if st.button("Пересчитать план"):
            # On the orders screen this is a two-phase internal barrier.  The
            # browser grid first returns its newest snapshot; only the following
            # run is allowed to construct DraftBundle and validate it.
            if st.session_state.get("current_page") == "Реестр заказов" and "orders_draft_rows" in st.session_state:
                token = uuid4().hex
                st.session_state["orders_component_flush_request"] = token
                st.session_state["orders_recalculation_requested"] = True
            else:
                initialize_database()
                from app.ui.pages.page_utils import commit_all_session_drafts
                commit_all_session_drafts()
