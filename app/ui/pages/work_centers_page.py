"""Work centers directory page."""

from datetime import datetime, time
from typing import Any

import streamlit as st

from app.db.database import SessionLocal
from app.db.models import WorkCenter
from app.repositories.work_centers_repository import WorkCentersRepository
from app.ui.components.tables import work_center_rows
from app.ui.pages.page_utils import recalculate_after_save

EDITOR_COLUMNS = [
    "Выбран",
    "ID",
    "Название",
    "Доступные часы в день",
    "Время начала рабочего дня",
    "Активен",
]
DRAFT_ROW_SESSION_KEY = "work_centers_page_has_draft_row"
SELECTED_ROW_SESSION_KEY = "work_centers_page_selected_id"
EDITOR_KEY = "work_centers_page_editor"


def render_work_centers_page() -> None:
    """Render work centers with inline editing controls."""
    st.header("Справочник участков")
    st.caption(
        "Редактируйте участки прямо в таблице. После изменения план автоматически пересчитывается."
    )

    with SessionLocal() as session:
        repository = WorkCentersRepository(session)
        work_centers = list(repository.list_work_centers())
        selected_id = st.session_state.get(SELECTED_ROW_SESSION_KEY)
        if selected_id not in {item.id for item in work_centers}:
            selected_id = None
            st.session_state[SELECTED_ROW_SESSION_KEY] = None

        add_col, delete_col = st.columns(2)
        with add_col:
            if st.button("Добавить участок", use_container_width=True):
                st.session_state[DRAFT_ROW_SESSION_KEY] = True
                st.rerun()
        with delete_col:
            if st.button(
                "Удалить участок",
                use_container_width=True,
                disabled=selected_id is None,
            ):
                if selected_id is not None:
                    deleted = repository.delete_work_center(int(selected_id))
                    if deleted:
                        session.commit()
                        recalculate_after_save(session)
                        st.session_state[SELECTED_ROW_SESSION_KEY] = None
                        st.session_state[DRAFT_ROW_SESSION_KEY] = False
                        st.rerun()
                    st.error(
                        "Участок используется в маршрутах или плане и не может быть удалён."
                    )

        include_draft = bool(st.session_state.get(DRAFT_ROW_SESSION_KEY))
        rows = build_work_center_editor_rows(
            work_centers, selected_id=selected_id, include_draft=include_draft
        )
        if not rows:
            st.info("Участки пока не заведены. Нажмите «Добавить участок».")
            return

        edited_rows = st.data_editor(
            rows,
            key=EDITOR_KEY,
            use_container_width=True,
            hide_index=True,
            disabled=["ID"],
            column_order=EDITOR_COLUMNS,
            num_rows="fixed",
            column_config={
                "Выбран": st.column_config.CheckboxColumn(
                    "Выбран", help="Отметьте один участок для удаления."
                ),
                "ID": st.column_config.NumberColumn("ID", disabled=True),
                "Доступные часы в день": st.column_config.NumberColumn(
                    "Доступные часы в день", min_value=0.01, step=0.5
                ),
                "Активен": st.column_config.CheckboxColumn("Активен"),
            },
        )
        _process_editor_changes(session, repository, work_centers, edited_rows)


def build_work_center_editor_rows(
    work_centers: list[WorkCenter], *, selected_id: int | None, include_draft: bool
) -> list[dict[str, Any]]:
    rows = [
        {"Выбран": item.id == selected_id, **row}
        for item, row in zip(work_centers, work_center_rows(work_centers), strict=True)
    ]
    if include_draft:
        rows.append(
            {
                "Выбран": False,
                "ID": None,
                "Название": "",
                "Доступные часы в день": 0.0,
                "Время начала рабочего дня": "09:00",
                "Активен": True,
            }
        )
    return rows


def validate_work_center_row(
    row: dict[str, Any], *, existing_names: dict[str, int], current_id: int | None
) -> list[str]:
    errors: list[str] = []
    name = str(row.get("Название") or "").strip()
    hours = _parse_float(row.get("Доступные часы в день"))
    if not name:
        errors.append("Название участка обязательно.")
    duplicate_id = existing_names.get(name)
    if duplicate_id is not None and duplicate_id != current_id:
        errors.append("Участок с таким названием уже существует.")
    if hours is None or hours <= 0:
        errors.append("Доступные часы в день должны быть больше 0.")
    if _parse_time(row.get("Время начала рабочего дня")) is None:
        errors.append("Время начала рабочего дня должно быть в формате HH:MM.")
    if not isinstance(row.get("Активен"), bool):
        errors.append("Активность участка должна быть булевым значением.")
    return errors


def _process_editor_changes(
    session,
    repository: WorkCentersRepository,
    work_centers: list[WorkCenter],
    edited_rows: list[dict[str, Any]],
) -> None:
    original_by_id = {item.id: item for item in work_centers}
    existing_names = {item.name: item.id for item in work_centers}
    selected_ids = [
        int(row["ID"])
        for row in edited_rows
        if row.get("Выбран") and row.get("ID") is not None
    ]
    selected_id = selected_ids[-1] if selected_ids else None
    if selected_id != st.session_state.get(SELECTED_ROW_SESSION_KEY):
        st.session_state[SELECTED_ROW_SESSION_KEY] = selected_id
        st.rerun()

    for row in edited_rows:
        item_id = row.get("ID")
        if item_id is None:
            if _is_blank_draft_row(row):
                st.warning(
                    "Новая строка ещё не заполнена: укажите название и часы, чтобы создать участок."
                )
                return
            errors = validate_work_center_row(
                row, existing_names=existing_names, current_id=None
            )
            if errors:
                for error in errors:
                    st.error(error)
                return
            repository.create_work_center(**_row_to_payload(row))
            session.commit()
            recalculate_after_save(session)
            st.session_state[DRAFT_ROW_SESSION_KEY] = False
            st.rerun()
        item = original_by_id.get(int(item_id))
        if item is not None and _row_changed(row, item):
            errors = validate_work_center_row(
                row, existing_names=existing_names, current_id=item.id
            )
            if errors:
                for error in errors:
                    st.error(error)
                return
            repository.update_work_center(item.id, **_row_to_payload(row))
            session.commit()
            recalculate_after_save(session)
            st.rerun()


def _row_to_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(row["Название"]).strip(),
        "available_hours_per_day": float(row["Доступные часы в день"]),
        "workday_start_time": _parse_time(row["Время начала рабочего дня"])
        or time(hour=9),
        "is_active": bool(row["Активен"]),
    }


def _row_changed(row: dict[str, Any], item: WorkCenter) -> bool:
    return any(
        [
            str(row.get("Название") or "").strip() != item.name,
            _parse_float(row.get("Доступные часы в день"))
            != float(item.available_hours_per_day),
            _parse_time(row.get("Время начала рабочего дня"))
            != item.workday_start_time,
            bool(row.get("Активен")) != item.is_active,
        ]
    )


def _is_blank_draft_row(row: dict[str, Any]) -> bool:
    return not str(row.get("Название") or "").strip() and not _parse_float(
        row.get("Доступные часы в день")
    )


def _parse_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_time(value: Any) -> time | None:
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    if not isinstance(value, str):
        return None
    value = value.strip()
    try:
        parsed = datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return None
    if value != parsed.strftime("%H:%M"):
        return None
    return parsed
