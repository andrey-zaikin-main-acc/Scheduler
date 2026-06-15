"""Planning conflicts page."""

import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.database import SessionLocal
from app.db.models import PlanningConflict
from app.ui.components.tables import conflict_rows


def render_conflicts_page() -> None:
    """Render saved planning conflicts."""
    st.header("Конфликты планирования")
    with SessionLocal() as session:
        conflicts = session.scalars(
            select(PlanningConflict)
            .options(
                selectinload(PlanningConflict.order),
                selectinload(PlanningConflict.work_center),
            )
            .order_by(PlanningConflict.id)
        ).all()
    rows = conflict_rows(list(conflicts))
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.success("Конфликтов планирования нет.")
