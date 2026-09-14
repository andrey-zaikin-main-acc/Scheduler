from types import SimpleNamespace

from app.services.draft_history_service import section_is_dirty
from app.ui.components import draft_table as module


def _streamlit(editor_result):
    return SimpleNamespace(
        session_state={},
        data_editor=lambda rows, **kwargs: editor_result,
    )


def test_selection_event_does_not_mark_routes_dirty(monkeypatch) -> None:
    fake_st = _streamlit([{"ID": 1, "Выбран": True, "Название": "R"}])
    monkeypatch.setattr(module, "st", fake_st)
    result = module.draft_table(
        [{"ID": 1, "Выбран": False, "Название": "R"}],
        key="routes_page_route_editor",
    )
    assert [event.kind for event in result.events] == ["selection"]
    assert not section_is_dirty(fake_st.session_state, "routes")


def test_business_cell_event_marks_routes_dirty(monkeypatch) -> None:
    fake_st = _streamlit([{"ID": 1, "Выбран": False, "Название": "Changed"}])
    monkeypatch.setattr(module, "st", fake_st)
    result = module.draft_table(
        [{"ID": 1, "Выбран": False, "Название": "Before"}],
        key="routes_page_route_editor",
    )
    assert [event.kind for event in result.events] == ["cell"]
    assert section_is_dirty(fake_st.session_state, "routes")
