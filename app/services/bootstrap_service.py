"""Bootstrap helpers for local database setup and demo data."""

from sqlalchemy.orm import Session

from app.config import SQLITE_PATH
from app.db.database import create_all
from app.db.seed_data import seed_demo_data


def initialize_database() -> None:
    """Create the local SQLite schema."""
    create_all()


def load_demo_data(session: Session) -> None:
    """Load idempotent demo data into an initialized database."""
    seed_demo_data(session)


def initialize_desktop_database() -> None:
    """Create and seed the desktop database only on the first launch."""
    database_existed = SQLITE_PATH.exists()
    create_all()
    if database_existed:
        return
    from app.db.database import SessionLocal

    with SessionLocal() as session:
        seed_demo_data(session)
