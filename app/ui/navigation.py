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

# Sidebar navigation grouped by purpose: source data the user edits versus the
# planning results produced by a recalculation.  PAGES keeps the original flat
# order/membership so the rest of the shell and tests stay unchanged.
DATA_PAGES = ["Реестр заказов", "Маршруты", "Участки"]
RESULT_PAGES = [
    "Производственный план", "Свободные слоты", "Диаграмма Ганта",
    "Конфликты", "Результаты пересчёта",
]
PAGES = DATA_PAGES + RESULT_PAGES


def _on_nav_data() -> None:
    """Keep a single active page when the «Данные» group is used."""
    choice = st.session_state.get("nav_group_data")
    if choice:
        st.session_state["nav_group_plan"] = None
        st.session_state["navigation_requested"] = choice


def _on_nav_plan() -> None:
    """Keep a single active page when the «План и результаты» group is used."""
    choice = st.session_state.get("nav_group_plan")
    if choice:
        st.session_state["nav_group_data"] = None
        st.session_state["navigation_requested"] = choice


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
    current = st.session_state.setdefault("current_page", PAGES[0])

    # Reserve a slot at the very top of the sidebar for the plan status and the
    # primary «Пересчитать план» action.  It is filled later (after the page has
    # rendered) so the two-phase recalculation barrier keeps its exact timing.
    planning_slot = st.sidebar.container()

    # Two grouped radios ("Данные" / "План и результаты") that behave as one
    # selector: picking a page in either group deselects the other via callbacks.
    if "nav_group_data" not in st.session_state:
        st.session_state["nav_group_data"] = current if current in DATA_PAGES else None
    if "nav_group_plan" not in st.session_state:
        st.session_state["nav_group_plan"] = current if current in RESULT_PAGES else None
    st.sidebar.markdown("**Данные**")
    st.sidebar.radio(
        "Данные", DATA_PAGES, key="nav_group_data",
        on_change=_on_nav_data, label_visibility="collapsed",
    )
    st.sidebar.markdown("**План и результаты**")
    st.sidebar.radio(
        "План и результаты", RESULT_PAGES, key="nav_group_plan",
        on_change=_on_nav_plan, label_visibility="collapsed",
    )
    requested = st.session_state.pop("navigation_requested", current)
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

    # The page must first capture data_editor's value and record its action.
    render_history_controls()
    # Process save/recalculation only after the active page captured the latest
    # widget value into its screen draft.  The planning controls are drawn into
    # the reserved top slot so the prominent «Пересчитать план» action and plan
    # status appear above navigation without changing when this code executes.
    render_bootstrap_controls(planning_slot)


def render_history_controls() -> None:
    """Render the sole undo/redo controls against the up-to-date history."""
    if st.session_state.get("draft_history_replay_in_progress"):
        # The target can legitimately be an empty table after redo-delete, in
        # which case no draft_table instance exists to consume the event.
        event = st.session_state.pop("draft_visual_event", {})
        if event.get("animation") == "remove":
            st.info("Выбранные строки удалены из черновика.")
        st.session_state.pop("draft_history_replay_editor_key", None)
        st.session_state["draft_history_replay_in_progress"] = False
    history = session_history(st.session_state)
    st.sidebar.button(
        "Назад", key="draft_history_undo", disabled=not history.undo_stack,
        on_click=undo_session, args=(st.session_state,),
    )
    st.sidebar.button(
        "Вперёд", key="draft_history_redo", disabled=not history.redo_stack,
        on_click=redo_session, args=(st.session_state,),
    )
