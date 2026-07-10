from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.db.database as database
from app.constants import ORDER_STATUS_NEW
from app.db.models import Base, Order, PlanningConflict, Route


def test_migration_converts_legacy_conflict_status(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(database, "engine", engine)

    with Session(engine) as session:
        route = Route(name="Маршрут")
        session.add(route)
        session.flush()
        order = Order(
            order_number="LEGACY-1",
            client_name="Клиент",
            product_name="Продукт",
            quantity=1000,
            shipment_date=date(2026, 7, 10),
            route_id=route.id,
            status="Конфликт планирования",
            calculated_start_date=date(2026, 7, 1),
        )
        session.add(order)
        session.commit()

    database._migrate_legacy_conflict_order_status()
    database._migrate_legacy_conflict_order_status()

    with Session(engine) as session:
        order = session.scalar(select(Order).where(Order.order_number == "LEGACY-1"))
        assert order is not None
        assert order.status == ORDER_STATUS_NEW
        assert order.calculated_start_date is None
        conflicts = session.scalars(select(PlanningConflict)).all()
        assert len(conflicts) == 1
        assert conflicts[0].order_id == order.id
