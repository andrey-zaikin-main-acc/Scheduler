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
