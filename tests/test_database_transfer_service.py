from __future__ import annotations

import sqlite3
import os
from datetime import datetime, timezone

import pytest

from app.services.database_transfer_service import (
    DatabaseTransferError,
    REQUIRED_TABLES,
    export_database,
    import_database,
    rollback_available,
    rollback_last_import,
    validate_transfer_file,
)
from app.services import database_transfer_service


def _database(path, label: str) -> None:
    with sqlite3.connect(path) as connection:
        for table in sorted(REQUIRED_TABLES):
            if table == "orders":
                connection.execute(
                    "CREATE TABLE orders (id INTEGER PRIMARY KEY, label TEXT NOT NULL)"
                )
                connection.execute("INSERT INTO orders (label) VALUES (?)", (label,))
            else:
                connection.execute(
                    f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)'
                )
        connection.commit()


def _label(path) -> str:
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT label FROM orders").fetchone()[0]


def test_export_contains_author_timestamp_marker_and_complete_snapshot(tmp_path) -> None:
    current = tmp_path / "planner.sqlite3"
    _database(current, "saved plan")
    created_at = datetime(2026, 9, 16, 14, 5, 7, tzinfo=timezone.utc)

    exported = export_database(
        tmp_path,
        "Андрей Заикин",
        source_path=current,
        created_at=created_at,
    )

    local_stamp = created_at.astimezone().strftime("%Y-%m-%d_%H-%M-%S")
    assert exported.name == f"DrawPPT_{local_stamp}_Андрей_Заикин.drawppt"
    assert _label(exported) == "saved plan"
    metadata = validate_transfer_file(exported)
    assert metadata.author == "Андрей Заикин"
    assert metadata.created_at == created_at
    assert metadata.kind == "export"


def test_same_extension_sqlite_without_drawppt_marker_is_rejected(tmp_path) -> None:
    unrelated = tmp_path / "unrelated.drawppt"
    _database(unrelated, "not an export")

    with pytest.raises(DatabaseTransferError, match="служебная метка"):
        validate_transfer_file(unrelated)


def test_export_closes_sqlite_handles_before_atomic_rename(tmp_path, monkeypatch) -> None:
    current = tmp_path / "planner.sqlite3"
    _database(current, "saved plan")
    connections = []
    real_connect = sqlite3.connect
    real_replace = os.replace

    class TrackingConnection(sqlite3.Connection):
        closed = False

        def close(self) -> None:
            self.closed = True
            super().close()

    def tracking_connect(*args, **kwargs):
        kwargs["factory"] = TrackingConnection
        connection = real_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    def guarded_replace(source, destination):
        assert connections
        assert all(connection.closed for connection in connections)
        return real_replace(source, destination)

    monkeypatch.setattr(database_transfer_service.sqlite3, "connect", tracking_connect)
    monkeypatch.setattr(database_transfer_service.os, "replace", guarded_replace)

    exported = export_database(tmp_path, "Андрей", source_path=current)

    assert exported.is_file()
    assert all(connection.closed for connection in connections)


def test_import_replaces_everything_and_persistent_one_step_rollback_restores(tmp_path) -> None:
    current = tmp_path / "planner.sqlite3"
    colleague = tmp_path / "colleague.sqlite3"
    backup = tmp_path / "last_import_backup.drawppt"
    _database(current, "before import")
    _database(colleague, "from colleague")
    transfer = export_database(tmp_path, "Коллега", source_path=colleague)
    disposals = []

    metadata = import_database(
        transfer,
        current_path=current,
        backup_path=backup,
        dispose_connections=lambda: disposals.append("disposed"),
    )

    assert metadata.author == "Коллега"
    assert _label(current) == "from colleague"
    assert rollback_available(backup)
    assert disposals == ["disposed"]

    rollback_last_import(
        current_path=current,
        backup_path=backup,
        dispose_connections=lambda: disposals.append("disposed"),
    )

    assert _label(current) == "before import"
    assert not rollback_available(backup)
    assert disposals == ["disposed", "disposed"]


def test_failed_post_import_migration_automatically_restores_old_database(tmp_path) -> None:
    current = tmp_path / "planner.sqlite3"
    colleague = tmp_path / "colleague.sqlite3"
    backup = tmp_path / "last_import_backup.drawppt"
    _database(current, "safe original")
    _database(colleague, "bad replacement")
    transfer = export_database(tmp_path, "Коллега", source_path=colleague)
    calls = []

    def migration() -> None:
        calls.append("migrate")
        if len(calls) == 1:
            raise RuntimeError("simulated migration failure")

    with pytest.raises(DatabaseTransferError, match="автоматически восстановлены"):
        import_database(
            transfer,
            current_path=current,
            backup_path=backup,
            migrate_database=migration,
        )

    assert _label(current) == "safe original"
    assert not rollback_available(backup)
    assert calls == ["migrate", "migrate"]
