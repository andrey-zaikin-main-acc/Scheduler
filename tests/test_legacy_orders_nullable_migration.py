"""Regression tests for upgrading the pre-draft SQLite orders table."""

from datetime import date

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

import app.db.database as database
import app.services.bootstrap_service as bootstrap_service
from app.db.models import Base, Order


OLD_ORDERS_SQL = """
CREATE TABLE orders (
    id INTEGER NOT NULL PRIMARY KEY,
    priority INTEGER NOT NULL DEFAULT 0,
    order_number VARCHAR(100) NOT NULL UNIQUE,
    client_name VARCHAR(255) NOT NULL,
    product_name VARCHAR(255) NOT NULL,
    quantity FLOAT NOT NULL,
    shipment_date DATE NOT NULL,
    planning_mode VARCHAR(50) NOT NULL DEFAULT 'От даты отгрузки',
    fixed_start_date DATE,
    child_group_key VARCHAR(100),
    child_sequence_number INTEGER,
    is_child_order BOOLEAN NOT NULL DEFAULT 0,
    is_linked_child_group BOOLEAN NOT NULL DEFAULT 0,
    route_id INTEGER NOT NULL REFERENCES routes (id),
    status VARCHAR(50) NOT NULL,
    calculated_start_date DATE,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    CONSTRAINT ck_orders_quantity_positive CHECK (quantity > 0)
)
"""


def _create_legacy_database(engine, *, partially_updated: bool = False) -> None:
    """Create the legacy orders table and representative related user data."""
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys = OFF")
        connection.exec_driver_sql("DROP TABLE orders")
        sql = OLD_ORDERS_SQL
        if partially_updated:
            sql = sql.replace(
                "planning_mode VARCHAR(50)",
                "calculated_shipment_date DATE, planning_mode VARCHAR(50)",
            )
        connection.exec_driver_sql(sql)
        connection.exec_driver_sql(
            "CREATE INDEX ix_orders_legacy_customer ON orders (client_name, product_name)"
        )
        connection.execute(text("""
            INSERT INTO work_centers (
                id, name, available_hours_per_day, workday_start_time, is_active,
                prevent_order_interruption, created_at, updated_at
            ) VALUES (11, 'Участок', 8, '09:00:00', 1, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """))
        connection.execute(text("""
            INSERT INTO routes (
                id, name, description, is_active, prevent_order_interruption,
                created_at, updated_at
            ) VALUES (21, 'Маршрут', 'Пользовательский маршрут', 1, 0,
                      CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """))
        connection.execute(text("""
            INSERT INTO route_operations (
                id, route_id, sequence_number, work_center_id,
                labor_hours_per_1000, min_transfer_quantity_to_next, is_active,
                created_at, updated_at
            ) VALUES (31, 21, 1, 11, 2, NULL, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """))
        calculated_column = ", calculated_shipment_date" if partially_updated else ""
        calculated_value = ", NULL" if partially_updated else ""
        connection.execute(text(f"""
            INSERT INTO orders (
                id, priority, order_number, client_name, product_name, quantity,
                shipment_date{calculated_column}, planning_mode, fixed_start_date,
                child_group_key, child_sequence_number, is_child_order,
                is_linked_child_group, route_id, status, calculated_start_date,
                created_at, updated_at
            ) VALUES
                (101, 1, 'SHIP-1', 'Клиент А', 'Продукт А', 1000,
                 '2026-08-20'{calculated_value}, 'От даты отгрузки', NULL,
                 NULL, NULL, 0, 0, 21, 'Новый', '2026-08-18', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                (102, 2, 'START-1', 'Клиент Б', 'Продукт Б', 2000,
                 '2026-08-10'{calculated_value}, 'От даты запуска', '2026-08-10',
                 'GROUP-1', 1, 0, 1, 21, 'Запланирован', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                (103, 3, 'START-1/2', 'Клиент Б', 'Продукт Б', 500,
                 '2026-08-10'{calculated_value}, 'От даты запуска', '2026-08-11',
                 'GROUP-1', 2, 1, 1, 21, '', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """))
        connection.execute(text("""
            INSERT INTO planned_operations (
                id, order_id, route_operation_id, work_center_id, sequence_number,
                planned_start_date, planned_end_date, required_hours, planned_hours,
                status, created_at, updated_at
            ) VALUES
                (201, 102, 31, 11, 1, '2026-08-10', '2026-08-14', 4, 4,
                 'Запланирована', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                (202, 103, 31, 11, 1, '2026-08-11', '2026-08-15', 2, 2,
                 'Запланирована', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """))
        connection.execute(text("""
            INSERT INTO planning_conflicts (
                id, order_id, shipment_date, work_center_id, required_hours,
                available_hours, deficit_hours, blocking_order_ids, reason, created_at
            ) VALUES (301, 101, '2026-08-20', 11, 10, 8, 2, '102',
                      'Пользовательский конфликт', CURRENT_TIMESTAMP)
        """))


def _use_engine(monkeypatch, engine) -> None:
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys = ON")
        connection.commit()
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(
        database,
        "SessionLocal",
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
    )


def _assert_migrated(engine) -> None:
    columns = {column["name"]: column for column in inspect(engine).get_columns("orders")}
    assert columns["shipment_date"]["nullable"] is True
    assert columns["status"]["nullable"] is True
    assert "calculated_shipment_date" in columns

    with engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM orders ORDER BY id")).scalars().all() == [101, 102, 103]
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        assert connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='ix_orders_legacy_customer'"
        )).scalar_one() == "ix_orders_legacy_customer"
        assert connection.execute(text("SELECT COUNT(*) FROM planned_operations")).scalar_one() == 2
        assert connection.execute(text("SELECT order_id FROM planning_conflicts")).scalar_one() == 101
        assert connection.execute(text(
            "SELECT route_id, work_center_id FROM route_operations WHERE id = 31"
        )).one() == (21, 11)

    with Session(engine) as session:
        shipment = session.get(Order, 101)
        start = session.get(Order, 102)
        child = session.get(Order, 103)
        assert shipment.shipment_date == date(2026, 8, 20)
        assert (shipment.order_number, shipment.client_name, shipment.product_name) == (
            "SHIP-1", "Клиент А", "Продукт А"
        )
        assert shipment.quantity == 1000
        assert shipment.route_id == 21
        assert start.shipment_date is None
        assert start.fixed_start_date == date(2026, 8, 10)
        assert start.calculated_shipment_date == date(2026, 8, 14)
        assert child.shipment_date is None
        assert child.calculated_shipment_date == date(2026, 8, 15)
        assert child.child_group_key == "GROUP-1"
        assert [operation.id for operation in start.planned_operations] == [201]
        shipment.status = None
        session.commit()
        assert session.scalar(select(Order.status).where(Order.id == 101)) is None


def test_create_all_migrates_legacy_orders_without_data_loss(monkeypatch, tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite3'}")
    _create_legacy_database(engine)
    _use_engine(monkeypatch, engine)

    database.create_all()
    _assert_migrated(engine)
    database.create_all()
    _assert_migrated(engine)


def test_create_all_handles_partially_updated_legacy_orders(monkeypatch, tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'partial.sqlite3'}")
    _create_legacy_database(engine, partially_updated=True)
    _use_engine(monkeypatch, engine)

    database.create_all()
    _assert_migrated(engine)


def test_desktop_initialization_migrates_existing_legacy_database(monkeypatch, tmp_path) -> None:
    sqlite_path = tmp_path / "DrawPPT" / "planner.sqlite3"
    sqlite_path.parent.mkdir()
    engine = create_engine(f"sqlite:///{sqlite_path}")
    _create_legacy_database(engine)
    _use_engine(monkeypatch, engine)
    monkeypatch.setattr(bootstrap_service, "SQLITE_PATH", sqlite_path)

    bootstrap_service.initialize_desktop_database()

    _assert_migrated(engine)
