"""Routes catalog page."""

import streamlit as st

from app.db.database import SessionLocal
from app.services.catalog_service import CatalogService


def render_routes_page() -> None:
    """Render routes, route operations and creation forms."""
    st.header("Технологические маршруты")
    with SessionLocal() as session:
        service = CatalogService(session)
        routes = service.list_routes()
        work_centers = service.list_work_centers()

    _render_routes_table(routes)
    _render_create_route_form()
    _render_add_operation_form(routes, work_centers)


def _render_routes_table(routes) -> None:
    rows = []
    for route in routes:
        if route.operations:
            for operation in route.operations:
                rows.append(
                    {
                        "Маршрут": route.name,
                        "Операция": operation.sequence_number,
                        "Участок": operation.work_center.name if operation.work_center else operation.work_center_id,
                        "Трудоёмкость / 1000": round(operation.labor_hours_per_1000, 2),
                        "Передаточная партия": operation.min_transfer_quantity_to_next,
                        "Активен": route.is_active,
                    }
                )
        else:
            rows.append(
                {
                    "Маршрут": route.name,
                    "Операция": None,
                    "Участок": None,
                    "Трудоёмкость / 1000": None,
                    "Передаточная партия": None,
                    "Активен": route.is_active,
                }
            )
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("Маршруты пока не созданы.")


def _render_create_route_form() -> None:
    st.subheader("Добавить маршрут")
    with st.form("create_route"):
        name = st.text_input("Название маршрута")
        description = st.text_area("Описание", height=80)
        is_active = st.checkbox("Активен", value=True, key="route_is_active")
        submitted = st.form_submit_button("Создать маршрут")

    if submitted:
        with SessionLocal() as session:
            try:
                CatalogService(session).create_route(name=name, description=description, is_active=is_active)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.success("Маршрут создан.")
                st.rerun()


def _render_add_operation_form(routes, work_centers) -> None:
    st.subheader("Добавить операцию маршрута")
    if not routes or not work_centers:
        st.info("Для добавления операции нужны хотя бы один маршрут и один участок.")
        return

    route_by_name = {route.name: route for route in routes}
    center_by_name = {work_center.name: work_center for work_center in work_centers}

    with st.form("add_route_operation"):
        route_name = st.selectbox("Маршрут", list(route_by_name))
        work_center_name = st.selectbox("Участок", list(center_by_name))
        sequence_number = st.number_input("Порядковый номер", min_value=1, value=1, step=1)
        labor_hours = st.number_input("Трудоёмкость часов / 1000 шт.", min_value=0.01, value=1.0, step=0.5)
        use_transfer = st.checkbox("Задать передаточную партию к следующей операции")
        transfer_quantity = st.number_input("Передаточная партия", min_value=0.01, value=1000.0, step=100.0)
        submitted = st.form_submit_button("Добавить операцию")

    if submitted:
        transfer = float(transfer_quantity) if use_transfer else None
        with SessionLocal() as session:
            try:
                CatalogService(session).add_route_operation(
                    route_id=route_by_name[route_name].id,
                    work_center_id=center_by_name[work_center_name].id,
                    sequence_number=int(sequence_number),
                    labor_hours_per_1000=float(labor_hours),
                    min_transfer_quantity_to_next=transfer,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.success("Операция добавлена. При необходимости запустите пересчёт плана.")
                st.rerun()
