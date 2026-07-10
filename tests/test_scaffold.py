from app.config import DEFAULT_FREE_SLOT_DAYS, MAX_BACKWARD_SEARCH_MONTHS
from app.constants import (
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_CONFLICT,
    ORDER_STATUS_NEW,
    ORDER_STATUS_PLANNED,
    ORDER_STATUSES,
    PLANNABLE_ORDER_STATUSES,
)


def test_default_free_slot_period_is_30_days() -> None:
    assert DEFAULT_FREE_SLOT_DAYS == 30


def test_backward_search_limit_is_12_months() -> None:
    assert MAX_BACKWARD_SEARCH_MONTHS == 12


def test_supported_order_statuses_are_exactly_four() -> None:
    assert ORDER_STATUSES == (
        ORDER_STATUS_NEW,
        ORDER_STATUS_PLANNED,
        ORDER_STATUS_CONFLICT,
        ORDER_STATUS_CANCELLED,
    )
    assert "Выполнен" not in ORDER_STATUSES
    assert "Не выполнен" not in ORDER_STATUSES


def test_cancelled_orders_are_not_plannable() -> None:
    assert ORDER_STATUS_NEW in PLANNABLE_ORDER_STATUSES
    assert ORDER_STATUS_PLANNED in PLANNABLE_ORDER_STATUSES
    assert ORDER_STATUS_CONFLICT in PLANNABLE_ORDER_STATUSES
    assert ORDER_STATUS_CANCELLED not in PLANNABLE_ORDER_STATUSES
