import pytest

pytest.importorskip("streamlit")

from app.ui.pages.routes_page import reconcile_single_selection


def test_route_selection_uses_first_checkbox_click_and_clears_previous() -> None:
    previous = [
        {"ID": 1, "Выбран": True},
        {"ID": 2, "Выбран": False},
    ]
    edited = [
        {"ID": 1, "Выбран": True},
        {"ID": 2, "Выбран": True},
    ]

    rows, selected_id, changed = reconcile_single_selection(
        previous, edited, previous_id=1
    )

    assert selected_id == 2
    assert changed is True
    assert [row["Выбран"] for row in rows] == [False, True]


def test_operation_selection_can_be_cleared_with_one_click() -> None:
    rows, selected_id, changed = reconcile_single_selection(
        [{"ID": 10, "Выбран": True}],
        [{"ID": 10, "Выбран": False}],
        previous_id=10,
    )
    assert rows == [{"ID": 10, "Выбран": False}]
    assert selected_id is None
    assert changed is True
