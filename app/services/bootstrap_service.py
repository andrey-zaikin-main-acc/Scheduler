"""Bootstrap helpers for local database setup and demo data."""

from sqlalchemy.orm import Session

from app.db.database import create_all
from app.db.seed_data import seed_demo_data


def initialize_database() -> None:
    """Create the local SQLite schema."""
    create_all()


def load_demo_data(session: Session) -> None:
    """Load idempotent demo data into an initialized database."""
    seed_demo_data(session)
