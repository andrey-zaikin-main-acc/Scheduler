"""Application configuration."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SQLITE_PATH = DATA_DIR / "planner.sqlite3"
DATABASE_URL = f"sqlite:///{SQLITE_PATH}"
DEFAULT_FREE_SLOT_DAYS = 30
MAX_BACKWARD_SEARCH_MONTHS = 12
