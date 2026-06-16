from datetime import date

import pytest

pytest.importorskip("sqlalchemy")
from app.constants import ORDER_STATUS_NEW, ORDER_STATUS_PLANNED
from app.db.models import Order, PlannedOperation, PlannedOperationDay, PlanningConflict, RecalculationRun, Route, WorkCenter
from app.ui.components.tables import conflict_rows, order_rows, planned_operation_day_rows, planned_operation_rows, recalculation_rows


def test_order_rows_include_text_client_and_product() -> None:
    route = Route(id=1, name="Маршрут A")
    order = Order(
        id=10,
        order_number="O-10",
        client_name="Клиент",
        product_name="Продукт",
        quantity=1000,
        shipment_date=date(2026, 7, 10),
        route_id=1,
        route=route,
        status=ORDER_STATUS_NEW,
    )

    assert order_rows([order]) == [
        {
            "ID": 10,
            "Номер": "O-10",
            "Клиент": "Клиент",
            "Продукция": "Продукт",
            "Тираж": 1000,
            "Срок отгрузки": date(2026, 7, 10),
            "Маршрут": "Маршрут A",
            "Статус": ORDER_STATUS_NEW,
            "Дата запуска": None,
            "Конфликт": False,
        }
    ]


def test_plan_and_conflict_rows_are_display_ready() -> None:
    work_center = WorkCenter(id=1, name="Печать", available_hours_per_day=8)
    order = Order(
        id=10,
        order_number="O-10",
        client_name="Клиент",
        product_name="Продукт",
        quantity=1000,
        shipment_date=date(2026, 7, 10),
        route_id=1,
        status=ORDER_STATUS_PLANNED,
    )
    operation = PlannedOperation(
        id=20,
        order_id=10,
        order=order,
        route_operation_id=1,
        work_center_id=1,
        work_center=work_center,
        sequence_number=1,
        planned_start_date=date(2026, 7, 10),
        planned_end_date=date(2026, 7, 10),
        required_hours=8.123,
        planned_hours=8.123,
        status=ORDER_STATUS_PLANNED,
    )
    day = PlannedOperationDay(
        id=30,
        planned_operation_id=20,
        work_center_id=1,
        work_center=work_center,
        date=date(2026, 7, 10),
        hours=8.123,
    )
    conflict = PlanningConflict(
        order_id=10,
        order=order,
        shipment_date=date(2026, 7, 10),
        work_center_id=1,
        work_center=work_center,
        required_hours=3,
        available_hours=1,
        deficit_hours=2,
        blocking_order_ids="1,2",
        reason="Недостаточно мощности",
    )
    run = RecalculationRun(id=1, status="completed", summary="OK")

    assert planned_operation_rows([operation])[0]["Требуется часов"] == 8.12
    assert planned_operation_day_rows([day])[0]["Часы"] == 8.12
    assert conflict_rows([conflict])[0]["Дефицит часов"] == 2
    assert recalculation_rows([run])[0]["Статус"] == "completed"
