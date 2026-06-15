"""Database initialization entry point."""

from app.db import models as _models  # noqa: F401
from app.db.database import create_all


def init_db() -> None:
    """Create the SQLite database schema."""
    create_all()


if __name__ == "__main__":
    init_db()
