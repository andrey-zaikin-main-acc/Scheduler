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

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def markdown(self, *_args, **_kwargs):
        return None

    def expander(self, *_args, **_kwargs):
        return nullcontext()

    def button(self, label: str, **kwargs) -> bool:
        self.button_calls.append({"label": label, **kwargs})
        return self.click and label == "Пересчитать план" and not kwargs.get("disabled")

    def rerun(self):
        raise _Rerun


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

    commit.assert_called_once_with()
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

    commit.assert_called_once_with()
    assert "orders_component_flush_request" not in state

