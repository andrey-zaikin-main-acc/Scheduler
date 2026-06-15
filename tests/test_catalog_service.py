from datetime import date

import pytest

pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.constants import ORDER_STATUS_NEW
from app.db.database import Base
from app.db.models import Order, Route, RouteOperation, WorkCenter
from app.services.catalog_service import CatalogService


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with session_factory() as session:
        yield session


def test_catalog_service_creates_work_center_route_operation_and_order(session: Session) -> None:
    service = CatalogService(session)

    work_center = service.create_work_center(name="Печать", available_hours_per_day=8)
    route = service.create_route(name="Маршрут A")
    operation = service.add_route_operation(
        route_id=route.id,
        work_center_id=work_center.id,
        sequence_number=1,
        labor_hours_per_1000=4,
        min_transfer_quantity_to_next=1000,
    )
    order = service.create_order(
        order_number="C-001",
        client_name="Клиент",
        product_name="Продукт",
        quantity=1000,
        shipment_date=date(2026, 7, 10),
        route_id=route.id,
        status=ORDER_STATUS_NEW,
    )

    assert session.query(WorkCenter).count() == 1
    assert session.query(Route).count() == 1
    assert session.query(RouteOperation).count() == 1
    assert session.query(Order).count() == 1
    assert operation.min_transfer_quantity_to_next == 1000
    assert order.client_name == "Клиент"


def test_catalog_service_validates_positive_values(session: Session) -> None:
    service = CatalogService(session)

    with pytest.raises(ValueError):
        service.create_work_center(name="Печать", available_hours_per_day=0)

    work_center = service.create_work_center(name="Печать", available_hours_per_day=8)
    route = service.create_route(name="Маршрут A")

    with pytest.raises(ValueError):
        service.add_route_operation(
            route_id=route.id,
            work_center_id=work_center.id,
            sequence_number=1,
            labor_hours_per_1000=0,
        )

    with pytest.raises(ValueError):
        service.create_order(
            order_number="C-002",
            client_name="Клиент",
            product_name="Продукт",
            quantity=0,
            shipment_date=date(2026, 7, 10),
            route_id=route.id,
        )
