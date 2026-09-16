from pathlib import Path
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

from app.services.draft_history_service import DraftAction, session_history
from app.ui.pages import common
from app.ui.pages.common import _has_unsaved_changes


def test_database_transfer_controls_replace_old_bootstrap_buttons() -> None:
    app = AppTest.from_file("app/main.py", default_timeout=20).run()

    assert not app.exception
    labels = [button.label for button in app.button]
    assert "Создать таблицы" not in labels
    assert "Выгрузить актуальные данные" in labels
    assert "Загрузить актуальные данные" in labels
    export_button = next(
        button for button in app.button
        if button.label == "Выгрузить актуальные данные"
    )
    assert export_button.disabled


def test_any_draft_history_action_is_still_detected_for_protected_operations() -> None:
    state = {}
    session_history(state).record(DraftAction("orders", "cell", [], []))

    assert _has_unsaved_changes(state)


def test_clean_state_does_not_block_database_transfer() -> None:
    assert not _has_unsaved_changes({})


def test_nonempty_author_enables_export_and_survives_rerun() -> None:
    app = AppTest.from_file("app/main.py", default_timeout=20).run()
    author = next(field for field in app.text_input if field.label == "Автор выгрузки")

    author.set_value("Иван Петров").run()

    export_button = next(
        button for button in app.button
        if button.label == "Выгрузить актуальные данные"
    )
    assert not export_button.disabled
    assert app.session_state["database_transfer_author"] == "Иван Петров"

    # Leave the orders registry, return to it, and perform one more ordinary
    # rerun.  None of these renders may clear the author widget.
    next(radio for radio in app.radio if radio.key == "nav_group_plan").set_value(
        "Производственный план"
    ).run()
    next(radio for radio in app.radio if radio.key == "nav_group_data").set_value(
        "Реестр заказов"
    ).run()
    app.run()
    assert next(
        field for field in app.text_input if field.label == "Автор выгрузки"
    ).value == "Иван Петров"
    assert not next(
        button for button in app.button
        if button.label == "Выгрузить актуальные данные"
    ).disabled

    # Draft changes and component-originated reruns affect neither the durable
    # author nor export availability.
    app.session_state["orders_draft_rows_dirty"] = True
    app.session_state["orders_component_ack_revision"] = 42
    app.run()
    assert app.session_state["database_transfer_author"] == "Иван Петров"
    assert not next(
        button for button in app.button
        if button.label == "Выгрузить актуальные данные"
    ).disabled


def test_whitespace_author_keeps_export_disabled() -> None:
    app = AppTest.from_file("app/main.py", default_timeout=20).run()
    author = next(field for field in app.text_input if field.label == "Автор выгрузки")

    author.set_value("   \t").run()

    assert next(
        button for button in app.button
        if button.label == "Выгрузить актуальные данные"
    ).disabled


def test_author_widget_is_restored_from_persistent_state(monkeypatch) -> None:
    buttons = []
    fake_st = SimpleNamespace(
        session_state={"database_transfer_author": "Автор из состояния"},
        text_input=lambda *args, **kwargs: None,
        button=lambda label, **kwargs: buttons.append((label, kwargs)) or False,
    )
    monkeypatch.setattr(common, "st", fake_st)
    monkeypatch.setattr(common, "_perform_pending_transfer_action", lambda: None)
    monkeypatch.setattr(common, "_render_transfer_flash", lambda: None)
    monkeypatch.setattr(common, "rollback_available", lambda: False)

    common._render_database_transfer_controls()

    export = next(
        kwargs for label, kwargs in buttons
        if label == "Выгрузить актуальные данные"
    )
    assert export["disabled"] is False
    assert (
        fake_st.session_state["database_transfer_author_input"]
        == "Автор из состояния"
    )


def test_unsaved_export_opens_picker_and_exports_persisted_database(
    monkeypatch, tmp_path
) -> None:
    state = {
        "database_transfer_author": "Иван Петров",
        "orders_draft_rows": [{"number": "НЕСОХРАНЕННЫЙ ЧЕРНОВИК"}],
        "orders_recalculation_requested": True,
        "reference_tables_save_requested": True,
    }
    fake_st = SimpleNamespace(session_state=state)
    monkeypatch.setattr(common, "st", fake_st)
    picker_calls = []
    export_calls = []
    monkeypatch.setattr(
        common,
        "choose_export_directory",
        lambda: picker_calls.append(True) or tmp_path,
    )
    monkeypatch.setattr(
        common,
        "export_database",
        lambda directory, author: export_calls.append((directory, author))
        or Path("snapshot.drawppt"),
    )
    session_history(state).record(DraftAction("orders", "cell", [], []))

    common._export_current_database("Иван Петров")

    assert picker_calls == [True]
    assert export_calls == [(tmp_path, "Иван Петров")]
    assert state["orders_draft_rows"] == [{"number": "НЕСОХРАНЕННЫЙ ЧЕРНОВИК"}]
    assert state["orders_recalculation_requested"] is True
    assert state["database_transfer_flash"] == (
        "success",
        "Данные выгружены: snapshot.drawppt",
    )


def test_successful_export_preserves_author(monkeypatch, tmp_path) -> None:
    state = {"database_transfer_author": "Иван Петров"}
    monkeypatch.setattr(common, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(common, "choose_export_directory", lambda: tmp_path)
    monkeypatch.setattr(common, "export_database", lambda *_: Path("snapshot.drawppt"))

    common._export_current_database(state["database_transfer_author"])

    assert state["database_transfer_author"] == "Иван Петров"
