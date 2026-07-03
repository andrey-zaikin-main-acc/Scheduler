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

    def radio(label: str, options: list[str]) -> str:
        captured_options.extend(options)
        return "Производственный план"

    with patch.object(navigation.st, "title"), patch.object(
        navigation.st, "caption"
    ), patch.object(navigation.st.sidebar, "radio", side_effect=radio):
        navigation.render_navigation()

    assert "Производственный план" in captured_options
    assert "Свободные слоты" in captured_options
    render_production_plan_page.assert_called_once_with()
    render_free_slots_page.assert_not_called()
    render_orders_page.assert_not_called()
    render_bootstrap_controls.assert_called_once_with()
