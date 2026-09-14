from unittest.mock import Mock, patch

from app.ui import navigation


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
