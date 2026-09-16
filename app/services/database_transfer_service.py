"""Safe whole-database exchange for DrawPPT desktop installations."""

from __future__ import annotations

import os
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable
from uuid import uuid4

from app.config import DATA_DIR, SQLITE_PATH


TRANSFER_EXTENSION = ".drawppt"
TRANSFER_MARKER = "DrawPPT database transfer"
TRANSFER_FORMAT_VERSION = 1
METADATA_TABLE = "_drawppt_transfer_metadata"
ROLLBACK_FILE_NAME = "last_import_backup.drawppt"
REQUIRED_TABLES = frozenset({
    "orders",
    "work_centers",
    "routes",
    "route_operations",
    "planned_operations",
    "planned_operation_days",
    "planning_conflicts",
    "recalculation_runs",
    "plan_changes",
    "settings",
})


class DatabaseTransferError(RuntimeError):
    """Raised when an exchange file is invalid or cannot be applied safely."""


@dataclass(frozen=True)
class TransferMetadata:
    author: str
    created_at: datetime
    kind: str
    format_version: int


def rollback_file_path(data_dir: Path | None = None) -> Path:
    return (data_dir or DATA_DIR) / ROLLBACK_FILE_NAME


def _rollback_state_path(backup_path: Path) -> Path:
    return backup_path.with_suffix(f"{backup_path.suffix}.state")


def _write_rollback_state(backup_path: Path, state: str) -> None:
    state_path = _rollback_state_path(backup_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_name(f".{state_path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(state, encoding="utf-8")
        os.replace(temporary, state_path)
    finally:
        temporary.unlink(missing_ok=True)


def sanitize_author_for_filename(author: str) -> str:
    """Return a readable author fragment that is safe on Windows filesystems."""
    normalized = unicodedata.normalize("NFKC", author).strip()
    normalized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", normalized)
    normalized = re.sub(r"\s+", "_", normalized).strip(" ._")
    return normalized[:60]


def build_export_filename(author: str, created_at: datetime) -> str:
    safe_author = sanitize_author_for_filename(author)
    if not safe_author:
        raise DatabaseTransferError("Укажите автора выгрузки.")
    timestamp = created_at.astimezone().strftime("%Y-%m-%d_%H-%M-%S")
    return f"DrawPPT_{timestamp}_{safe_author}{TRANSFER_EXTENSION}"


def _unique_destination(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    for index in range(2, 10_000):
        candidate = directory / f"{stem}_{index}{TRANSFER_EXTENSION}"
        if not candidate.exists():
            return candidate
    raise DatabaseTransferError("Не удалось подобрать свободное имя файла выгрузки.")


def _connect_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _check_database_integrity(connection: sqlite3.Connection) -> None:
    result = connection.execute("PRAGMA quick_check").fetchall()
    if result != [("ok",)]:
        raise DatabaseTransferError("Файл данных повреждён: проверка SQLite не пройдена.")
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise DatabaseTransferError(
            "В файле данных нарушены связи между таблицами DrawPPT."
        )


def _validate_schema(connection: sqlite3.Connection) -> None:
    missing = sorted(REQUIRED_TABLES - _table_names(connection))
    if missing:
        raise DatabaseTransferError(
            "Файл не содержит полный набор данных DrawPPT. "
            f"Отсутствуют таблицы: {', '.join(missing)}."
        )


def _read_metadata(connection: sqlite3.Connection) -> TransferMetadata:
    if METADATA_TABLE not in _table_names(connection):
        raise DatabaseTransferError(
            "Выбранный файл не является выгрузкой DrawPPT: отсутствует служебная метка."
        )
    row = connection.execute(
        f'SELECT marker, format_version, kind, created_at, author '
        f'FROM "{METADATA_TABLE}" WHERE id = 1'
    ).fetchone()
    if row is None or row[0] != TRANSFER_MARKER:
        raise DatabaseTransferError(
            "Выбранный файл не является выгрузкой DrawPPT: служебная метка неверна."
        )
    version = int(row[1])
    if version != TRANSFER_FORMAT_VERSION:
        raise DatabaseTransferError(
            f"Версия файла DrawPPT ({version}) не поддерживается этой программой."
        )
    try:
        created_at = datetime.fromisoformat(str(row[3]))
    except (TypeError, ValueError) as exc:
        raise DatabaseTransferError("В файле указана некорректная дата выгрузки.") from exc
    author = str(row[4]).strip()
    if not author:
        raise DatabaseTransferError("В файле не указан автор выгрузки.")
    return TransferMetadata(
        author=author,
        created_at=created_at,
        kind=str(row[2]),
        format_version=version,
    )


def validate_transfer_file(
    path: str | Path,
    *,
    allowed_kinds: Iterable[str] = ("export",),
    require_extension: bool = True,
) -> TransferMetadata:
    """Validate file identity, format, schema, integrity and metadata."""
    candidate = Path(path)
    if not candidate.is_file():
        raise DatabaseTransferError("Выбранный файл не найден.")
    if require_extension and candidate.suffix.lower() != TRANSFER_EXTENSION:
        raise DatabaseTransferError(
            f"Нужен файл выгрузки DrawPPT с расширением {TRANSFER_EXTENSION}."
        )
    try:
        with _connect_read_only(candidate) as connection:
            _check_database_integrity(connection)
            _validate_schema(connection)
            metadata = _read_metadata(connection)
    except DatabaseTransferError:
        raise
    except sqlite3.DatabaseError as exc:
        raise DatabaseTransferError(
            "Выбранный файл не является исправной базой данных DrawPPT."
        ) from exc
    if metadata.kind not in set(allowed_kinds):
        raise DatabaseTransferError("Этот служебный файл нельзя использовать для загрузки.")
    return metadata


def _stamp_metadata(
    path: Path, *, kind: str, author: str, created_at: datetime
) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(f'DROP TABLE IF EXISTS "{METADATA_TABLE}"')
        connection.execute(f'''CREATE TABLE "{METADATA_TABLE}" (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            marker TEXT NOT NULL,
            format_version INTEGER NOT NULL,
            kind TEXT NOT NULL,
            created_at TEXT NOT NULL,
            author TEXT NOT NULL
        )''')
        connection.execute(
            f'INSERT INTO "{METADATA_TABLE}" '
            '(id, marker, format_version, kind, created_at, author) '
            'VALUES (1, ?, ?, ?, ?, ?)',
            (
                TRANSFER_MARKER,
                TRANSFER_FORMAT_VERSION,
                kind,
                created_at.isoformat(timespec="seconds"),
                author,
            ),
        )
        connection.commit()


def _copy_sqlite_database(source: Path, destination: Path) -> None:
    """Create a transactionally consistent SQLite snapshot."""
    if not source.is_file():
        raise DatabaseTransferError("Текущая база данных DrawPPT не найдена.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _connect_read_only(source) as source_connection:
        with sqlite3.connect(destination) as destination_connection:
            source_connection.backup(destination_connection)


def _snapshot_with_metadata(
    source: Path,
    destination: Path,
    *,
    kind: str,
    author: str,
    created_at: datetime,
) -> None:
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        _copy_sqlite_database(source, temporary)
        _stamp_metadata(temporary, kind=kind, author=author, created_at=created_at)
        validate_transfer_file(
            temporary, allowed_kinds=(kind,), require_extension=False
        )
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def export_database(
    destination_directory: str | Path,
    author: str,
    *,
    source_path: str | Path | None = None,
    created_at: datetime | None = None,
) -> Path:
    """Export the complete saved database to a marked DrawPPT file."""
    directory = Path(destination_directory)
    if not directory.is_dir():
        raise DatabaseTransferError("Выбранная папка не существует.")
    exact_author = author.strip()
    moment = created_at or datetime.now().astimezone()
    destination = _unique_destination(
        directory, build_export_filename(exact_author, moment)
    )
    _snapshot_with_metadata(
        Path(source_path or SQLITE_PATH),
        destination,
        kind="export",
        author=exact_author,
        created_at=moment,
    )
    return destination


def _validate_live_database(path: Path) -> None:
    if not path.is_file():
        raise DatabaseTransferError("Текущая база данных DrawPPT не найдена.")
    try:
        with _connect_read_only(path) as connection:
            _check_database_integrity(connection)
            _validate_schema(connection)
    except DatabaseTransferError:
        raise
    except sqlite3.DatabaseError as exc:
        raise DatabaseTransferError("Текущая база данных DrawPPT повреждена.") from exc


def _atomic_replace_from_snapshot(source: Path, destination: Path) -> None:
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        _copy_sqlite_database(source, temporary)
        _validate_live_database(temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def import_database(
    transfer_file: str | Path,
    *,
    current_path: str | Path | None = None,
    backup_path: str | Path | None = None,
    dispose_connections: Callable[[], None] | None = None,
    migrate_database: Callable[[], None] | None = None,
) -> TransferMetadata:
    """Replace the live database, preserving a mandatory one-step rollback."""
    source = Path(transfer_file)
    metadata = validate_transfer_file(source)
    current = Path(current_path or SQLITE_PATH)
    backup = Path(backup_path or rollback_file_path(current.parent))
    _validate_live_database(current)
    _snapshot_with_metadata(
        current,
        backup,
        kind="rollback",
        author="DrawPPT",
        created_at=datetime.now().astimezone(),
    )
    _write_rollback_state(backup, "available")
    if dispose_connections:
        dispose_connections()
    try:
        _atomic_replace_from_snapshot(source, current)
        if migrate_database:
            migrate_database()
        _validate_live_database(current)
    except Exception as exc:
        if dispose_connections:
            dispose_connections()
        try:
            _atomic_replace_from_snapshot(backup, current)
            if migrate_database:
                migrate_database()
        except Exception as rollback_exc:
            raise DatabaseTransferError(
                "Загрузка не завершена, автоматическое восстановление также не удалось."
            ) from rollback_exc
        _write_rollback_state(backup, "used")
        if isinstance(exc, DatabaseTransferError):
            raise
        raise DatabaseTransferError(
            "Загрузка не завершена; прежние данные автоматически восстановлены."
        ) from exc
    return metadata


def rollback_available(backup_path: str | Path | None = None) -> bool:
    backup = Path(backup_path or rollback_file_path())
    state_path = _rollback_state_path(backup)
    if not backup.is_file() or not state_path.is_file():
        return False
    try:
        if state_path.read_text(encoding="utf-8").strip() != "available":
            return False
        validate_transfer_file(
            backup, allowed_kinds=("rollback",), require_extension=False
        )
    except (OSError, DatabaseTransferError):
        return False
    return True


def rollback_last_import(
    *,
    current_path: str | Path | None = None,
    backup_path: str | Path | None = None,
    dispose_connections: Callable[[], None] | None = None,
    migrate_database: Callable[[], None] | None = None,
) -> None:
    """Restore the state preceding the last successful import exactly once."""
    current = Path(current_path or SQLITE_PATH)
    backup = Path(backup_path or rollback_file_path(current.parent))
    if not rollback_available(backup):
        raise DatabaseTransferError("Нет доступной загрузки для отмены.")
    emergency = current.with_name(f".{current.name}.{uuid4().hex}.before-rollback")
    try:
        _copy_sqlite_database(current, emergency)
        if dispose_connections:
            dispose_connections()
        try:
            _atomic_replace_from_snapshot(backup, current)
            if migrate_database:
                migrate_database()
            _validate_live_database(current)
        except Exception as exc:
            if dispose_connections:
                dispose_connections()
            _atomic_replace_from_snapshot(emergency, current)
            if migrate_database:
                migrate_database()
            raise DatabaseTransferError(
                "Откат не завершён; данные, загруженные последними, сохранены."
            ) from exc
        _write_rollback_state(backup, "used")
    finally:
        emergency.unlink(missing_ok=True)


def choose_export_directory() -> Path | None:
    """Open the native directory picker used by the Windows desktop build."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        raise DatabaseTransferError("Системное окно выбора папки недоступно.") from exc
    root = tk.Tk()
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
        selected = filedialog.askdirectory(title="Куда выгрузить данные DrawPPT")
    finally:
        root.destroy()
    return Path(selected) if selected else None


def choose_import_file() -> Path | None:
    """Open the native picker, allowing both filtered and all-file views."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        raise DatabaseTransferError("Системное окно выбора файла недоступно.") from exc
    root = tk.Tk()
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
        selected = filedialog.askopenfilename(
            title="Выберите файл данных DrawPPT",
            filetypes=(
                ("Данные DrawPPT", f"*{TRANSFER_EXTENSION}"),
                ("Все файлы", "*.*"),
            ),
        )
    finally:
        root.destroy()
    return Path(selected) if selected else None
