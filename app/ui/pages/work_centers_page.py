"""Work centers catalog page."""

import streamlit as st

from app.db.database import SessionLocal
from app.services.catalog_service import CatalogService


def render_work_centers_page() -> None:
    """Render work centers list and creation form."""
    st.header("Производственные участки")
    with SessionLocal() as session:
        service = CatalogService(session)
        work_centers = service.list_work_centers()

    rows = [
        {
            "ID": work_center.id,
            "Название": work_center.name,
            "Доступно часов/день": round(work_center.available_hours_per_day, 2),
            "Активен": work_center.is_active,
        }
        for work_center in work_centers
    ]
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("Производственные участки пока не созданы.")

    st.subheader("Добавить участок")
    with st.form("create_work_center"):
        name = st.text_input("Название участка")
        available_hours = st.number_input("Доступно часов в день", min_value=0.01, value=8.0, step=0.5)
        is_active = st.checkbox("Активен", value=True)
        submitted = st.form_submit_button("Создать участок")

    if submitted:
        with SessionLocal() as session:
            try:
                CatalogService(session).create_work_center(
                    name=name,
                    available_hours_per_day=float(available_hours),
                    is_active=is_active,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.success("Участок создан. При необходимости запустите пересчёт плана.")
                st.rerun()
