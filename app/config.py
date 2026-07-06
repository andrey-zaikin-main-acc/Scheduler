"""Application configuration."""

import os
import sys
from pathlib import Path

APP_NAME = "DrawPPT"
BASE_DIR = Path(__file__).resolve().parent.parent
DEV_DATA_DIR = BASE_DIR / "data"


def is_frozen_app() -> bool:
    """Return True when the application runs from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def is_desktop_mode() -> bool:
    """Return True when desktop-specific paths should be used."""
    return is_frozen_app() or os.environ.get("DRAWPPT_DESKTOP") == "1"


def get_user_data_dir() -> Path:
    """Return the persistent per-user data directory for the desktop app."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_NAME
    return Path.home() / "AppData" / "Local" / APP_NAME


def get_data_dir() -> Path:
    """Return the directory where SQLite data should be stored."""
    if is_desktop_mode():
        return get_user_data_dir()
    return DEV_DATA_DIR


def get_sqlite_path() -> Path:
    """Return the SQLite database path for the current runtime mode."""
    return get_data_dir() / "planner.sqlite3"


DATA_DIR = get_data_dir()
SQLITE_PATH = get_sqlite_path()
DATABASE_URL = f"sqlite:///{SQLITE_PATH}"
DEFAULT_FREE_SLOT_DAYS = 30
MAX_BACKWARD_SEARCH_MONTHS = 12
