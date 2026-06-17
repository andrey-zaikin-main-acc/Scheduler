from datetime import date

import pytest

pytest.importorskip("streamlit")
from app.constants import ORDER_STATUS_NEW
from app.db.models import Order, Route
from app.ui.pages.orders_page import build_order_editor_rows, validate_order_editor_row


def test_order_editor_rows_include_selection_and_editable_fields() -> None:
    route = Route(id=1, name="наша сборка")
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

    rows = build_order_editor_rows([order], selected_order_id=10, include_draft=True)

    assert rows[0] == {
        "Выбран": True,
        "ID": 10,
        "Номер": "O-10",
        "Клиент": "Клиент",
        "Продукция": "Продукт",
        "Тираж": 1000,
        "Срок отгрузки": date(2026, 7, 10),
        "Маршрут": "наша сборка",
        "Статус": ORDER_STATUS_NEW,
        "Дата запуска": None,
        "Конфликт": False,
    }
    assert rows[1]["ID"] is None
    assert rows[1]["Статус"] == ORDER_STATUS_NEW


def test_validate_order_editor_row_rejects_duplicate_order_number() -> None:
    row = {
        "Номер": "DUP-1",
        "Клиент": "Клиент",
        "Продукция": "Продукт",
        "Тираж": 1000,
        "Срок отгрузки": date(2026, 7, 10),
        "Маршрут": "наша сборка",
        "Статус": ORDER_STATUS_NEW,
    }

    errors = validate_order_editor_row(
        row,
        route_names={"наша сборка"},
        existing_numbers={"DUP-1": 1},
        current_order_id=None,
    )

    assert "Заказ с таким номером уже существует." in errors


def test_validate_order_editor_row_accepts_current_order_number_on_update() -> None:
    row = {
        "Номер": "DUP-1",
        "Клиент": "Клиент",
        "Продукция": "Продукт",
        "Тираж": 1000,
        "Срок отгрузки": date(2026, 7, 10),
        "Маршрут": "наша сборка",
        "Статус": ORDER_STATUS_NEW,
    }

    errors = validate_order_editor_row(
        row,
        route_names={"наша сборка"},
        existing_numbers={"DUP-1": 1},
        current_order_id=1,
    )

    assert errors == []
