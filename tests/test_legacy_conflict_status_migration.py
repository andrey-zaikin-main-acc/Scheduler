from datetime import date

from sqlalchemy import create_engine, select, text
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
        assert order.status == ""
        assert order.calculated_start_date is None
        conflicts = session.scalars(select(PlanningConflict)).all()
        assert len(conflicts) == 1
        assert conflicts[0].order_id == order.id


def test_priority_migration_initializes_by_id_and_is_idempotent(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr(database, "engine", engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE orders (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO orders (id) VALUES (7), (2), (9)"))

    database._ensure_order_priority_column()
    with engine.begin() as connection:
        rows = connection.execute(text("SELECT id, priority FROM orders ORDER BY id")).all()
        assert rows == [(2, 1), (7, 2), (9, 3)]
        connection.execute(text("UPDATE orders SET priority = 1 WHERE id = 9"))
        connection.execute(text("UPDATE orders SET priority = 2 WHERE id = 2"))
        connection.execute(text("UPDATE orders SET priority = 3 WHERE id = 7"))

    database._ensure_order_priority_column()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM orders ORDER BY priority")).scalars().all() == [9, 2, 7]
