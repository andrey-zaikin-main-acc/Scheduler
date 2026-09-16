from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.ui.pages import common


class _Rerun(Exception):
    pass


class _FakeStreamlit:
    def __init__(self, state: dict, *, click: bool = False):
        self.session_state = state
        self.sidebar = self
        self.click = click
        self.button_calls: list[dict] = []
        self.render_events: list[tuple[str, object]] = []
        self.containers: list[_FakeContainer] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def markdown(self, *_args, **_kwargs):
        return None

    def expander(self, *_args, **_kwargs):
        return nullcontext()

    def container(self):
        container = _FakeContainer(self, len(self.containers))
        self.containers.append(container)
        self.render_events.append(("container", container.index))
        return container

    def button(self, label: str, **kwargs) -> bool:
        self.button_calls.append({"label": label, **kwargs})
        return self.click and label == "Пересчитать план" and not kwargs.get("disabled")

    def rerun(self):
        raise _Rerun


class _FakeContainer:
    def __init__(self, streamlit: _FakeStreamlit, index: int):
        self.streamlit = streamlit
        self.index = index
        self.errors: list[str] = []

    def button(self, label: str, **kwargs) -> bool:
        self.streamlit.render_events.append(("button", self.index))
        return self.streamlit.button(label, **kwargs)

    def error(self, message: str) -> None:
        self.errors.append(message)
        self.streamlit.render_events.append(("error", message))


def _render(fake_st: _FakeStreamlit) -> None:
    with (
        patch.object(common, "st", fake_st),
        patch.object(common, "_render_plan_status"),
        patch.object(common, "_render_database_transfer_controls"),
    ):
        common.render_bootstrap_controls()


def test_orders_click_creates_one_flush_token_and_immediately_reruns(monkeypatch) -> None:
    state = {"current_page": "Реестр заказов", "orders_draft_rows": [{"ID": 1}]}
    fake_st = _FakeStreamlit(state, click=True)
    monkeypatch.setattr(common, "uuid4", lambda: SimpleNamespace(hex="flush-1"))

    with pytest.raises(_Rerun):
        _render(fake_st)

    assert state["orders_component_flush_request"] == "flush-1"
    assert state["orders_recalculation_requested"] is True


def test_pending_orders_flush_disables_button_without_replacing_token(monkeypatch) -> None:
    state = {
        "current_page": "Реестр заказов",
        "orders_draft_rows": [{"ID": 1}],
        "orders_component_flush_request": "original-token",
        "orders_recalculation_requested": True,
    }
    fake_st = _FakeStreamlit(state, click=True)
    uuid4 = Mock()
    monkeypatch.setattr(common, "uuid4", uuid4)

    _render(fake_st)

    assert state["orders_component_flush_request"] == "original-token"
    uuid4.assert_not_called()
    assert fake_st.button_calls[0]["disabled"] is True


def test_matching_ack_is_claimed_and_committed_only_once() -> None:
    state = {
        "current_page": "Реестр заказов",
        "orders_draft_rows": [{"ID": 1}],
        "orders_component_flush_request": "flush-1",
        "orders_component_flush_ack": "flush-1",
        "orders_recalculation_requested": True,
    }
    fake_st = _FakeStreamlit(state)

    with (
        patch("app.ui.pages.page_utils.commit_all_session_drafts", return_value=False) as commit,
        patch.object(common, "initialize_database"),
    ):
        _render(fake_st)
        _render(fake_st)  # A component may repeat its last acknowledged payload.

    commit.assert_called_once_with(message_target=fake_st.containers[1])
    assert "orders_component_flush_request" not in state
    assert "orders_recalculation_requested" not in state
    assert state["orders_component_flush_ack"] == "flush-1"
    assert fake_st.button_calls[-1]["disabled"] is False


def test_mismatched_ack_never_starts_commit() -> None:
    state = {
        "current_page": "Реестр заказов",
        "orders_draft_rows": [{"ID": 1}],
        "orders_component_flush_request": "new-token",
        "orders_component_flush_ack": "old-token",
        "orders_recalculation_requested": True,
    }
    fake_st = _FakeStreamlit(state)

    with patch("app.ui.pages.page_utils.commit_all_session_drafts") as commit:
        _render(fake_st)

    commit.assert_not_called()
    assert state["orders_component_flush_request"] == "new-token"


def test_other_pages_still_commit_directly() -> None:
    state = {"current_page": "Маршруты", "routes_draft_rows": [{"ID": 1}]}
    fake_st = _FakeStreamlit(state, click=True)

    with (
        patch("app.ui.pages.page_utils.commit_all_session_drafts") as commit,
        patch.object(common, "initialize_database"),
    ):
        _render(fake_st)

    commit.assert_called_once_with(message_target=fake_st.containers[1])
    assert "orders_component_flush_request" not in state


def test_button_slot_precedes_empty_error_container() -> None:
    fake_st = _FakeStreamlit({"current_page": "Маршруты"})

    _render(fake_st)

    assert fake_st.render_events == [
        ("container", 0),
        ("container", 1),
        ("button", 0),
    ]
    assert fake_st.containers[1].errors == []


@pytest.mark.parametrize(
    "state",
    [
        {
            "current_page": "Реестр заказов",
            "orders_draft_rows": [{"ID": 1}],
            "orders_component_flush_request": "flush-1",
            "orders_component_flush_ack": "flush-1",
            "orders_recalculation_requested": True,
        },
        {"current_page": "Маршруты", "routes_draft_rows": [{"ID": 1}]},
    ],
)
def test_validation_errors_use_only_container_below_button(state: dict) -> None:
    fake_st = _FakeStreamlit(state, click=state["current_page"] != "Реестр заказов")

    def failed_commit(*, message_target) -> bool:
        message_target.error("Первая ошибка")
        message_target.error("Вторая ошибка")
        return False

    with (
        patch(
            "app.ui.pages.page_utils.commit_all_session_drafts",
            side_effect=failed_commit,
        ) as commit,
        patch.object(common, "initialize_database"),
    ):
        _render(fake_st)

    commit.assert_called_once_with(message_target=fake_st.containers[1])
    assert fake_st.containers[1].errors == ["Первая ошибка", "Вторая ошибка"]
    assert fake_st.render_events[:2] == [("container", 0), ("container", 1)]
    assert ("button", 0) in fake_st.render_events
    assert fake_st.button_calls[-1]["disabled"] is False
