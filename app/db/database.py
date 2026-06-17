"""Database engine and session helpers for the production planner MVP."""

from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATA_DIR, DATABASE_URL


class Base(DeclarativeBase):
    """Base class for SQLAlchemy ORM models."""


engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def ensure_data_dir() -> None:
    """Create the local data directory used by SQLite if it does not exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def create_all() -> None:
    """Create all database tables."""
    ensure_data_dir()
    Base.metadata.create_all(bind=engine)
    _ensure_planned_operation_day_intraday_columns()


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


def _ensure_planned_operation_day_intraday_columns() -> None:
    """Add intraday placement columns to existing SQLite databases."""
    inspector = inspect(engine)
    if "planned_operation_days" not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns("planned_operation_days")}
    statements = []
    if "start_datetime" not in existing_columns:
        statements.append("ALTER TABLE planned_operation_days ADD COLUMN start_datetime DATETIME")
    if "end_datetime" not in existing_columns:
        statements.append("ALTER TABLE planned_operation_days ADD COLUMN end_datetime DATETIME")
    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
        connection.execute(
            text(
                """
                UPDATE planned_operation_days
                SET
                    start_datetime = COALESCE(start_datetime, datetime(date || ' 09:00:00')),
                    end_datetime = COALESCE(end_datetime, datetime(date || ' 09:00:00', '+' || hours || ' hours'))
                """
            )
        )
