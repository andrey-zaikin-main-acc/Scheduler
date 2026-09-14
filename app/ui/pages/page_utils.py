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


def commit_all_session_drafts(*, sections: set[str] | None = None, message_target=None) -> bool:
    """Atomically save the requested screen drafts and recalculate exactly once."""
    from app.db.database import SessionLocal
    from app.db.models import Route
    from app.services.draft_commit_service import DraftBundle, DraftCommitService, success_flash
    from app.ui.pages.orders_page import _editor_row_to_draft
    from sqlalchemy import select
    with SessionLocal() as session:
        routes = list(session.scalars(select(Route)).all())
        route_by_name = {route.name: route for route in routes}
        rows = st.session_state.get("orders_draft_rows", [])
        operations_by_route = st.session_state.get("route_operations_drafts_by_route_id", {})
        bundle = DraftBundle(
            orders=[_editor_row_to_draft(row, route_by_name) for row in rows],
            pending_delete_ids=set(st.session_state.get("orders_pending_delete_ids", set())),
            routes=list(st.session_state.get("routes_draft_rows", [])),
            operations=[row for rows_for_route in operations_by_route.values() for row in rows_for_route],
            work_centers=list(st.session_state.get("work_centers_draft_rows", [])),
        )
        selected_sections = sections or {"orders", "routes", "work_centers"}
        service = DraftCommitService(session)
        if len(selected_sections) == 1 and not selected_sections.intersection({"orders"}):
            result = service.save_reference_section(bundle, next(iter(selected_sections)))
        else:
            result = service.commit_and_recalculate(bundle, sections=selected_sections)
        if result.ok:
            from app.services.draft_history_service import session_history
            history = session_history(st.session_state)
            for section in selected_sections:
                history.clear_section(section)
                st.session_state[f"{section}_dirty"] = False
                if section == "routes":
                    history.clear_section("operations")
                    st.session_state["routes_dirty"] = False
            # Clear before rerun: Streamlit aborts execution at st.rerun().
            section_keys = {
                "orders": {"orders_draft_rows", "orders_page_editor", "orders_page_editor_source_version",
                           "orders_page_editor_applied_version", "orders_page_editor_source_reason",
                           "orders_route_capacity_result", "orders_route_capacity_slots",
                           "orders_page_show_new_order_form", "orders_page_selected_order_id"},
                "routes": {"routes_draft_rows", "route_operations_drafts_by_route_id", "routes_page_route_editor",
                           "routes_page_has_draft_route", "routes_page_has_draft_operation",
                           "routes_page_selected_route_id", "routes_page_selected_operation_id"},
                "work_centers": {"work_centers_draft_rows", "work_centers_page_editor",
                                 "work_centers_page_has_draft_row", "work_centers_page_selected_id"},
            }
            old_order_source_version = int(st.session_state.get("orders_page_editor_source_version", 0))
            clear_keys = set().union(*(section_keys[name] for name in selected_sections))
            for key in list(st.session_state):
                if (key in clear_keys or ("routes" in selected_sections and key.startswith("routes_page_operation_editor_"))
                        or ("orders" in selected_sections and (key.startswith("order_mode_") or key.startswith("order_date_")))):
                    st.session_state.pop(key, None)
            if "orders" in selected_sections:
                st.session_state["orders_pending_delete_ids"] = set()
                # Never reuse the component's old source version after clearing
                # the session snapshot: the next DB load is authoritative.
                st.session_state["orders_page_editor_source_version"] = old_order_source_version + 1
                for key in ("orders_component_ack_revision", "orders_component_flush_ack",
                            "orders_component_flush_request", "orders_recalculation_requested"):
                    st.session_state.pop(key, None)
            st.session_state["draft_flash"] = (success_flash(result.summary) if result.summary else "Изменения сохранены без пересчёта плана.")
            if st.session_state.get("pending_navigation_commit"):
                st.session_state["pending_navigation_commit_completed"] = True
            st.rerun()
            return True
        target = message_target or st.sidebar
        for error in result.errors:
            target.error(error)
        return False


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
