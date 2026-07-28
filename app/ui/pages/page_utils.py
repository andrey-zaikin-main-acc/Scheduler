"""Shared Streamlit page utilities."""

from collections.abc import Sequence
from datetime import date

import streamlit as st
from sqlalchemy.orm import Session

from app.services.recalculation_service import RecalculationService


def recalculate_after_save(session: Session) -> None:
    """Recalculate the production plan after a persisted user change."""
    try:
        summary = RecalculationService(session).recalculate_plan()
        session.commit()
    except Exception:
        session.rollback()
        raise
    st.success(f"Изменения сохранены. План пересчитан: запланировано — {summary.planned_orders}, конфликтов — {summary.conflicts}.")


def commit_all_session_drafts() -> None:
    """Sidebar adapter for the same atomic action as the registry button."""
    from app.db.database import SessionLocal
    from app.db.models import Route
    from app.services.draft_commit_service import DraftBundle, DraftCommitService, success_flash
    from app.ui.pages.orders_page import _editor_row_to_draft
    from sqlalchemy import select
    with SessionLocal() as session:
        routes = list(session.scalars(select(Route)).all())
        route_by_name = {route.name: route for route in routes}
        rows = st.session_state.get("orders_draft_rows", [])
        bundle = DraftBundle(
            orders=[_editor_row_to_draft(row, route_by_name) for row in rows],
            pending_delete_ids=set(st.session_state.get("orders_pending_delete_ids", set())),
            routes=list(st.session_state.get("routes_draft_rows", [])),
            operations=list(st.session_state.get("route_operations_draft_rows", [])),
            work_centers=list(st.session_state.get("work_centers_draft_rows", [])),
        )
        result = DraftCommitService(session).commit(bundle)
        if result.ok:
            # Clear before rerun: Streamlit aborts execution at st.rerun().
            for key in list(st.session_state):
                if (key in {"orders_draft_rows", "routes_draft_rows", "route_operations_draft_rows",
                            "work_centers_draft_rows", "orders_page_editor", "orders_page_editor_signature",
                            "orders_route_capacity_result", "orders_route_capacity_slots"}
                        or key.startswith("order_mode_") or key.startswith("order_date_")):
                    st.session_state.pop(key, None)
            st.session_state["orders_pending_delete_ids"] = set()
            st.session_state["draft_flash"] = success_flash(result.summary)
            st.rerun()
        for error in result.errors:
            st.sidebar.error(error)


def normalize_date_range(value: object, default_start: date, default_end: date) -> tuple[date, date]:
    """Return a safe inclusive date range from a Streamlit date input value.

    ``st.date_input`` returns a tuple/list with two dates only after the user
    completes a range selection. During partial selection it can return a single
    date or a one-item sequence, so pages should fall back to their defaults
    instead of querying with an incomplete range. Reversed ranges are normalized
    to keep downstream filters valid.
    """
    if _is_date_pair(value):
        start_date, end_date = value
        if start_date <= end_date:
            return start_date, end_date
        return end_date, start_date
    return default_start, default_end


def _is_date_pair(value: object) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return False
    return len(value) == 2 and all(isinstance(item, date) for item in value)
