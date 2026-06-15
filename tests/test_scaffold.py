from app.config import DEFAULT_FREE_SLOT_DAYS, MAX_BACKWARD_SEARCH_MONTHS
from app.constants import ORDER_STATUS_DONE, ORDER_STATUS_NEW, PLANNABLE_ORDER_STATUSES


def test_default_free_slot_period_is_30_days() -> None:
    assert DEFAULT_FREE_SLOT_DAYS == 30


def test_backward_search_limit_is_12_months() -> None:
    assert MAX_BACKWARD_SEARCH_MONTHS == 12


def test_done_orders_are_not_plannable() -> None:
    assert ORDER_STATUS_NEW in PLANNABLE_ORDER_STATUSES
    assert ORDER_STATUS_DONE not in PLANNABLE_ORDER_STATUSES
