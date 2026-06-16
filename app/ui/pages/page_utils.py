"""Shared Streamlit page utilities for data mutations."""

import streamlit as st
from sqlalchemy.orm import Session

from app.services.recalculation_service import RecalculationService


def recalculate_after_save(session: Session) -> None:
    """Recalculate the production plan after a persisted user change."""
    summary = RecalculationService(session).recalculate_plan()
    st.success(
        "Изменения сохранены, план пересчитан: "
        f"заказов запланировано — {summary.planned_orders}, "
        f"конфликтов — {summary.conflicts}, "
        f"операций — {summary.planned_operations}."
    )
