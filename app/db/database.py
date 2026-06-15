"""Database engine and session helpers for the production planner MVP."""

from collections.abc import Iterator

from sqlalchemy import create_engine
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
