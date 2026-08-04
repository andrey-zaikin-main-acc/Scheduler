"""Technological routes directory page."""

from typing import Any

import streamlit as st

from app.db.database import SessionLocal
from app.db.models import Route, RouteOperation, WorkCenter
from app.repositories.routes_repository import RoutesRepository
from app.repositories.work_centers_repository import WorkCentersRepository
from app.ui.components.tables import route_operation_rows, route_rows
from app.ui.pages.page_utils import recalculate_after_save

ROUTE_COLUMNS = ["Выбран", "ID", "Название", "Описание", "Активен", "Операций"]
OPERATION_COLUMNS = [
    "Выбран",
    "ID",
    "№",
    "Участок",
    "Трудоёмкость на 1000",
    "Мин. передаточная партия",
    "Активна",
]
DRAFT_ROUTE_SESSION_KEY = "routes_page_has_draft_route"
SELECTED_ROUTE_SESSION_KEY = "routes_page_selected_route_id"
ROUTE_EDITOR_KEY = "routes_page_route_editor"
DRAFT_OPERATION_SESSION_KEY = "routes_page_has_draft_operation"
SELECTED_OPERATION_SESSION_KEY = "routes_page_selected_operation_id"
OPERATION_EDITOR_KEY = "routes_page_operation_editor"


def render_routes_page() -> None:
    """Render routes and route operations with inline editing controls."""
    st.header("Справочник маршрутов")
    if flash := st.session_state.pop("draft_flash", None):
        st.success(flash)
    st.caption(
        "Изменения хранятся в черновике до явного сохранения раздела."
    )

    with SessionLocal() as session:
        routes_repository = RoutesRepository(session)
        work_centers = list(WorkCentersRepository(session).list_work_centers())
        routes = list(routes_repository.list_routes_with_operations())
        selected_route_id = _normalize_selected_route(routes)

        save_section = st.button("Сохранить изменения", use_container_width=True)

        add_col, delete_col = st.columns(2)
        with add_col:
            if st.button("Добавить маршрут", use_container_width=True):
                st.session_state[DRAFT_ROUTE_SESSION_KEY] = True
                st.rerun()
        with delete_col:
            if st.button(
                "Удалить маршрут",
                use_container_width=True,
                disabled=selected_route_id is None,
            ):
                st.warning("Маршруты не удаляются физически. Снимите флаг «Активен» и сохраните раздел.")

        route_rows_data = st.session_state.get("routes_draft_rows") or build_route_editor_rows(
            routes, selected_id=selected_route_id,
            include_draft=bool(st.session_state.get(DRAFT_ROUTE_SESSION_KEY)),
        )
        if not route_rows_data:
            st.info("Маршруты пока не заведены. Нажмите «Добавить маршрут».")
            return
        edited_routes = st.data_editor(
            route_rows_data,
            key=ROUTE_EDITOR_KEY,
            use_container_width=True,
            hide_index=True,
            disabled=["ID", "Операций"],
            column_order=ROUTE_COLUMNS,
            num_rows="fixed",
            column_config={
                "Выбран": st.column_config.CheckboxColumn(
                    "Выбран", help="Отметьте один маршрут."
                ),
                "ID": st.column_config.NumberColumn("ID", disabled=True),
                "Активен": st.column_config.CheckboxColumn("Активен"),
                "Операций": st.column_config.NumberColumn("Операций", disabled=True),
            },
        )
        edited_routes, selected_route_id, selection_changed = reconcile_single_selection(
            route_rows_data, edited_routes, previous_id=selected_route_id
        )
        st.session_state["routes_draft_rows"] = edited_routes
        if selection_changed:
            st.session_state[SELECTED_ROUTE_SESSION_KEY] = selected_route_id
            st.session_state[SELECTED_OPERATION_SESSION_KEY] = None
            st.rerun()
        if save_section:
            from app.ui.pages.page_utils import commit_all_session_drafts
            commit_all_session_drafts(sections={"routes"}, message_target=st)

        selected_route_id = st.session_state.get(SELECTED_ROUTE_SESSION_KEY)
        selected_route = next(
            (route for route in routes if route.id == selected_route_id), None
        )
        if selected_route is not None:
            _render_operations_table(
                session, routes_repository, selected_route, work_centers
            )


def _render_operations_table(
    session, repository: RoutesRepository, route: Route, work_centers: list[WorkCenter]
) -> None:
    st.subheader(f"Операции маршрута: {route.name}")
    if not work_centers:
        st.warning("Сначала создайте хотя бы один участок")
        return
    selected_operation_id = _normalize_selected_operation(route.operations)
    add_col, delete_col = st.columns(2)
    with add_col:
        if st.button("Добавить операцию", use_container_width=True):
            st.session_state[DRAFT_OPERATION_SESSION_KEY] = True
            st.rerun()
    with delete_col:
        if st.button(
            "Удалить операцию",
            use_container_width=True,
            disabled=selected_operation_id is None,
        ):
            st.warning("Операции не удаляются физически. Снимите флаг «Активна» и сохраните раздел.")

    work_center_by_name = {item.name: item for item in work_centers if item.is_active}
    drafts_by_route = st.session_state.setdefault("route_operations_drafts_by_route_id", {})
    rows = drafts_by_route.get(route.id) or build_operation_editor_rows(
        route.operations, selected_id=selected_operation_id,
        include_draft=bool(st.session_state.get(DRAFT_OPERATION_SESSION_KEY)),
    )
    if not rows:
        st.warning("У маршрута нет операций. Нажмите «Добавить операцию».")
        return
    edited_rows = st.data_editor(
        rows,
        key=f"{OPERATION_EDITOR_KEY}_{route.id}",
        use_container_width=True,
        hide_index=True,
        disabled=["ID"],
        column_order=OPERATION_COLUMNS,
        num_rows="fixed",
        column_config={
            "Выбран": st.column_config.CheckboxColumn(
                "Выбран", help="Отметьте одну операцию для удаления."
            ),
            "ID": st.column_config.NumberColumn("ID", disabled=True),
            "№": st.column_config.NumberColumn("№", min_value=1, step=1),
            "Участок": st.column_config.SelectboxColumn(
                "Участок", options=list(work_center_by_name)
            ),
            "Трудоёмкость на 1000": st.column_config.NumberColumn(
                "Трудоёмкость на 1000", min_value=0.01, step=0.5
            ),
            "Мин. передаточная партия": st.column_config.NumberColumn(
                "Мин. передаточная партия", min_value=0.0, step=100.0
            ),
        },
    )
    edited_rows, selected_operation_id, selection_changed = reconcile_single_selection(
        rows, edited_rows, previous_id=selected_operation_id
    )
    for row in edited_rows:
        row["_route_id"] = route.id
    drafts_by_route[route.id] = edited_rows
    if selection_changed:
        st.session_state[SELECTED_OPERATION_SESSION_KEY] = selected_operation_id
        st.rerun()


def reconcile_single_selection(
    previous: list[dict[str, Any]], edited: list[dict[str, Any]], *, previous_id: int | None
) -> tuple[list[dict[str, Any]], int | None, bool]:
    """Keep the last newly checked persisted row as the sole selection."""
    before = {row.get("ID") for row in previous if row.get("Выбран")}
    checked = [row.get("ID") for row in edited if row.get("Выбран") and row.get("ID") is not None]
    newly_checked = [item_id for item_id in checked if item_id not in before]
    selected_id = int((newly_checked or checked)[-1]) if checked else None
    for row in edited:
        row["Выбран"] = row.get("ID") == selected_id
    return edited, selected_id, selected_id != previous_id


def build_route_editor_rows(
    routes: list[Route], *, selected_id: int | None, include_draft: bool
) -> list[dict[str, Any]]:
    rows = [
        {"Выбран": route.id == selected_id, **row}
        for route, row in zip(routes, route_rows(routes), strict=True)
    ]
    if include_draft:
        rows.append(
            {
                "Выбран": False,
                "ID": None,
                "Название": "",
                "Описание": "",
                "Активен": True,
                "Операций": 0,
            }
        )
    return rows


def build_operation_editor_rows(
    operations: list[RouteOperation], *, selected_id: int | None, include_draft: bool
) -> list[dict[str, Any]]:
    rows = [
        {"Выбран": op.id == selected_id, **row}
        for op, row in zip(operations, route_operation_rows(operations), strict=True)
    ]
    if include_draft:
        rows.append(
            {
                "Выбран": False,
                "ID": None,
                "№": (max([op.sequence_number for op in operations], default=0) + 1),
                "Участок": None,
                "Трудоёмкость на 1000": 0.0,
                "Мин. передаточная партия": 0.0,
                "Активна": True,
            }
        )
    return rows


def validate_route_row(
    row: dict[str, Any], *, existing_names: dict[str, int], current_id: int | None
) -> list[str]:
    errors = []
    name = str(row.get("Название") or "").strip()
    if not name:
        errors.append("Название маршрута обязательно.")
    duplicate_id = existing_names.get(name)
    if duplicate_id is not None and duplicate_id != current_id:
        errors.append("Маршрут с таким названием уже существует.")
    if not isinstance(row.get("Активен"), bool):
        errors.append("Активен должен быть bool.")
    return errors


def validate_operation_row(
    row: dict[str, Any],
    *,
    work_center_names: set[str],
    existing_numbers: dict[int, int],
    current_id: int | None,
) -> list[str]:
    errors = []
    number = _parse_int(row.get("№"))
    labor = _parse_float(row.get("Трудоёмкость на 1000"))
    transfer = _parse_float(row.get("Мин. передаточная партия"))
    wc = row.get("Участок")
    if number is None or number <= 0:
        errors.append("Номер операции обязателен и должен быть больше 0.")
    elif (
        existing_numbers.get(number) is not None
        and existing_numbers[number] != current_id
    ):
        errors.append("Номер операции должен быть уникален внутри маршрута.")
    if not wc or wc not in work_center_names:
        errors.append("Участок обязателен.")
    if labor is None or labor <= 0:
        errors.append("Трудоёмкость должна быть больше 0.")
    if transfer is None or transfer < 0:
        errors.append("Минимальная передаточная партия не должна быть меньше 0.")
    return errors


def _process_route_changes(
    session,
    repository: RoutesRepository,
    routes: list[Route],
    edited_rows: list[dict[str, Any]],
) -> None:
    original_by_id = {route.id: route for route in routes}
    existing_names = {route.name: route.id for route in routes}
    selected_ids = [
        int(row["ID"])
        for row in edited_rows
        if row.get("Выбран") and row.get("ID") is not None
    ]
    selected_id = selected_ids[-1] if selected_ids else None
    if selected_id != st.session_state.get(SELECTED_ROUTE_SESSION_KEY):
        st.session_state[SELECTED_ROUTE_SESSION_KEY] = selected_id
        st.session_state[SELECTED_OPERATION_SESSION_KEY] = None
        st.rerun()
    for row in edited_rows:
        route_id = row.get("ID")
        if route_id is None:
            if _is_blank_route_draft_row(row):
                st.warning(
                    "Новая строка ещё не заполнена: укажите название, чтобы создать маршрут."
                )
                return
            errors = validate_route_row(
                row, existing_names=existing_names, current_id=None
            )
            if errors:
                for error in errors:
                    st.error(error)
                return
            route = repository.create_route(**_route_row_to_payload(row))
            session.commit()
            recalculate_after_save(session)
            st.session_state[DRAFT_ROUTE_SESSION_KEY] = False
            st.session_state[SELECTED_ROUTE_SESSION_KEY] = route.id
            st.rerun()
        route = original_by_id.get(int(route_id))
        if route is not None and _route_row_changed(row, route):
            errors = validate_route_row(
                row, existing_names=existing_names, current_id=route.id
            )
            if errors:
                for error in errors:
                    st.error(error)
                return
            repository.update_route(route.id, **_route_row_to_payload(row))
            session.commit()
            recalculate_after_save(session)
            st.rerun()


def _process_operation_changes(
    session,
    repository: RoutesRepository,
    route: Route,
    edited_rows: list[dict[str, Any]],
    work_center_by_name: dict[str, WorkCenter],
) -> None:
    original_by_id = {op.id: op for op in route.operations}
    existing_numbers = {op.sequence_number: op.id for op in route.operations}
    selected_ids = [
        int(row["ID"])
        for row in edited_rows
        if row.get("Выбран") and row.get("ID") is not None
    ]
    selected_id = selected_ids[-1] if selected_ids else None
    if selected_id != st.session_state.get(SELECTED_OPERATION_SESSION_KEY):
        st.session_state[SELECTED_OPERATION_SESSION_KEY] = selected_id
        st.rerun()
    for row in edited_rows:
        operation_id = row.get("ID")
        if operation_id is None:
            if _is_blank_operation_draft_row(row):
                st.warning("Новая строка операции ещё не заполнена.")
                return
            errors = validate_operation_row(
                row,
                work_center_names=set(work_center_by_name),
                existing_numbers=existing_numbers,
                current_id=None,
            )
            if errors:
                for error in errors:
                    st.error(error)
                return
            repository.add_operation(
                route_id=route.id, **_operation_row_to_payload(row, work_center_by_name)
            )
            session.commit()
            recalculate_after_save(session)
            st.session_state[DRAFT_OPERATION_SESSION_KEY] = False
            st.rerun()
        operation = original_by_id.get(int(operation_id))
        if operation is not None and _operation_row_changed(row, operation):
            errors = validate_operation_row(
                row,
                work_center_names=set(work_center_by_name),
                existing_numbers=existing_numbers,
                current_id=operation.id,
            )
            if errors:
                for error in errors:
                    st.error(error)
                return
            repository.update_operation(
                operation.id, **_operation_row_to_payload(row, work_center_by_name)
            )
            session.commit()
            recalculate_after_save(session)
            st.rerun()


def _route_row_to_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(row["Название"]).strip(),
        "description": str(row.get("Описание") or "").strip() or None,
        "is_active": bool(row["Активен"]),
    }


def _operation_row_to_payload(
    row: dict[str, Any], work_center_by_name: dict[str, WorkCenter]
) -> dict[str, Any]:
    transfer = float(row.get("Мин. передаточная партия") or 0)
    return {
        "sequence_number": int(row["№"]),
        "work_center_id": work_center_by_name[str(row["Участок"])].id,
        "labor_hours_per_1000": float(row["Трудоёмкость на 1000"]),
        "min_transfer_quantity_to_next": transfer if transfer > 0 else None,
        "is_active": bool(row.get("Активна", True)),
    }


def _route_row_changed(row: dict[str, Any], route: Route) -> bool:
    return any(
        [
            str(row.get("Название") or "").strip() != route.name,
            str(row.get("Описание") or "").strip() != (route.description or ""),
            bool(row.get("Активен")) != route.is_active,
        ]
    )


def _operation_row_changed(row: dict[str, Any], operation: RouteOperation) -> bool:
    transfer = _parse_float(row.get("Мин. передаточная партия")) or 0.0
    return any(
        [
            _parse_int(row.get("№")) != operation.sequence_number,
            row.get("Участок")
            != (operation.work_center.name if operation.work_center else None),
            _parse_float(row.get("Трудоёмкость на 1000"))
            != float(operation.labor_hours_per_1000),
            (transfer if transfer > 0 else None)
            != operation.min_transfer_quantity_to_next,
            bool(row.get("Активна", True)) != operation.is_active,
        ]
    )


def _is_blank_route_draft_row(row: dict[str, Any]) -> bool:
    return (
        not str(row.get("Название") or "").strip()
        and not str(row.get("Описание") or "").strip()
    )


def _is_blank_operation_draft_row(row: dict[str, Any]) -> bool:
    return not row.get("Участок") and not _parse_float(row.get("Трудоёмкость на 1000"))


def _normalize_selected_route(routes: list[Route]) -> int | None:
    selected_id = st.session_state.get(SELECTED_ROUTE_SESSION_KEY)
    if selected_id not in {route.id for route in routes}:
        selected_id = None
        st.session_state[SELECTED_ROUTE_SESSION_KEY] = None
    return selected_id


def _normalize_selected_operation(operations: list[RouteOperation]) -> int | None:
    selected_id = st.session_state.get(SELECTED_OPERATION_SESSION_KEY)
    if selected_id not in {op.id for op in operations}:
        selected_id = None
        st.session_state[SELECTED_OPERATION_SESSION_KEY] = None
    return selected_id


def _parse_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
