from datetime import date

from app.ui.pages.page_utils import normalize_date_range


def test_normalize_date_range_accepts_streamlit_tuple_and_list() -> None:
    start = date(2026, 7, 1)
    end = date(2026, 7, 31)

    assert normalize_date_range((start, end), date(2026, 1, 1), date(2026, 1, 31)) == (start, end)
    assert normalize_date_range([start, end], date(2026, 1, 1), date(2026, 1, 31)) == (start, end)


def test_normalize_date_range_falls_back_for_partial_selection() -> None:
    default_start = date(2026, 1, 1)
    default_end = date(2026, 1, 31)

    assert normalize_date_range(date(2026, 7, 1), default_start, default_end) == (default_start, default_end)
    assert normalize_date_range([date(2026, 7, 1)], default_start, default_end) == (default_start, default_end)


def test_normalize_date_range_orders_reversed_range() -> None:
    assert normalize_date_range(
        (date(2026, 7, 31), date(2026, 7, 1)),
        date(2026, 1, 1),
        date(2026, 1, 31),
    ) == (date(2026, 7, 1), date(2026, 7, 31))


def test_successful_reference_save_advances_route_operation_and_work_center_sources() -> None:
    from app.ui.pages.page_utils import advance_saved_reference_sources

    state = {
        "routes_page_route_editor_source_version": 4,
        "routes_page_visible_editors": ["routes_page_route_editor", "routes_page_operation_editor_7"],
        "routes_page_operation_editor_7_source_version": 2,
        "routes_page_operation_editor_9_source_version": 5,
        "work_centers_page_editor_source_version": 8,
    }
    editors = advance_saved_reference_sources(state, {"routes", "work_centers"})

    assert editors == {
        "routes_page_route_editor", "routes_page_operation_editor_7",
        "routes_page_operation_editor_9", "work_centers_page_editor",
    }
    assert state["routes_page_route_editor_source_version"] == 5
    assert state["routes_page_operation_editor_7_source_version"] == 3
    assert state["routes_page_operation_editor_9_source_version"] == 6
    assert state["work_centers_page_editor_source_version"] == 9


def test_unsaved_sections_do_not_advance_reference_sources() -> None:
    from app.ui.pages.page_utils import advance_saved_reference_sources

    state = {"routes_page_route_editor_source_version": 4}
    assert advance_saved_reference_sources(state, {"orders"}) == set()
    assert state["routes_page_route_editor_source_version"] == 4
