from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.services.app_logging import get_logger


log = get_logger("migrations")


MIGRATION_PATTERN = re.compile(r"^(?P<version>\d{3,})_(?P<name>[a-z0-9_]+)\.sql$")


class MigrationError(RuntimeError):
    """Raised when the database migration history is unsafe or incomplete."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path
    sql: str
    checksum: str


def default_migrations_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "app" / "migrations"


def _bootstrap_tracking_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version INTEGER NOT NULL UNIQUE,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            checksum TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _load_migrations(directory: Path) -> list[Migration]:
    if not directory.is_dir():
        raise MigrationError(f"Pasta de migracoes nao encontrada: {directory}")
    migrations: list[Migration] = []
    versions: set[int] = set()
    for path in sorted(directory.glob("*.sql")):
        match = MIGRATION_PATTERN.match(path.name)
        if not match:
            raise MigrationError(f"Nome de migracao invalido: {path.name}")
        version = int(match.group("version"))
        if version in versions:
            raise MigrationError(f"Versao de migracao duplicada: {version}")
        versions.add(version)
        raw = path.read_bytes()
        # Git may check out text files with CRLF on Windows. Migration
        # checksums must represent SQL content, not the local newline style.
        canonical = raw.replace(b"\r\n", b"\n")
        migrations.append(
            Migration(
                version=version,
                name=match.group("name"),
                path=path,
                sql=raw.decode("utf-8-sig"),
                checksum=hashlib.sha256(canonical).hexdigest(),
            )
        )
    if not migrations:
        raise MigrationError("Nenhuma migracao SQL foi encontrada.")
    return migrations


def _statements(script: str):
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            buffer = ""
            if statement:
                yield statement
    if buffer.strip():
        raise MigrationError("Migracao termina com uma instrucao SQL incompleta.")


def apply_migrations(
    conn: sqlite3.Connection,
    migrations_dir: str | Path | None = None,
) -> list[int]:
    """Apply pending migrations atomically and return applied versions."""
    directory = Path(migrations_dir) if migrations_dir else default_migrations_dir()
    _bootstrap_tracking_table(conn)
    migrations = _load_migrations(directory)
    applied_rows = conn.execute(
        "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
    ).fetchall()
    applied = {int(row[0]): (row[1], row[2]) for row in applied_rows}

    known_versions = {migration.version for migration in migrations}
    unknown = sorted(set(applied) - known_versions)
    if unknown:
        raise MigrationError(f"Banco contem migracoes desconhecidas: {unknown}")

    completed: list[int] = []
    for migration in migrations:
        previous = applied.get(migration.version)
        if previous:
            previous_name, previous_checksum = previous
            if previous_name != migration.name or previous_checksum != migration.checksum:
                raise MigrationError(
                    f"Migracao {migration.version:03d} foi alterada depois de aplicada."
                )
            continue
        try:
            conn.execute("BEGIN IMMEDIATE")
            for statement in _statements(migration.sql):
                conn.execute(statement)
            conn.execute(
                """
                INSERT INTO schema_migrations(version, name, applied_at, checksum)
                VALUES (?, ?, ?, ?)
                """,
                (
                    migration.version,
                    migration.name,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    migration.checksum,
                ),
            )
            conn.commit()
        except (OSError, UnicodeError, sqlite3.Error, MigrationError) as exc:
            conn.rollback()
            raise MigrationError(
                f"Falha ao aplicar migracao {migration.version:03d}_{migration.name}."
            ) from exc
        completed.append(migration.version)
        log.info("Migracao aplicada | versao=%03d | nome=%s", migration.version, migration.name)
    return completed


def migration_status(
    conn: sqlite3.Connection,
    migrations_dir: str | Path | None = None,
) -> list[dict[str, object]]:
    directory = Path(migrations_dir) if migrations_dir else default_migrations_dir()
    _bootstrap_tracking_table(conn)
    applied = {
        int(row[0]): (row[1], row[2], row[3])
        for row in conn.execute(
            "SELECT version, name, checksum, applied_at FROM schema_migrations"
        )
    }
    return [
        {
            "version": migration.version,
            "name": migration.name,
            "applied": migration.version in applied,
            "applied_at": applied.get(migration.version, (None, None, None))[2],
            "checksum": migration.checksum,
        }
        for migration in _load_migrations(directory)
    ]
