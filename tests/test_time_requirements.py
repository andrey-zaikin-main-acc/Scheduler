from datetime import date

import pytest

from app.planning.entities import PlanningRouteOperation
from app.planning.order_preparation import PreparedOrder, sort_prepared_orders
from app.planning.time_requirements import (
    calculate_first_transfer_hours,
    calculate_operation_requirements,
    calculate_required_hours,
    calculate_total_required_hours,
    effective_transfer_quantity,
)
from app.planning.entities import PlanningOrder
from app.constants import ORDER_STATUS_NEW


def test_calculate_required_hours() -> None:
    assert calculate_required_hours(10_000, 5) == 50


def test_calculate_required_hours_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        calculate_required_hours(0, 5)
    with pytest.raises(ValueError):
        calculate_required_hours(10_000, 0)


def test_calculate_operation_requirements_and_total_hours() -> None:
    operations = (
        PlanningRouteOperation(2, 2, 20, "Высечка", 3),
        PlanningRouteOperation(1, 1, 10, "Печать", 4),
    )

    requirements = calculate_operation_requirements(10_000, operations)

    assert [
        requirement.route_operation.sequence_number for requirement in requirements
    ] == [1, 2]
    assert [requirement.required_hours for requirement in requirements] == [40, 30]
    assert calculate_total_required_hours(requirements) == 70


def test_transfer_batch_calculations() -> None:
    assert effective_transfer_quantity(700, 1000) == 700
    assert effective_transfer_quantity(10_000, 1000) == 1000
    assert (
        calculate_first_transfer_hours(
            order_quantity=10_000,
            min_transfer_quantity=1000,
            labor_hours_per_1000=5,
        )
        == 5
    )


def test_sort_prepared_orders_uses_shipment_deadline_then_order_id() -> (
    None
):
    first = PreparedOrder(
        order=PlanningOrder(
            id=2, quantity=1000, shipment_date=date(2026, 7, 9), status=ORDER_STATUS_NEW
        ),
        requirements=(),
        total_required_hours=10,
    )
    second = PreparedOrder(
        order=PlanningOrder(
            id=1,
            quantity=1000,
            shipment_date=date(2026, 7, 10),
            status=ORDER_STATUS_NEW,
        ),
        requirements=(),
        total_required_hours=100,
    )
    third = PreparedOrder(
        order=PlanningOrder(
            id=3, quantity=1000, shipment_date=date(2026, 7, 8), status=ORDER_STATUS_NEW
        ),
        requirements=(),
        total_required_hours=20,
    )

    sorted_orders = sort_prepared_orders([first, second, third])

    assert [prepared.order.id for prepared in sorted_orders] == [3, 2, 1]
