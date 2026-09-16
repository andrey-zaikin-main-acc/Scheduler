from streamlit.testing.v1 import AppTest

from app.services.draft_history_service import DraftAction, session_history
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
