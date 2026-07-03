"""Shared Streamlit page utilities."""

from collections.abc import Sequence
from datetime import date

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
