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


def test_any_draft_history_action_blocks_database_transfer() -> None:
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


def test_export_disabled_uses_value_displayed_by_text_input(monkeypatch) -> None:
    """Regression for a widget rerun whose session mapping is one render behind."""
    buttons = []
    fake_st = SimpleNamespace(
        session_state={"database_transfer_author": ""},
        text_input=lambda *args, **kwargs: "Автор из браузера",
        button=lambda label, **kwargs: buttons.append((label, kwargs)) or False,
    )
    monkeypatch.setattr(common, "st", fake_st)
    monkeypatch.setattr(common, "_perform_pending_transfer_action", lambda: None)
    monkeypatch.setattr(common, "_render_transfer_flash", lambda: None)
    monkeypatch.setattr(common, "rollback_available", lambda: False)

    common._render_database_transfer_controls()

    export = next(kwargs for label, kwargs in buttons if label == "Выгрузить актуальные данные")
    assert export["disabled"] is False


def test_unsaved_export_does_not_open_directory_picker(monkeypatch) -> None:
    state = {
        "database_transfer_author": "Иван Петров",
        "database_transfer_action": "export",
        "database_transfer_probe_pending": True,
        "database_transfer_probe_completed": True,
    }
    fake_st = SimpleNamespace(session_state=state)
    monkeypatch.setattr(common, "st", fake_st)
    monkeypatch.setattr(
        common, "choose_export_directory",
        lambda: (_ for _ in ()).throw(AssertionError("directory picker must not open")),
    )
    session_history(state).record(DraftAction("orders", "cell", [], []))

    common._perform_pending_transfer_action()

    assert state["database_transfer_flash"] == (
        "error",
        "Есть несохранённые изменения. Нажмите «Пересчитать план», дождитесь "
        "сохранения изменений и повторите выгрузку.",
    )
    assert "database_transfer_action" not in state
