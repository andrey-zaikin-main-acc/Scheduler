"""Navigation shell for the MVP user interface."""

import streamlit as st
from app.services.bootstrap_service import initialize_database

from app.ui.pages.common import render_bootstrap_controls
from app.ui.pages.conflicts_page import render_conflicts_page
from app.ui.pages.free_slots_page import render_free_slots_page
from app.ui.pages.gantt_page import render_gantt_page
from app.ui.pages.production_plan_page import render_production_plan_page
from app.ui.pages.orders_page import render_orders_page
from app.ui.pages.recalculation_results_page import render_recalculation_results_page
from app.ui.pages.routes_page import render_routes_page
from app.ui.pages.work_centers_page import render_work_centers_page
from app.services.draft_history_service import redo_session, session_history, undo_session

PAGES = [
    "Реестр заказов", "Маршруты", "Участки", "Производственный план",
    "Свободные слоты", "Диаграмма Ганта", "Конфликты", "Результаты пересчёта",
]


def request_navigation(state, requested: str, *, dirty: bool) -> str:
    """Pure transition used by the Streamlit shell and navigation tests."""
    current = state.setdefault("current_page", PAGES[0])
    state["requested_page"] = requested
    if requested != current and dirty and current in {"Маршруты", "Участки"}:
        state["pending_navigation"] = True
        return current
    state["current_page"] = requested
    state["pending_navigation"] = False
    return requested


def render_navigation() -> None:
    """Render navigation and dispatch the selected MVP screen."""
    # Schema creation/migrations must precede every page query, including a
    # first manual launch against an empty SQLite file.
    initialize_database()
    st.title("Production Planner MVP")
    st.caption("Локальный прототип планирования производства с SQLite")
    history = session_history(st.session_state)
    if st.sidebar.button("Назад", disabled=not history.undo_stack):
        undo_session(st.session_state); st.rerun()
    if st.sidebar.button("Вперёд", disabled=not history.redo_stack):
        redo_session(st.session_state); st.rerun()
    current = st.session_state.setdefault("current_page", PAGES[0])
    requested = st.sidebar.radio("Раздел", PAGES)
    dirty = bool(st.session_state.get("routes_draft_rows") or st.session_state.get("route_operations_drafts_by_route_id")) if current == "Маршруты" else bool(st.session_state.get("work_centers_draft_rows"))
    page = request_navigation(st.session_state, requested, dirty=dirty)
    if st.session_state.get("pending_navigation"):
        st.warning("Сохранить изменения?")
        yes, no = st.columns(2)
        if yes.button("Да"):
            from app.ui.pages.page_utils import commit_all_session_drafts
            section = "routes" if current == "Маршруты" else "work_centers"
            if commit_all_session_drafts(sections={section}, message_target=st):
                st.session_state.current_page = requested
        if no.button("Нет"):
            section = "routes" if current == "Маршруты" else "work_centers"
            for key in (("routes_draft_rows", "route_operations_drafts_by_route_id") if section == "routes" else ("work_centers_draft_rows",)):
                st.session_state.pop(key, None)
            session_history(st.session_state).clear_section(section)
            st.session_state.current_page = requested
            st.session_state.pending_navigation = False
            st.rerun()

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

    # Process save/recalculation only after the active page captured the latest
    # widget value into its screen draft.
    render_bootstrap_controls()
