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
from app.services.draft_history_service import (
    redo_session, section_is_dirty, session_history, undo_session,
)

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
    if requested != current and dirty and current in {"Маршруты", "Участки"}:
        state["pending_navigation"] = True
        state["pending_navigation_target"] = requested
        state["requested_page"] = requested
        return current
    state["current_page"] = requested
    state["pending_navigation"] = False
    state.pop("pending_navigation_target", None)
    state["requested_page"] = requested
    return requested


def complete_pending_navigation(state) -> str:
    """Finish a confirmed transition and synchronise both sidebar groups."""
    target = state.get("pending_navigation_target", state.get("current_page", PAGES[0]))
    state["current_page"] = target
    state["requested_page"] = target
    state["pending_navigation"] = False
    state.pop("pending_navigation_target", None)
    state.pop("pending_navigation_commit", None)
    state.pop("pending_navigation_commit_completed", None)
    state.pop("pending_navigation_discard_completed", None)
    state.pop("navigation_probe_clean_completed", None)
    state.pop("navigation_probe_pending", None)
    state.pop("navigation_probe_section", None)
    state["nav_group_data"] = target if target in DATA_PAGES else None
    state["nav_group_plan"] = target if target in RESULT_PAGES else None
    return target


def begin_navigation_probe(state, requested: str, *, section: str, editor_keys: list[str]) -> str:
    """Keep the editable page mounted while its browser grids synchronize."""
    from app.ui.components.reference_table import request_reference_navigation_probe

    if state.get("navigation_probe_pending"):
        return state["reference_tables_flush_request"]
    state["navigation_probe_pending"] = True
    state["navigation_probe_section"] = section
    state["pending_navigation_target"] = requested
    state["requested_page"] = requested
    return request_reference_navigation_probe(
        state, section=section, editor_keys=editor_keys
    )


def resolve_navigation_probe(state, section: str) -> bool:
    """Resolve an acknowledged probe using the now-authoritative draft."""
    from app.ui.components.reference_table import clear_reference_save

    if not state.get("navigation_probe_pending"):
        return False
    clear_reference_save(state)
    state["navigation_probe_pending"] = False
    state.pop("navigation_probe_section", None)
    if section_is_dirty(state, section):
        state["pending_navigation"] = True
    else:
        state["pending_navigation"] = False
        state["navigation_probe_clean_completed"] = True
    return True


def render_navigation() -> None:
    """Render navigation and dispatch the selected MVP screen."""
    st.title("Production Planner MVP")
    st.caption("Локальный прототип планирования производства с SQLite")
    # Session state keys owned by Streamlit widgets must only be programmatically
    # changed before those widgets are instantiated in the current run.
    if (st.session_state.get("pending_navigation_commit_completed")
            or st.session_state.get("pending_navigation_discard_completed")
            or st.session_state.get("navigation_probe_clean_completed")):
        complete_pending_navigation(st.session_state)
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
    requested = (st.session_state.get("pending_navigation_target")
                 if (st.session_state.get("pending_navigation")
                     or st.session_state.get("navigation_probe_pending"))
                 else st.session_state.pop("navigation_requested", current))
    dirty = (section_is_dirty(st.session_state, "routes") if current == "Маршруты"
             else section_is_dirty(st.session_state, "work_centers") if current == "Участки"
             else False)
    if (requested != current and current in {"Маршруты", "Участки"}
            and not st.session_state.get("pending_navigation")
            and not st.session_state.get("navigation_probe_pending")):
        from app.ui.pages.routes_page import route_flush_editor_keys
        section = "routes" if current == "Маршруты" else "work_centers"
        editor_keys = (route_flush_editor_keys(
            st.session_state.get("routes_page_selected_route_id"), st.session_state
        ) if section == "routes" else ["work_centers_page_editor"])
        begin_navigation_probe(
            st.session_state, requested, section=section, editor_keys=editor_keys
        )
        page = current
    elif st.session_state.get("navigation_probe_pending"):
        page = current
    else:
        page = request_navigation(st.session_state, requested, dirty=dirty)
    if st.session_state.get("pending_navigation"):
        st.warning("Сохранить изменения?")
        yes, no = st.columns(2)
        if yes.button("Да"):
            from app.ui.components.reference_table import request_reference_save
            from app.ui.pages.routes_page import route_flush_editor_keys
            section = "routes" if current == "Маршруты" else "work_centers"
            editor_keys = (route_flush_editor_keys(st.session_state.get("routes_page_selected_route_id"))
                           if section == "routes" else ["work_centers_page_editor"])
            request_reference_save(
                st.session_state, section=section, editor_keys=editor_keys, navigation=True
            )
        if no.button("Нет"):
            from app.ui.components.reference_table import clear_reference_save
            clear_reference_save(st.session_state)
            section = "routes" if current == "Маршруты" else "work_centers"
            discard_keys = (
                ("routes_draft_rows", "route_operations_drafts_by_route_id",
                 "routes_page_route_editor", "routes_page_has_draft_route",
                 "routes_page_has_draft_operation", "routes_page_selected_route_id",
                 "routes_page_selected_operation_id")
                if section == "routes" else
                ("work_centers_draft_rows", "work_centers_page_editor",
                 "work_centers_page_has_draft_row", "work_centers_page_selected_id")
            )
            for key in discard_keys:
                st.session_state.pop(key, None)
            if section == "routes":
                for key in list(st.session_state):
                    if key.startswith("routes_page_operation_editor_"):
                        st.session_state.pop(key, None)
            # A discarded browser snapshot must not leave ACK/revision state
            # that could be mistaken for a later barrier response.
            editor_prefixes = (["routes_page_route_editor", "routes_page_operation_editor_"]
                               if section == "routes" else ["work_centers_page_editor"])
            for key in list(st.session_state):
                if "_component_" in key and any(
                    key.startswith(prefix) for prefix in editor_prefixes
                ):
                    st.session_state.pop(key, None)
            session_history(st.session_state).clear_section(section)
            if section == "routes":
                session_history(st.session_state).clear_section("operations")
            st.session_state[f"{section}_dirty"] = False
            st.session_state["pending_navigation_discard_completed"] = True
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
