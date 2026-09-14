"""Bootstrap helpers for local database setup and demo data."""

from threading import Lock

from sqlalchemy.orm import Session

from app.config import SQLITE_PATH
from app.db import database
from app.db.database import create_all
from app.db.seed_data import seed_demo_data


_initialization_lock = Lock()
_initialized_engine = None


def initialize_database() -> None:
    """Create the local SQLite schema."""
    create_all()


def initialize_database_once() -> None:
    """Initialize the schema once in this Streamlit/desktop process."""
    global _initialized_engine
    current_engine = database.engine
    if _initialized_engine is current_engine:
        return
    with _initialization_lock:
        current_engine = database.engine
        if _initialized_engine is current_engine:
            return
        initialize_database()
        # Failed initialization must remain retryable.
        _initialized_engine = current_engine


def load_demo_data(session: Session) -> None:
    """Load idempotent demo data into an initialized database."""
    seed_demo_data(session)


def initialize_desktop_database() -> None:
    """Create and seed the desktop database only on the first launch."""
    database_existed = SQLITE_PATH.exists()
    initialize_database_once()
    if database_existed:
        return
    from app.db.database import SessionLocal

    with SessionLocal() as session:
        seed_demo_data(session)
