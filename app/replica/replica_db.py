"""Replica local (SQLite) dos dados operacionais, somente leitura para as telas.

A fonte da verdade continua sendo a API/PostgreSQL. Este arquivo e um cache
descartavel: nunca e migrado, so recriado. Qualquer divergencia de layout,
de `schema_version` do servidor ou de identidade (servidor/usuario) apaga
tudo e forca uma nova carga inicial.

Cada entidade vira uma tabela `(id, <colunas indexadas>, data)`: `data` guarda
a linha inteira em JSON, como veio da API, e as colunas indexadas (ver
`INDEXED_COLUMNS`) existem so para filtrar/juntar rapido. Coluna nova no
servidor aparece sozinha em `data`, sem quebrar o Desktop.

Quem grava aqui e apenas o motor de sincronizacao (`sync_engine.py`).
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from app.services.app_logging import get_logger

log = get_logger("replica_db")

# Subir quando INDEXED_COLUMNS ou o formato das tabelas mudar.
LOCAL_LAYOUT_VERSION = 1

INDEXED_COLUMNS: dict[str, tuple[str, ...]] = {
    "proposals": ("proposal_number", "current_area", "current_status", "parent_proposal_id", "active", "updated_at"),
    "proposal_items": ("proposal_id",),
    "galvanization_loads": (),
    "galvanization_load_items": ("load_id", "proposal_id", "proposal_item_id"),
    "expedition_items": ("proposal_id", "proposal_item_id"),
    "fiscal_records": ("proposal_id",),
    "fiscal_items": ("fiscal_record_id", "proposal_id", "proposal_item_id"),
    "fiscal_invoices": ("fiscal_record_id", "proposal_id"),
    "fiscal_invoice_items": ("fiscal_invoice_id", "fiscal_item_id", "proposal_id", "proposal_item_id"),
}

_META_TABLE = "replica_meta"
_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,59}$")

META_LAYOUT = "layout_version"
META_SCHEMA = "schema_version"
META_IDENTITY = "identity"
META_ENTITIES = "entities"
META_CURSOR = "cursor_seq"
META_LAST_SYNC = "last_sync_at"
META_LAST_FULL_SYNC = "last_full_sync_at"


def _check_name(name: str) -> str:
    if not _NAME_PATTERN.match(name) or name == _META_TABLE:
        raise ValueError(f"Nome de entidade invalido para a replica: {name!r}")
    return name


def _indexed(entity: str) -> tuple[str, ...]:
    return INDEXED_COLUMNS.get(entity, ())


def _index_value(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


class ReplicaDatabase:
    """Acesso ao arquivo da replica. Seguro entre threads: uma conexao curta por operacao."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._write_lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_layout()

    # ---- conexao ------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
        except BaseException:
            # No Windows, conexao aberta impede apagar/recriar um arquivo corrompido.
            connection.close()
            raise
        return connection

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    # ---- layout -------------------------------------------------------------
    def _ensure_layout(self) -> None:
        try:
            with self._read() as connection:
                connection.execute(f"CREATE TABLE IF NOT EXISTS {_META_TABLE} (key TEXT PRIMARY KEY, value TEXT)")
            stored = self.get_meta(META_LAYOUT)
        except sqlite3.DatabaseError:
            log.warning("replica_corrupted_recreating path=%s", self.path)
            self._delete_file()
            stored = None
        if stored != str(LOCAL_LAYOUT_VERSION):
            if stored is not None:
                log.info("replica_layout_changed from=%s to=%s", stored, LOCAL_LAYOUT_VERSION)
            self.reset()

    def _delete_file(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            Path(str(self.path) + suffix).unlink(missing_ok=True)

    def _drop_all(self, connection: sqlite3.Connection) -> None:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            connection.execute(f'DROP TABLE IF EXISTS "{table}"')
        connection.execute(f"CREATE TABLE {_META_TABLE} (key TEXT PRIMARY KEY, value TEXT)")
        connection.execute(f"INSERT INTO {_META_TABLE} (key, value) VALUES (?, ?)", (META_LAYOUT, str(LOCAL_LAYOUT_VERSION)))

    def _ensure_table(self, connection: sqlite3.Connection, entity: str) -> None:
        _check_name(entity)
        columns = "".join(f', "{column}"' for column in _indexed(entity))
        connection.execute(f'CREATE TABLE IF NOT EXISTS "{entity}" (id INTEGER PRIMARY KEY{columns}, data TEXT NOT NULL)')
        for column in _indexed(entity):
            connection.execute(f'CREATE INDEX IF NOT EXISTS "ix_{entity}_{column}" ON "{entity}" ("{column}")')

    def _upsert(self, connection: sqlite3.Connection, entity: str, rows: Iterable[dict[str, Any]]) -> None:
        indexed = _indexed(entity)
        names = "".join(f', "{column}"' for column in indexed)
        marks = ", ?" * len(indexed)
        connection.executemany(
            f'INSERT OR REPLACE INTO "{entity}" (id{names}, data) VALUES (?{marks}, ?)',
            [
                (int(row["id"]), *(_index_value(row.get(column)) for column in indexed), json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                for row in rows
            ],
        )

    @staticmethod
    def _set_meta(connection: sqlite3.Connection, values: dict[str, Any]) -> None:
        connection.executemany(
            f"INSERT OR REPLACE INTO {_META_TABLE} (key, value) VALUES (?, ?)",
            [(key, None if value is None else str(value)) for key, value in values.items()],
        )

    # ---- escrita (so o motor de sincronizacao) ------------------------------
    def reset(self) -> None:
        """Apaga tudo: a proxima sincronizacao faz a carga inicial."""
        with self._write() as connection:
            self._drop_all(connection)

    def replace_all(self, *, tables: dict[str, list[dict[str, Any]]], meta: dict[str, Any]) -> None:
        """Troca atomica do conteudo inteiro (carga inicial). Leitores veem o estado antigo ate o commit."""
        with self._write() as connection:
            self._drop_all(connection)
            for entity, rows in tables.items():
                self._ensure_table(connection, entity)
                self._upsert(connection, entity, rows)
            self._set_meta(connection, meta)

    def apply_changes(self, changes: list[dict[str, Any]], *, cursor: int, meta: dict[str, Any] | None = None) -> set[str]:
        """Aplica uma pagina de mudancas e avanca o cursor na MESMA transacao."""
        touched: set[str] = set()
        with self._write() as connection:
            for change in changes:
                entity = change["entity"]
                self._ensure_table(connection, entity)
                if change.get("op") == "delete" or change.get("row") is None:
                    connection.execute(f'DELETE FROM "{entity}" WHERE id = ?', (int(change["id"]),))
                else:
                    self._upsert(connection, entity, [change["row"]])
                touched.add(entity)
            # Outra instancia do app no mesmo usuario pode ter avancado mais: nunca regride.
            current = connection.execute(f"SELECT value FROM {_META_TABLE} WHERE key = ?", (META_CURSOR,)).fetchone()
            previous = int(current[0]) if current and current[0] is not None else 0
            self._set_meta(connection, {**(meta or {}), META_CURSOR: max(previous, int(cursor))})
        return touched

    # ---- leitura ------------------------------------------------------------
    def get_meta(self, key: str) -> str | None:
        with self._read() as connection:
            row = connection.execute(f"SELECT value FROM {_META_TABLE} WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def cursor(self) -> int | None:
        value = self.get_meta(META_CURSOR)
        return int(value) if value is not None else None

    def entities(self) -> list[str]:
        with self._read() as connection:
            rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name <> ? ORDER BY name", (_META_TABLE,))
            return [row[0] for row in rows]

    def _has_table(self, connection: sqlite3.Connection, entity: str) -> bool:
        return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (_check_name(entity),)).fetchone() is not None

    def count(self, entity: str) -> int:
        with self._read() as connection:
            if not self._has_table(connection, entity):
                return 0
            return int(connection.execute(f'SELECT COUNT(*) FROM "{entity}"').fetchone()[0])

    def get(self, entity: str, row_id: int) -> dict[str, Any] | None:
        with self._read() as connection:
            if not self._has_table(connection, entity):
                return None
            row = connection.execute(f'SELECT data FROM "{entity}" WHERE id = ?', (int(row_id),)).fetchone()
        return json.loads(row[0]) if row else None

    def find(self, entity: str, **filters: Any) -> list[dict[str, Any]]:
        """Linhas da entidade filtradas por igualdade em colunas indexadas, ordenadas por id.

        Um valor de filtro pode ser uma lista/tupla/conjunto (vira `IN`).
        """
        indexed = _indexed(entity)
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in filters.items():
            if column != "id" and column not in indexed:
                raise ValueError(f"Coluna nao indexada na replica: {entity}.{column}")
            if isinstance(value, (list, tuple, set, frozenset)):
                values = [_index_value(item) for item in value]
                if not values:
                    return []
                clauses.append(f'"{column}" IN ({", ".join("?" * len(values))})')
                params.extend(values)
            elif value is None:
                clauses.append(f'"{column}" IS NULL')
            else:
                clauses.append(f'"{column}" = ?')
                params.append(_index_value(value))
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._read() as connection:
            if not self._has_table(connection, entity):
                return []
            rows = connection.execute(f'SELECT data FROM "{entity}"{where} ORDER BY id', params).fetchall()
        return [json.loads(row[0]) for row in rows]
