"""Common Streamlit page helpers."""

from uuid import uuid4

import streamlit as st
from sqlalchemy import func, select

from app.db import database
from app.db.database import SessionLocal
from app.db.models import Order, PlanningConflict, RecalculationRun
from app.services.bootstrap_service import initialize_database
from app.services.database_transfer_service import (
    DatabaseTransferError,
    choose_export_directory,
    choose_import_file,
    export_database,
    import_database,
    rollback_available,
    rollback_last_import,
    validate_transfer_file,
)
from app.services.draft_history_service import HISTORY_SESSION_KEY, section_is_dirty


_TRANSFER_ACTION_KEY = "database_transfer_action"
_TRANSFER_PROBE_KEY = "database_transfer_probe_pending"
_TRANSFER_SELECTED_FILE_KEY = "database_transfer_selected_file"
_TRANSFER_CONFIRM_ROLLBACK_KEY = "database_transfer_confirm_rollback"
_TRANSFER_AUTHOR_KEY = "database_transfer_author"
_TRANSFER_AUTHOR_WIDGET_KEY = "database_transfer_author_input"


def _has_unsaved_changes(state) -> bool:
    """Report every known draft that has not reached SQLite yet."""
    history = state.get(HISTORY_SESSION_KEY)
    return bool(
        getattr(history, "undo_stack", None)
        or section_is_dirty(state, "routes")
        or section_is_dirty(state, "work_centers")
        or state.get("orders_recalculation_requested")
        or state.get("reference_tables_save_requested")
    )


def _set_transfer_flash(level: str, message: str) -> None:
    st.session_state["database_transfer_flash"] = (level, message)


def _sync_transfer_author() -> None:
    """Copy the transient widget value into persistent application state."""
    st.session_state[_TRANSFER_AUTHOR_KEY] = st.session_state.get(
        _TRANSFER_AUTHOR_WIDGET_KEY, ""
    )


def _restore_transfer_author_widget() -> str:
    """Restore a recreated text widget and return the persistent author."""
    state = st.session_state
    if _TRANSFER_AUTHOR_KEY not in state:
        state[_TRANSFER_AUTHOR_KEY] = state.get(_TRANSFER_AUTHOR_WIDGET_KEY, "")
    if _TRANSFER_AUTHOR_WIDGET_KEY not in state:
        state[_TRANSFER_AUTHOR_WIDGET_KEY] = state[_TRANSFER_AUTHOR_KEY]
    return state[_TRANSFER_AUTHOR_KEY]


def _export_current_database(author: str) -> None:
    """Export the persisted SQLite snapshot without inspecting UI drafts."""
    try:
        directory = choose_export_directory()
        if directory is None:
            _set_transfer_flash("info", "Выгрузка отменена.")
        else:
            path = export_database(directory, author)
            _set_transfer_flash("success", f"Данные выгружены: {path.name}")
    except (DatabaseTransferError, OSError) as exc:
        _set_transfer_flash("error", str(exc))
    except Exception as exc:
        _set_transfer_flash("error", f"Операция с данными не выполнена: {exc}")


def _clear_transfer_probe() -> None:
    token = st.session_state.pop("database_transfer_probe_token", None)
    if st.session_state.get("orders_component_flush_request") == token:
        st.session_state.pop("orders_component_flush_request", None)
    for key in (
        _TRANSFER_PROBE_KEY,
        "database_transfer_probe_page",
        "database_transfer_probe_completed",
    ):
        st.session_state.pop(key, None)


def _start_transfer_probe(action: str) -> None:
    """Synchronize the visible browser grid before checking its dirty state."""
    state = st.session_state
    page = state.get("current_page")
    state[_TRANSFER_ACTION_KEY] = action
    state[_TRANSFER_PROBE_KEY] = True
    state["database_transfer_probe_page"] = page
    token = uuid4().hex
    state["database_transfer_probe_token"] = token
    if page == "Реестр заказов" and state.get("orders_draft_rows"):
        state["orders_component_flush_request"] = token
    elif page == "Маршруты":
        from app.ui.components.reference_table import request_reference_transfer_probe
        from app.ui.pages.routes_page import route_flush_editor_keys

        request_reference_transfer_probe(
            state,
            section="routes",
            editor_keys=route_flush_editor_keys(
                state.get("routes_page_selected_route_id"), state
            ),
        )
    elif page == "Участки":
        from app.ui.components.reference_table import request_reference_transfer_probe

        request_reference_transfer_probe(
            state,
            section="work_centers",
            editor_keys=["work_centers_page_editor"],
        )
    else:
        state["database_transfer_probe_completed"] = True
    st.rerun()


def _transfer_probe_ready() -> bool:
    if not st.session_state.get(_TRANSFER_PROBE_KEY):
        return False
    page = st.session_state.get("database_transfer_probe_page")
    if page == "Реестр заказов":
        if not st.session_state.get("orders_draft_rows"):
            return True
        token = st.session_state.get("database_transfer_probe_token")
        return st.session_state.get("orders_component_flush_ack") == token
    return bool(st.session_state.get("database_transfer_probe_completed"))


def _reset_ui_after_database_change(message: str) -> None:
    """Drop stale drafts and component revisions after replacing SQLite."""
    st.session_state.clear()
    st.session_state["database_transfer_flash"] = ("success", message)
    st.rerun()


def _perform_pending_transfer_action() -> None:
    if not _transfer_probe_ready():
        return
    action = st.session_state.get(_TRANSFER_ACTION_KEY)
    _clear_transfer_probe()
    if _has_unsaved_changes(st.session_state):
        st.session_state.pop(_TRANSFER_ACTION_KEY, None)
        _set_transfer_flash(
            "error",
            "Есть несохранённые изменения. Сначала сохраните их, затем повторите действие.",
        )
        return
    try:
        if action == "select_import":
            path = choose_import_file()
            if path is None:
                _set_transfer_flash("info", "Выбор файла отменён.")
            else:
                metadata = validate_transfer_file(path)
                st.session_state[_TRANSFER_SELECTED_FILE_KEY] = str(path)
                st.session_state["database_transfer_selected_metadata"] = metadata
        elif action == "rollback":
            st.session_state[_TRANSFER_CONFIRM_ROLLBACK_KEY] = True
        elif action == "confirm_import":
            selected = st.session_state.get(_TRANSFER_SELECTED_FILE_KEY)
            if not selected:
                raise DatabaseTransferError("Файл для загрузки больше не выбран.")
            import_database(
                selected,
                dispose_connections=database.engine.dispose,
                migrate_database=initialize_database,
            )
            _reset_ui_after_database_change(
                "Данные загружены. Предыдущее состояние доступно для отмены."
            )
        elif action == "confirm_rollback":
            rollback_last_import(
                dispose_connections=database.engine.dispose,
                migrate_database=initialize_database,
            )
            _reset_ui_after_database_change(
                "Последняя загрузка отменена; прежние данные восстановлены."
            )
    except (DatabaseTransferError, OSError) as exc:
        _set_transfer_flash("error", str(exc))
    except Exception as exc:
        _set_transfer_flash("error", f"Операция с данными не выполнена: {exc}")
    finally:
        st.session_state.pop(_TRANSFER_ACTION_KEY, None)


def _render_transfer_flash() -> None:
    flash = st.session_state.pop("database_transfer_flash", None)
    if not flash:
        return
    level, message = flash
    getattr(st, level if level in {"success", "error", "warning", "info"} else "info")(
        message
    )


def _render_database_transfer_controls() -> None:
    _perform_pending_transfer_action()
    _render_transfer_flash()

    author = _restore_transfer_author_widget()
    st.text_input(
        "Автор выгрузки",
        key=_TRANSFER_AUTHOR_WIDGET_KEY,
        placeholder="Например: Андрей Заикин",
        on_change=_sync_transfer_author,
    )
    if st.button(
        "Выгрузить актуальные данные",
        use_container_width=True,
        disabled=not author.strip(),
    ):
        _export_current_database(author)
        _render_transfer_flash()
    if st.button("Загрузить актуальные данные", use_container_width=True):
        _start_transfer_probe("select_import")

    selected = st.session_state.get(_TRANSFER_SELECTED_FILE_KEY)
    if selected:
        metadata = st.session_state.get("database_transfer_selected_metadata")
        st.warning(
            "Все текущие данные будут полностью заменены. Перед заменой программа "
            "обязательно создаст резервную копию."
        )
        st.caption(f"Файл: {selected}")
        if metadata:
            st.caption(
                f"Автор: {metadata.author}; создан: "
                f"{metadata.created_at.astimezone().strftime('%d.%m.%Y %H:%M:%S')}"
            )
        confirm_col, cancel_col = st.columns(2)
        if confirm_col.button("Подтвердить загрузку", type="primary"):
            _start_transfer_probe("confirm_import")
        if cancel_col.button("Отмена", key="cancel_database_import"):
            st.session_state.pop(_TRANSFER_SELECTED_FILE_KEY, None)
            st.session_state.pop("database_transfer_selected_metadata", None)
            st.rerun()

    if rollback_available():
        st.divider()
        if st.button("Отменить последнюю загрузку", use_container_width=True):
            _start_transfer_probe("rollback")
    if st.session_state.get(_TRANSFER_CONFIRM_ROLLBACK_KEY):
        st.warning(
            "Будет восстановлено состояние, сохранённое непосредственно перед "
            "последней загрузкой."
        )
        yes, no = st.columns(2)
        if yes.button("Подтвердить откат", type="primary"):
            _start_transfer_probe("confirm_rollback")
        if no.button("Не откатывать"):
            st.session_state.pop(_TRANSFER_CONFIRM_ROLLBACK_KEY, None)
            st.rerun()


def _render_plan_status(host) -> None:
    """Show plan freshness: last recalculation, conflicts and stale hint.

    Read-only: it only reports existing database/session state and never changes
    planning logic.  «Свежесть» плана считается устаревшей, если данные заказов
    менялись после последнего пересчёта или есть несохранённые правки.
    """
    try:
        with SessionLocal() as session:
            last_run = session.scalars(
                select(RecalculationRun).order_by(RecalculationRun.id.desc()).limit(1)
            ).first()
            conflict_count = session.scalar(
                select(func.count()).select_from(PlanningConflict)
            ) or 0
            last_order_change = session.scalar(select(func.max(Order.updated_at)))
    except Exception:
        # Never let the status strip break the shell (e.g. empty DB on first run).
        return

    has_pending_edits = bool(
        st.session_state.get("orders_draft_rows_dirty")
        or section_is_dirty(st.session_state, "routes")
        or section_is_dirty(st.session_state, "work_centers")
        or st.session_state.get("orders_recalculation_requested")
    )

    if last_run is None or last_run.finished_at is None:
        # No completed run yet: treat the plan as needing a recalculation.
        stale = True
    else:
        # Orders edited after the last completed run bump ``updated_at`` past
        # ``finished_at``; recalculation writes happen before the run finishes.
        stale = has_pending_edits or (
            last_order_change is not None
            and last_order_change > last_run.finished_at
        )

    if last_run is None:
        host.warning("План: ещё не рассчитан")
    elif stale:
        host.warning("План: требует пересчёта")
    else:
        host.success("План: актуален")

    if last_run is not None and last_run.finished_at is not None:
        host.caption(f"Последний пересчёт: {last_run.finished_at.strftime('%d.%m.%Y %H:%M')}")

    if conflict_count:
        host.caption(f"⚠️ Конфликтов планирования: {conflict_count}")
    else:
        host.caption("Конфликтов планирования: нет")


def render_bootstrap_controls(planning_host=None) -> None:
    """Render database bootstrap and recalculation controls.

    ``planning_host`` is an optional sidebar container reserved at the top of the
    shell so the plan status and the prominent primary «Пересчитать план» button
    appear above navigation.  When omitted, the controls fall back to the sidebar.
    """
    host = planning_host if planning_host is not None else st.sidebar

    with host:
        st.markdown("**Планирование**")
        _render_plan_status(host)
        requested = st.session_state.get("orders_recalculation_requested")
        flush_request = st.session_state.get("orders_component_flush_request")
        if requested and flush_request == st.session_state.get("orders_component_flush_ack"):
            st.session_state.pop("orders_recalculation_requested", None)
            st.session_state.pop("orders_component_flush_request", None)
            initialize_database()
            from app.ui.pages.page_utils import commit_all_session_drafts
            commit_all_session_drafts()
        if st.button("Пересчитать план", type="primary", use_container_width=True):
            # On the orders screen this is a two-phase internal barrier.  The
            # browser grid first returns its newest snapshot; only the following
            # run is allowed to construct DraftBundle and validate it.
            if st.session_state.get("current_page") == "Реестр заказов" and "orders_draft_rows" in st.session_state:
                token = uuid4().hex
                st.session_state["orders_component_flush_request"] = token
                st.session_state["orders_recalculation_requested"] = True
            else:
                initialize_database()
                from app.ui.pages.page_utils import commit_all_session_drafts
                commit_all_session_drafts()

    transfer_expanded = bool(
        st.session_state.get("database_transfer_flash")
        or st.session_state.get(_TRANSFER_SELECTED_FILE_KEY)
        or st.session_state.get(_TRANSFER_CONFIRM_ROLLBACK_KEY)
        or st.session_state.get(_TRANSFER_PROBE_KEY)
    )
    with st.sidebar.expander("База данных", expanded=transfer_expanded):
        _render_database_transfer_controls()
