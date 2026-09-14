"""Common Streamlit page helpers."""

from uuid import uuid4

import streamlit as st
from sqlalchemy import func, select

from app.db.database import SessionLocal
from app.db.models import Order, PlanningConflict, RecalculationRun
from app.services.bootstrap_service import initialize_database, load_demo_data


def _render_plan_status(host) -> None:
    """Show plan freshness: last recalculation, conflicts and stale hint.

    Read-only: it only reports existing database/session state and never changes
    planning logic.  «Свежесть» плана считается устаревшей, если данные заказов
    менялись после последнего пересчёта или есть несохранённые правки.
    """
    try:
        with SessionLocal() as session:
            last_run = session.scalars(
                select(RecalculationRun).order_by(RecalculationRun.id.desc()).limit(1)
            ).first()
            conflict_count = session.scalar(
                select(func.count()).select_from(PlanningConflict)
            ) or 0
            last_order_change = session.scalar(select(func.max(Order.updated_at)))
    except Exception:
        # Never let the status strip break the shell (e.g. empty DB on first run).
        return

    has_pending_edits = any(
        st.session_state.get(key)
        for key in (
            "orders_draft_rows_dirty",
            "routes_draft_rows",
            "route_operations_drafts_by_route_id",
            "work_centers_draft_rows",
            "orders_recalculation_requested",
        )
    )

    if last_run is None or last_run.finished_at is None:
        # No completed run yet: treat the plan as needing a recalculation.
        stale = True
    else:
        # Orders edited after the last completed run bump ``updated_at`` past
        # ``finished_at``; recalculation writes happen before the run finishes.
        stale = has_pending_edits or (
            last_order_change is not None
            and last_order_change > last_run.finished_at
        )

    if last_run is None:
        host.warning("План: ещё не рассчитан")
    elif stale:
        host.warning("План: требует пересчёта")
    else:
        host.success("План: актуален")

    if last_run is not None and last_run.finished_at is not None:
        host.caption(f"Последний пересчёт: {last_run.finished_at.strftime('%d.%m.%Y %H:%M')}")

    if conflict_count:
        host.caption(f"⚠️ Конфликтов планирования: {conflict_count}")
    else:
        host.caption("Конфликтов планирования: нет")


def render_bootstrap_controls(planning_host=None) -> None:
    """Render database bootstrap and recalculation controls.

    ``planning_host`` is an optional sidebar container reserved at the top of the
    shell so the plan status and the prominent primary «Пересчитать план» button
    appear above navigation.  When omitted, the controls fall back to the sidebar.
    """
    host = planning_host if planning_host is not None else st.sidebar

    with host:
        st.markdown("**Планирование**")
        _render_plan_status(host)
        requested = st.session_state.get("orders_recalculation_requested")
        flush_request = st.session_state.get("orders_component_flush_request")
        if requested and flush_request == st.session_state.get("orders_component_flush_ack"):
            st.session_state.pop("orders_recalculation_requested", None)
            st.session_state.pop("orders_component_flush_request", None)
            initialize_database()
            from app.ui.pages.page_utils import commit_all_session_drafts
            commit_all_session_drafts()
        if st.button("Пересчитать план", type="primary", use_container_width=True):
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

    with st.sidebar.expander("База данных", expanded=False):
        if st.button("Создать таблицы"):
            initialize_database()
            st.success("Таблицы SQLite созданы или уже существовали.")
        if st.button("Загрузить актуальные данные"):
            initialize_database()
            with SessionLocal() as session:
                load_demo_data(session)
            st.success("Актуальные seed-данные загружены.")
