"""Tests for development and desktop SQLite path selection."""

import importlib
import sys
from pathlib import Path

import app.config as config


def reload_config(monkeypatch, *, frozen: bool = False, desktop_env: str | None = None, localappdata: Path | None = None):
    """Reload app.config with controlled runtime flags."""
    if frozen:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
    else:
        monkeypatch.delattr(sys, "frozen", raising=False)
    if desktop_env is None:
        monkeypatch.delenv("DRAWPPT_DESKTOP", raising=False)
    else:
        monkeypatch.setenv("DRAWPPT_DESKTOP", desktop_env)
    if localappdata is None:
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
    else:
        monkeypatch.setenv("LOCALAPPDATA", str(localappdata))
    return importlib.reload(config)


def test_dev_mode_uses_repository_data_directory(monkeypatch):
    cfg = reload_config(monkeypatch)

    assert cfg.DATA_DIR == cfg.BASE_DIR / "data"
    assert cfg.SQLITE_PATH == cfg.BASE_DIR / "data" / "planner.sqlite3"
    assert cfg.DATABASE_URL.endswith("/data/planner.sqlite3")


def test_frozen_desktop_mode_uses_local_app_data(monkeypatch, tmp_path):
    cfg = reload_config(monkeypatch, frozen=True, localappdata=tmp_path)

    assert cfg.DATA_DIR == tmp_path / "DrawPPT"
    assert cfg.SQLITE_PATH == tmp_path / "DrawPPT" / "planner.sqlite3"
    assert cfg.DATABASE_URL == f"sqlite:///{tmp_path / 'DrawPPT' / 'planner.sqlite3'}"


def test_desktop_env_mode_uses_local_app_data(monkeypatch, tmp_path):
    cfg = reload_config(monkeypatch, desktop_env="1", localappdata=tmp_path)

    assert cfg.SQLITE_PATH == tmp_path / "DrawPPT" / "planner.sqlite3"
