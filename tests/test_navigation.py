from unittest.mock import Mock, patch

import pytest
from streamlit.testing.v1 import AppTest

from app.ui import navigation
from app.services.draft_history_service import DraftAction, section_is_dirty, session_history


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


def test_clean_backend_navigation_waits_for_authoritative_probe() -> None:
    state = _state("Маршруты", routes_dirty=False)
    token = navigation.begin_navigation_probe(
        state, "Реестр заказов", section="routes", editor_keys=["route", "operation"]
    )
    assert state["current_page"] == "Маршруты"
    assert state["pending_navigation_target"] == "Реестр заказов"
    assert state["navigation_probe_pending"] is True
    assert state["reference_tables_flush_request"] == token
    assert navigation.begin_navigation_probe(
        state, "Реестр заказов", section="routes", editor_keys=["route", "operation"]
    ) == token


def test_probe_discovers_business_edit_before_showing_confirmation() -> None:
    state = _state("Маршруты", routes_dirty=False)
    navigation.begin_navigation_probe(
        state, "Реестр заказов", section="routes", editor_keys=["route"]
    )
    state["routes_dirty"] = True
    assert navigation.resolve_navigation_probe(state, "routes")
    assert state["pending_navigation"] is True
    assert state["current_page"] == "Маршруты"
    assert state["pending_navigation_target"] == "Реестр заказов"
    assert "reference_tables_flush_request" not in state


@pytest.mark.parametrize("page,section", [("Маршруты", "routes"), ("Участки", "work_centers")])
def test_clean_probe_completes_without_confirmation(page: str, section: str) -> None:
    state = _state(page, **{f"{section}_dirty": False})
    navigation.begin_navigation_probe(
        state, "Реестр заказов", section=section, editor_keys=["editor"]
    )
    assert navigation.resolve_navigation_probe(state, section)
    assert state["navigation_probe_clean_completed"] is True
    assert state["pending_navigation"] is False
    assert navigation.complete_pending_navigation(state) == "Реестр заказов"


def test_thirty_probe_discard_stress_has_one_token_per_navigation() -> None:
    state = _state("Маршруты", routes_dirty=False)
    tokens = set()
    for _ in range(30):
        token = navigation.begin_navigation_probe(
            state, "Реестр заказов", section="routes", editor_keys=["route", "operation"]
        )
        tokens.add(token)
        state["routes_dirty"] = True
        navigation.resolve_navigation_probe(state, "routes")
        assert state["pending_navigation"]
        state["routes_dirty"] = False
        state["pending_navigation_discard_completed"] = True
        navigation.complete_pending_navigation(state)
        state["current_page"] = "Маршруты"
    assert len(tokens) == 30


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


@pytest.mark.parametrize(
    ("page", "section", "target", "draft_key"),
    [
        ("Маршруты", "routes", "Реестр заказов", "routes_draft_rows"),
        ("Участки", "work_centers", "Реестр заказов", "work_centers_draft_rows"),
        ("Маршруты", "routes", "Производственный план", "routes_draft_rows"),
    ],
)
def test_real_streamlit_discard_completes_on_next_run_before_navigation_widgets(
    page: str, section: str, target: str, draft_key: str,
) -> None:
    """Exercise the widget lifecycle that a plain-dict state test cannot model."""
    app = AppTest.from_file("app/main.py", default_timeout=20).run()
    app.session_state["current_page"] = page
    app.session_state["nav_group_data"] = page
    app.session_state["nav_group_plan"] = None
    app.session_state["pending_navigation"] = True
    app.session_state["pending_navigation_target"] = target
    app.session_state["requested_page"] = target
    app.session_state[f"{section}_dirty"] = True
    app.session_state[("routes_page_route_editor_source_version"
                       if section == "routes" else
                       "work_centers_page_editor_source_version")] = 6
    app.session_state[draft_key] = [{"ID": 999, "Название": "Черновик"}]
    history = session_history(app.session_state)
    history.record(DraftAction(section, "cell", [], [], (), ("Название",)))
    if section == "routes":
        app.session_state["route_operations_drafts_by_route_id"] = {999: []}
        app.session_state["routes_page_operation_editor_999_source_version"] = 3
        app.session_state["routes_page_visible_editors"] = [
            "routes_page_route_editor", "routes_page_operation_editor_999"
        ]
        history.record(DraftAction("operations", "cell", [], [], (), ("Участок",)))

    app = app.run()
    assert not app.exception
    no_button = next(button for button in app.button if button.label == "Нет")
    app = no_button.click().run()

    assert not app.exception
    assert app.session_state["current_page"] == target
    assert app.session_state["nav_group_data"] == (target if target in navigation.DATA_PAGES else None)
    assert app.session_state["nav_group_plan"] == (target if target in navigation.RESULT_PAGES else None)
    assert app.session_state["pending_navigation"] is False
    assert "pending_navigation_target" not in app.session_state
    assert "pending_navigation_discard_completed" not in app.session_state
    assert draft_key not in app.session_state
    assert app.session_state[f"{section}_dirty"] is False
    main_version_key = ("routes_page_route_editor_source_version"
                        if section == "routes" else
                        "work_centers_page_editor_source_version")
    assert app.session_state[main_version_key] == 7
    remaining = session_history(app.session_state)
    assert not any(action.section == section for action in remaining.undo_stack + remaining.redo_stack)
    if section == "routes":
        assert app.session_state["routes_page_operation_editor_999_source_version"] == 4
        assert "route_operations_drafts_by_route_id" not in app.session_state
        assert not any(action.section == "operations"
                       for action in remaining.undo_stack + remaining.redo_stack)


@pytest.mark.parametrize("page,section", [("Маршруты", "routes"), ("Участки", "work_centers")])
def test_successful_navigation_save_completes_only_on_rerun(page: str, section: str) -> None:
    app = AppTest.from_file("app/main.py", default_timeout=20).run()
    app.session_state["current_page"] = page
    app.session_state["nav_group_data"] = page
    app.session_state["nav_group_plan"] = None
    app.session_state["pending_navigation"] = True
    app.session_state["pending_navigation_target"] = "Реестр заказов"
    app.session_state[f"{section}_dirty"] = True
    app = app.run()
    yes_button = next(button for button in app.button if button.label == "Да")

    def successful_commit(**_kwargs) -> bool:
        app.session_state[f"{section}_dirty"] = False
        app.session_state["pending_navigation_commit_completed"] = True
        return True

    with patch("app.ui.pages.page_utils.commit_all_session_drafts", side_effect=successful_commit) as commit:
        app = yes_button.click().run()
        token = (app.session_state["reference_tables_flush_request"]
                 if "reference_tables_flush_request" in app.session_state else None)
        # Routes can discover a second (operations) grid while rendering.  Ack
        # every discovered iframe just as the browser components do.
        for _ in range(3) if token else ():
            for editor in app.session_state["reference_tables_flush_editors"]:
                app.session_state[f"{editor}_component_flush_ack"] = token
            app = app.run()
            if commit.called:
                break

    assert not app.exception
    commit.assert_called_once_with(sections={section}, message_target=navigation.st)
    assert app.session_state["current_page"] == "Реестр заказов"
    assert app.session_state["nav_group_data"] == "Реестр заказов"
    assert app.session_state["nav_group_plan"] is None
    assert app.session_state["pending_navigation"] is False
    assert "pending_navigation_target" not in app.session_state
    assert "pending_navigation_commit_completed" not in app.session_state


def test_failed_navigation_save_preserves_dirty_page_and_pending_target() -> None:
    app = AppTest.from_file("app/main.py", default_timeout=20).run()
    app.session_state["current_page"] = "Маршруты"
    app.session_state["nav_group_data"] = "Маршруты"
    app.session_state["nav_group_plan"] = None
    app.session_state["pending_navigation"] = True
    app.session_state["pending_navigation_target"] = "Производственный план"
    app.session_state["routes_dirty"] = True
    app = app.run()
    yes_button = next(button for button in app.button if button.label == "Да")

    with patch("app.ui.pages.page_utils.commit_all_session_drafts", return_value=False):
        app = yes_button.click().run()

    assert not app.exception
    assert app.session_state["current_page"] == "Маршруты"
    assert app.session_state["routes_dirty"] is True
    assert app.session_state["pending_navigation"] is True
    assert app.session_state["pending_navigation_target"] == "Производственный план"
    assert "pending_navigation_commit_completed" not in app.session_state


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
