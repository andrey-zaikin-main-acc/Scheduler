"""Database engine and session helpers for the production planner MVP."""

import re
from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATA_DIR, DATABASE_URL
from app.constants import ORDER_STATUS_NEW, PLANNING_MODE_SHIPMENT


class Base(DeclarativeBase):
    """Base class for SQLAlchemy ORM models."""


engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
)


def ensure_data_dir() -> None:
    """Create the local data directory used by SQLite if it does not exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def create_all() -> None:
    """Create all database tables."""
    ensure_data_dir()
    Base.metadata.create_all(bind=engine)
    _ensure_work_center_workday_start_time_column()
    _ensure_work_center_prevent_order_interruption_column()
    _ensure_route_prevent_order_interruption_column()
    _ensure_planned_operation_day_intraday_columns()
    _ensure_order_planning_columns()
    _ensure_order_priority_column()
    _ensure_draft_architecture_columns()
    _ensure_nullable_conflict_shipment_date()
    _migrate_legacy_conflict_order_status()


def _ensure_draft_architecture_columns() -> None:
    """Idempotently upgrade databases created before session drafts existed."""
    _ensure_nullable_order_dates_and_status()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        if "route_operations" in tables:
            columns = {c["name"] for c in inspector.get_columns("route_operations")}
            if "is_active" not in columns:
                connection.execute(text("ALTER TABLE route_operations ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"))
        if "plan_changes" in tables:
            columns = {c["name"] for c in inspector.get_columns("plan_changes")}
            if "operation_sequence_number" not in columns:
                connection.execute(text("ALTER TABLE plan_changes ADD COLUMN operation_sequence_number INTEGER"))
        if "orders" in tables:
            columns = {c["name"] for c in inspector.get_columns("orders")}
            if "calculated_shipment_date" not in columns:
                connection.execute(text("ALTER TABLE orders ADD COLUMN calculated_shipment_date DATE"))
            # Recover the result for start-driven legacy orders from the real plan.
            connection.execute(text("""
                UPDATE orders SET calculated_shipment_date = (
                    SELECT MAX(planned_end_date) FROM planned_operations
                    WHERE planned_operations.order_id = orders.id
                ) WHERE planning_mode = 'От даты запуска'
                  AND calculated_shipment_date IS NULL
            """))
            connection.execute(text("""
                UPDATE orders SET shipment_date = NULL
                WHERE planning_mode = 'От даты запуска'
            """))
            connection.execute(text("""
                UPDATE orders SET status = ''
                WHERE status = 'Запланирован'
                   OR EXISTS (SELECT 1 FROM planning_conflicts c WHERE c.order_id = orders.id)
            """))


def _without_not_null(create_sql: str, column_names: set[str]) -> str:
    """Remove NOT NULL from selected top-level columns in SQLite CREATE SQL."""
    opening = create_sql.index("(")
    closing = create_sql.rindex(")")
    body = create_sql[opening + 1 : closing]
    parts: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    for position, character in enumerate(body):
        if quote:
            if character == quote:
                quote = None
        elif character in "\"'`[":
            quote = "]" if character == "[" else character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "," and depth == 0:
            parts.append(body[start:position])
            start = position + 1
    parts.append(body[start:])

    identifier = re.compile(r'^\s*(?:"([^"]+)"|`([^`]+)`|\[([^]]+)\]|([^\s]+))')
    for index, definition in enumerate(parts):
        match = identifier.match(definition)
        name = next((value for value in match.groups() if value), None) if match else None
        if name and name.lower() in column_names:
            parts[index] = re.sub(r"\s+NOT\s+NULL\b", "", definition, flags=re.IGNORECASE)
    return create_sql[: opening + 1] + ",".join(parts) + create_sql[closing:]


def _ensure_nullable_order_dates_and_status() -> None:
    """Transactionally align legacy SQLite ``orders`` nullability with the ORM.

    SQLite cannot drop a NOT NULL constraint in place.  Rebuilding only this
    table preserves the database and every order id; child tables are left in
    place while foreign-key enforcement is temporarily disabled.
    """
    inspector = inspect(engine)
    if engine.dialect.name != "sqlite" or "orders" not in inspector.get_table_names():
        return
    columns = {column["name"]: column for column in inspector.get_columns("orders")}
    targets = {
        name for name in ("shipment_date", "status")
        if name in columns and not columns[name]["nullable"]
    }
    if not targets:
        return

    temporary_table = "orders__nullable_migration"
    with engine.connect() as connection:
        foreign_keys = bool(connection.exec_driver_sql("PRAGMA foreign_keys").scalar())
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys = OFF")
        connection.commit()
        try:
            with connection.begin():
                connection.exec_driver_sql(f'DROP TABLE IF EXISTS "{temporary_table}"')
                create_sql = connection.execute(text(
                    "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'orders'"
                )).scalar_one()
                create_sql = _without_not_null(create_sql, targets)
                create_sql = re.sub(
                    r"^(\s*CREATE\s+TABLE\s+)(?:\"orders\"|`orders`|\[orders\]|orders)",
                    rf'\1"{temporary_table}"',
                    create_sql,
                    count=1,
                    flags=re.IGNORECASE,
                )
                indexes = connection.execute(text("""
                    SELECT sql FROM sqlite_master
                    WHERE type = 'index' AND tbl_name = 'orders' AND sql IS NOT NULL
                    ORDER BY name
                """)).scalars().all()
                column_list = ", ".join(f'"{name}"' for name in columns)
                connection.exec_driver_sql(create_sql)
                connection.exec_driver_sql(
                    f'INSERT INTO "{temporary_table}" ({column_list}) '
                    f'SELECT {column_list} FROM "orders"'
                )
                connection.exec_driver_sql('DROP TABLE "orders"')
                connection.exec_driver_sql(
                    f'ALTER TABLE "{temporary_table}" RENAME TO "orders"'
                )
                for index_sql in indexes:
                    connection.exec_driver_sql(index_sql)
                violations = connection.exec_driver_sql(
                    "PRAGMA foreign_key_check"
                ).all()
                if violations:
                    raise RuntimeError(
                        "orders migration failed foreign-key validation: "
                        f"{violations}"
                    )
        finally:
            connection.exec_driver_sql(
                f"PRAGMA foreign_keys = {'ON' if foreign_keys else 'OFF'}"
            )
            connection.commit()


def _ensure_nullable_conflict_shipment_date() -> None:
    """Allow conflicts for start-driven orders without inventing a deadline."""
    inspector = inspect(engine)
    if engine.dialect.name != "sqlite" or "planning_conflicts" not in inspector.get_table_names():
        return
    columns = {column["name"]: column for column in inspector.get_columns("planning_conflicts")}
    if columns.get("shipment_date", {}).get("nullable", True):
        return
    with engine.begin() as connection:
        sql = connection.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='planning_conflicts'"
        )).scalar_one()
        replacement = _without_not_null(sql, {"shipment_date"}).replace(
            "planning_conflicts", "planning_conflicts__nullable", 1
        )
        names = ", ".join(f'"{name}"' for name in columns)
        connection.exec_driver_sql("DROP TABLE IF EXISTS planning_conflicts__nullable")
        connection.exec_driver_sql(replacement)
        connection.exec_driver_sql(
            f"INSERT INTO planning_conflicts__nullable ({names}) SELECT {names} FROM planning_conflicts"
        )
        connection.exec_driver_sql("DROP TABLE planning_conflicts")
        connection.exec_driver_sql("ALTER TABLE planning_conflicts__nullable RENAME TO planning_conflicts")


def drop_all() -> None:
    """Drop all database tables. Intended for tests and local reset scripts."""
    Base.metadata.drop_all(bind=engine)


def get_session() -> Iterator[Session]:
    """Yield a database session and close it afterwards."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _ensure_work_center_workday_start_time_column() -> None:
    """Add configurable workday start time to existing SQLite databases."""
    inspector = inspect(engine)
    if "work_centers" not in inspector.get_table_names():
        return
    existing_columns = {
        column["name"] for column in inspector.get_columns("work_centers")
    }
    if "workday_start_time" in existing_columns:
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE work_centers "
                "ADD COLUMN workday_start_time TIME NOT NULL DEFAULT '09:00:00'"
            )
        )
        connection.execute(
            text(
                "UPDATE work_centers "
                "SET workday_start_time = COALESCE(workday_start_time, '09:00:00')"
            )
        )


def _ensure_work_center_prevent_order_interruption_column() -> None:
    """Add order-interruption protection flag to existing SQLite databases."""
    inspector = inspect(engine)
    if "work_centers" not in inspector.get_table_names():
        return
    existing_columns = {
        column["name"] for column in inspector.get_columns("work_centers")
    }
    if "prevent_order_interruption" in existing_columns:
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE work_centers "
                "ADD COLUMN prevent_order_interruption BOOLEAN NOT NULL DEFAULT 0"
            )
        )
        connection.execute(
            text(
                "UPDATE work_centers "
                "SET prevent_order_interruption = COALESCE(prevent_order_interruption, 0)"
            )
        )


def _ensure_route_prevent_order_interruption_column() -> None:
    """Add order-interruption protection flag to existing route rows."""
    inspector = inspect(engine)
    if "routes" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("routes")}
    if "prevent_order_interruption" in existing_columns:
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE routes "
                "ADD COLUMN prevent_order_interruption BOOLEAN NOT NULL DEFAULT 0"
            )
        )
        connection.execute(
            text(
                "UPDATE routes "
                "SET prevent_order_interruption = COALESCE(prevent_order_interruption, 0)"
            )
        )


def _ensure_planned_operation_day_intraday_columns() -> None:
    """Add intraday placement columns to existing SQLite databases."""
    inspector = inspect(engine)
    if "planned_operation_days" not in inspector.get_table_names():
        return
    existing_columns = {
        column["name"] for column in inspector.get_columns("planned_operation_days")
    }
    statements = []
    if "start_datetime" not in existing_columns:
        statements.append(
            "ALTER TABLE planned_operation_days ADD COLUMN start_datetime DATETIME"
        )
    if "end_datetime" not in existing_columns:
        statements.append(
            "ALTER TABLE planned_operation_days ADD COLUMN end_datetime DATETIME"
        )
    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        connection.execute(text("""
                UPDATE planned_operation_days
                SET
                    start_datetime = COALESCE(start_datetime, datetime(date || ' 09:00:00')),
                    end_datetime = COALESCE(end_datetime, datetime(date || ' 09:00:00', '+' || hours || ' hours'))
                """))



def _ensure_order_planning_columns() -> None:
    """Add planning-mode and child-order metadata to existing SQLite databases."""
    inspector = inspect(engine)
    if "orders" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("orders")}
    statements = []
    if "planning_mode" not in existing_columns:
        statements.append("ALTER TABLE orders ADD COLUMN planning_mode VARCHAR(50) NOT NULL DEFAULT 'От даты отгрузки'")
    if "fixed_start_date" not in existing_columns:
        statements.append("ALTER TABLE orders ADD COLUMN fixed_start_date DATE")
    if "child_group_key" not in existing_columns:
        statements.append("ALTER TABLE orders ADD COLUMN child_group_key VARCHAR(100)")
    if "child_sequence_number" not in existing_columns:
        statements.append("ALTER TABLE orders ADD COLUMN child_sequence_number INTEGER")
    if "is_child_order" not in existing_columns:
        statements.append("ALTER TABLE orders ADD COLUMN is_child_order BOOLEAN NOT NULL DEFAULT 0")
    if "is_linked_child_group" not in existing_columns:
        statements.append("ALTER TABLE orders ADD COLUMN is_linked_child_group BOOLEAN NOT NULL DEFAULT 0")
    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        connection.execute(
            text("""
                UPDATE orders
                SET planning_mode = COALESCE(planning_mode, :mode),
                    is_child_order = COALESCE(is_child_order, 0),
                    is_linked_child_group = COALESCE(is_linked_child_group, 0)
                """),
            {"mode": PLANNING_MODE_SHIPMENT},
        )


def _ensure_order_priority_column() -> None:
    """Add the structural priority column without repairing legacy values."""
    inspector = inspect(engine)
    if "orders" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("orders")}
    if "priority" not in existing_columns:
        # Zero remains visible as an invalid migration sentinel and must be
        # corrected explicitly by the user before a global recalculation.
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE orders ADD COLUMN priority INTEGER NOT NULL DEFAULT 0"))

def _migrate_legacy_conflict_order_status() -> None:
    """Convert legacy conflict status rows to new status plus conflict record."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "orders" not in tables:
        return
    with engine.begin() as connection:
        if "planning_conflicts" in tables:
            connection.execute(text("""
                    INSERT INTO planning_conflicts (
                        order_id, shipment_date, work_center_id, required_hours,
                        available_hours, deficit_hours, blocking_order_ids, reason, created_at
                    )
                    SELECT
                        orders.id, CASE WHEN orders.planning_mode = 'От даты запуска' THEN NULL ELSE orders.shipment_date END, NULL, 0, 0, 0, NULL,
                        'Заказ перенесён из устаревшего статуса конфликта планирования.',
                        CURRENT_TIMESTAMP
                    FROM orders
                    WHERE orders.status = 'Конфликт планирования'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM planning_conflicts
                          WHERE planning_conflicts.order_id = orders.id
                      )
                    """))
        connection.execute(
            text("""
                UPDATE orders
                SET status = :new_status, calculated_start_date = NULL
                WHERE status = 'Конфликт планирования'
                """),
            {"new_status": ""},
        )
