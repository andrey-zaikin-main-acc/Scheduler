"""Technological routes directory page."""

import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.database import SessionLocal
from app.db.models import Route, RouteOperation
from app.repositories.routes_repository import RoutesRepository
from app.repositories.work_centers_repository import WorkCentersRepository
from app.ui.pages.page_utils import recalculate_after_save


def render_routes_page() -> None:
    """Render CRUD controls for routes and route operations."""
    st.header("Справочник маршрутов")
    with SessionLocal() as session:
        routes_repository = RoutesRepository(session)
        work_centers = list(WorkCentersRepository(session).list_work_centers())
        routes = list(
            session.scalars(
                select(Route).options(selectinload(Route.operations).selectinload(RouteOperation.work_center)).order_by(Route.name)
            ).all()
        )

        if routes:
            st.dataframe(
                [
                    {
                        "ID": route.id,
                        "Название": route.name,
                        "Описание": route.description,
                        "Активен": route.is_active,
                        "Операций": len(route.operations),
                    }
                    for route in routes
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Маршруты пока не заведены.")

        with st.expander("Создать маршрут", expanded=not routes):
            with st.form("create_route"):
                name = st.text_input("Название")
                description = st.text_area("Описание")
                submitted = st.form_submit_button("Создать")
            if submitted:
                if not name.strip():
                    st.error("Название маршрута обязательно.")
                else:
                    routes_repository.create_route(name=name.strip(), description=description.strip() or None)
                    session.commit()
                    st.success("Маршрут создан. Добавьте хотя бы одну операцию для планирования.")
                    st.rerun()

        if routes:
            selected_id = st.selectbox(
                "Маршрут для редактирования",
                options=[route.id for route in routes],
                format_func=lambda item_id: next(route.name for route in routes if route.id == item_id),
            )
            selected = next(route for route in routes if route.id == selected_id)

            with st.expander("Редактировать маршрут", expanded=True):
                with st.form("edit_route"):
                    name = st.text_input("Название", value=selected.name)
                    description = st.text_area("Описание", value=selected.description or "")
                    is_active = st.checkbox("Активен", value=selected.is_active)
                    submitted = st.form_submit_button("Сохранить и пересчитать")
                if submitted:
                    if not name.strip():
                        st.error("Название маршрута обязательно.")
                    else:
                        routes_repository.update_route(
                            selected.id,
                            name=name.strip(),
                            description=description.strip() or None,
                            is_active=is_active,
                        )
                        session.commit()
                        recalculate_after_save(session)
                        st.rerun()

            st.subheader("Операции маршрута")
            if selected.operations:
                st.dataframe(
                    [
                        {
                            "ID": operation.id,
                            "№": operation.sequence_number,
                            "Участок": operation.work_center.name if operation.work_center else operation.work_center_id,
                            "Трудоёмкость на 1000": operation.labor_hours_per_1000,
                            "Мин. передаточная партия": operation.min_transfer_quantity_to_next,
                        }
                        for operation in selected.operations
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.warning("У маршрута нет операций. Заказы с таким маршрутом попадут в конфликт до добавления операций.")

            if not work_centers:
                st.info("Сначала создайте хотя бы один участок.")
                return

            with st.expander("Добавить операцию"):
                with st.form("add_route_operation"):
                    sequence_number = st.number_input("Порядковый номер", min_value=1, value=len(selected.operations) + 1, step=1)
                    work_center_id = st.selectbox(
                        "Участок",
                        options=[item.id for item in work_centers],
                        format_func=lambda item_id: next(item.name for item in work_centers if item.id == item_id),
                    )
                    labor = st.number_input("Трудоёмкость на 1000 шт.", min_value=0.01, value=1.0, step=0.5)
                    transfer = st.number_input("Мин. передаточная партия к следующей операции", min_value=0.0, value=0.0, step=100.0)
                    submitted = st.form_submit_button("Добавить и пересчитать")
                if submitted:
                    routes_repository.add_operation(
                        route_id=selected.id,
                        sequence_number=int(sequence_number),
                        work_center_id=int(work_center_id),
                        labor_hours_per_1000=float(labor),
                        min_transfer_quantity_to_next=float(transfer) if transfer > 0 else None,
                    )
                    session.commit()
                    recalculate_after_save(session)
                    st.rerun()

            if selected.operations:
                with st.expander("Редактировать операцию"):
                    operation_id = st.selectbox(
                        "Операция",
                        options=[operation.id for operation in selected.operations],
                        format_func=lambda item_id: str(next(operation.sequence_number for operation in selected.operations if operation.id == item_id)),
                    )
                    operation = next(operation for operation in selected.operations if operation.id == operation_id)
                    with st.form("edit_route_operation"):
                        sequence_number = st.number_input("Порядковый номер", min_value=1, value=operation.sequence_number, step=1)
                        work_center_id = st.selectbox(
                            "Участок",
                            options=[item.id for item in work_centers],
                            index=[item.id for item in work_centers].index(operation.work_center_id),
                            format_func=lambda item_id: next(item.name for item in work_centers if item.id == item_id),
                        )
                        labor = st.number_input("Трудоёмкость на 1000 шт.", min_value=0.01, value=float(operation.labor_hours_per_1000), step=0.5)
                        transfer = st.number_input(
                            "Мин. передаточная партия к следующей операции",
                            min_value=0.0,
                            value=float(operation.min_transfer_quantity_to_next or 0.0),
                            step=100.0,
                        )
                        delete = st.checkbox("Удалить операцию")
                        submitted = st.form_submit_button("Сохранить и пересчитать")
                    if submitted:
                        if delete:
                            routes_repository.delete_operation(operation.id)
                        else:
                            routes_repository.update_operation(
                                operation.id,
                                sequence_number=int(sequence_number),
                                work_center_id=int(work_center_id),
                                labor_hours_per_1000=float(labor),
                                min_transfer_quantity_to_next=float(transfer) if transfer > 0 else None,
                            )
                        session.commit()
                        recalculate_after_save(session)
                        st.rerun()
