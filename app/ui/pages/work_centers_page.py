"""Work centers directory page."""

import streamlit as st

from app.db.database import SessionLocal
from app.repositories.work_centers_repository import WorkCentersRepository
from app.ui.pages.page_utils import recalculate_after_save


def render_work_centers_page() -> None:
    """Render CRUD controls for production work centers."""
    st.header("Справочник участков")
    with SessionLocal() as session:
        repository = WorkCentersRepository(session)
        work_centers = list(repository.list_work_centers())

        if work_centers:
            st.dataframe(
                [
                    {
                        "ID": item.id,
                        "Название": item.name,
                        "Доступные часы в день": item.available_hours_per_day,
                        "Активен": item.is_active,
                    }
                    for item in work_centers
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Участки пока не заведены.")

        with st.expander("Создать участок", expanded=not work_centers):
            with st.form("create_work_center"):
                name = st.text_input("Название")
                hours = st.number_input("Доступные часы в день", min_value=0.01, value=8.0, step=0.5)
                submitted = st.form_submit_button("Создать и пересчитать")
            if submitted:
                if not name.strip():
                    st.error("Название участка обязательно.")
                else:
                    repository.create_work_center(name=name.strip(), available_hours_per_day=float(hours))
                    session.commit()
                    recalculate_after_save(session)
                    st.rerun()

        if work_centers:
            with st.expander("Редактировать участок"):
                selected_id = st.selectbox(
                    "Участок",
                    options=[item.id for item in work_centers],
                    format_func=lambda item_id: next(item.name for item in work_centers if item.id == item_id),
                )
                selected = next(item for item in work_centers if item.id == selected_id)
                with st.form("edit_work_center"):
                    name = st.text_input("Название", value=selected.name)
                    hours = st.number_input(
                        "Доступные часы в день",
                        min_value=0.01,
                        value=float(selected.available_hours_per_day),
                        step=0.5,
                    )
                    is_active = st.checkbox("Активен", value=selected.is_active)
                    submitted = st.form_submit_button("Сохранить и пересчитать")
                if submitted:
                    if not name.strip():
                        st.error("Название участка обязательно.")
                    else:
                        repository.update_work_center(
                            selected.id,
                            name=name.strip(),
                            available_hours_per_day=float(hours),
                            is_active=is_active,
                        )
                        session.commit()
                        recalculate_after_save(session)
                        st.rerun()
