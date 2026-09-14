from unittest.mock import Mock, patch

from app.ui import navigation
from app.services.draft_history_service import section_is_dirty


def _state(page: str, **values):
    return {"current_page": page, **values}


def test_loaded_route_snapshot_does_not_block_navigation() -> None:
    state = _state("Маршруты", routes_draft_rows=[{"ID": 1}])
    page = navigation.request_navigation(
        state, "Реестр заказов", dirty=section_is_dirty(state, "routes")
    )
    assert page == state["current_page"] == "Реестр заказов"
    assert not state["pending_navigation"]
    assert "pending_navigation_target" not in state


def test_loaded_work_center_snapshot_does_not_block_navigation() -> None:
    state = _state("Участки", work_centers_draft_rows=[{"ID": 1}])
    page = navigation.request_navigation(
        state, "Реестр заказов", dirty=section_is_dirty(state, "work_centers")
    )
    assert page == state["current_page"] == "Реестр заказов"
    assert not state["pending_navigation"]


def test_dirty_route_navigation_keeps_target_until_confirmation() -> None:
    state = _state("Маршруты", routes_dirty=True)
    page = navigation.request_navigation(state, "Реестр заказов", dirty=True)
    assert page == state["current_page"] == "Маршруты"
    assert state["pending_navigation"] is True
    assert state["pending_navigation_target"] == "Реестр заказов"

    # A Streamlit rerun asks for the persisted target again; it is not popped.
    page = navigation.request_navigation(
        state, state["pending_navigation_target"], dirty=True
    )
    assert page == "Маршруты"
    assert state["pending_navigation_target"] == "Реестр заказов"


def test_declining_navigation_finishes_exact_requested_page() -> None:
    state = _state(
        "Маршруты", routes_dirty=False, pending_navigation=True,
        pending_navigation_target="Реестр заказов",
    )
    assert navigation.complete_pending_navigation(state) == "Реестр заказов"
    assert state["current_page"] == state["nav_group_data"] == "Реестр заказов"
    assert state["nav_group_plan"] is None
    assert not state["pending_navigation"]
    assert "pending_navigation_target" not in state


def test_successful_save_completion_finishes_work_center_navigation() -> None:
    state = _state(
        "Участки", work_centers_dirty=False, pending_navigation=True,
        pending_navigation_target="Реестр заказов",
        pending_navigation_commit=True, pending_navigation_commit_completed=True,
    )
    navigation.complete_pending_navigation(state)
    assert state["current_page"] == "Реестр заказов"
    assert not state["work_centers_dirty"]
    assert "pending_navigation_commit" not in state
    assert "pending_navigation_target" not in state


def test_cross_group_completion_synchronises_sidebar_radios() -> None:
    state = _state(
        "Маршруты", routes_dirty=False, pending_navigation=True,
        pending_navigation_target="Производственный план",
    )
    navigation.complete_pending_navigation(state)
    assert state["current_page"] == "Производственный план"
    assert state["nav_group_data"] is None
    assert state["nav_group_plan"] == "Производственный план"


@patch("app.ui.navigation.render_bootstrap_controls")
@patch("app.ui.navigation.render_production_plan_page")
@patch("app.ui.navigation.render_free_slots_page")
@patch("app.ui.navigation.render_orders_page")
def test_navigation_exposes_plan_and_free_slots_pages(
    render_orders_page: Mock,
    render_free_slots_page: Mock,
    render_production_plan_page: Mock,
    render_bootstrap_controls: Mock,
) -> None:
    captured_options = []

    # Start from a clean navigation state so grouped radios re-seed here.
    for key in (
        "current_page", "nav_group_data", "nav_group_plan", "navigation_requested",
    ):
        navigation.st.session_state.pop(key, None)

    def radio(label: str, options: list[str], **kwargs) -> str:
        captured_options.extend(options)
        key = kwargs.get("key")
        # Simulate the user selecting a page inside the "План и результаты" group.
        if "Производственный план" in options:
            navigation.st.session_state[key] = "Производственный план"
            on_change = kwargs.get("on_change")
            if on_change:
                on_change()
        return navigation.st.session_state.get(key)

    with patch.object(navigation.st, "title"), patch.object(
        navigation.st, "caption"
    ), patch.object(navigation.st.sidebar, "radio", side_effect=radio):
        navigation.render_navigation()

    # Both grouped radios expose their pages, and only the selected page renders.
    assert "Производственный план" in captured_options
    assert "Свободные слоты" in captured_options
    assert "Реестр заказов" in captured_options
    render_production_plan_page.assert_called_once_with()
    render_free_slots_page.assert_not_called()
    render_orders_page.assert_not_called()
    # The planning controls are now rendered into the reserved top sidebar slot,
    # so render_bootstrap_controls is called once with that container.
    render_bootstrap_controls.assert_called_once()
