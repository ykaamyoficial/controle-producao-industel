"""Motor de sincronizacao da replica local (sem Qt, sem thread propria).

Fala com os endpoints `/api/v1/sync/*` (ver `api/app/modules/sync/service.py`)
e grava em `ReplicaDatabase`. Quem decide QUANDO sincronizar e
`sync_agent.ReplicaSyncAgent`.

* Carga inicial: le o `seq` do servidor, baixa todas as entidades para a
  memoria e troca o conteudo da replica numa transacao so; depois segue pelo
  incremental a partir do `seq` lido no inicio.
* Incremental: pede o que veio depois do cursor local ate `has_more=false`.
  Um Desktop que ficou desligado na versao 1 com o servidor na 5 recebe
  2, 3, 4 e 5 aqui.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlencode

from app.replica.replica_db import (
    META_CURSOR,
    META_ENTITIES,
    META_IDENTITY,
    META_LAST_FULL_SYNC,
    META_LAST_SYNC,
    META_SCHEMA,
    ReplicaDatabase,
)
from app.services.app_logging import get_logger

log = get_logger("replica_sync")

SNAPSHOT_PAGE_SIZE = 1000
CHANGES_PAGE_SIZE = 500
# Protecao contra servidor que nunca devolve has_more=false.
MAX_PAGES_PER_SYNC = 2000

MODE_NOOP = "noop"
MODE_INCREMENTAL = "incremental"
MODE_BOOTSTRAP = "bootstrap"


class ReplicaSyncError(RuntimeError):
    pass


@dataclass
class SyncResult:
    mode: str = MODE_NOOP
    seq: int = 0
    changed_entities: set[str] = field(default_factory=set)
    applied_changes: int = 0
    bootstrap_reason: str | None = None


class SyncApiClient:
    """Chamadas HTTP do sync. `get_json(path)` devolve o corpo ja decodificado e autenticado."""

    def __init__(self, get_json: Callable[[str], Any]):
        self._get_json = get_json

    def head(self) -> dict[str, Any]:
        return self._get_json("/api/v1/sync/head")

    def changes(self, since: int, limit: int = CHANGES_PAGE_SIZE) -> dict[str, Any]:
        return self._get_json("/api/v1/sync/changes?" + urlencode({"since": int(since), "limit": int(limit)}))

    def snapshot(self, entity: str, after_id: int, limit: int = SNAPSHOT_PAGE_SIZE) -> dict[str, Any]:
        return self._get_json("/api/v1/sync/snapshot?" + urlencode({"entity": entity, "after_id": int(after_id), "limit": int(limit)}))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReplicaSyncEngine:
    def __init__(self, database: ReplicaDatabase, api: SyncApiClient, *, identity: str):
        self.database = database
        self.api = api
        # Servidor + usuario: outra pessoa (ou outro servidor) nunca herda a replica.
        self.identity = identity
        self._lock = threading.Lock()

    def sync_once(self) -> SyncResult:
        """Deixa a replica em dia. Uma chamada por vez; a segunda concorrente vira noop."""
        if not self._lock.acquire(blocking=False):
            return SyncResult(mode=MODE_NOOP, seq=self.database.cursor() or 0)
        try:
            return self._sync()
        finally:
            self._lock.release()

    # ---- decisao ------------------------------------------------------------
    def _bootstrap_reason(self, head: dict[str, Any]) -> str | None:
        database = self.database
        if database.cursor() is None:
            return "replica_vazia"
        if database.get_meta(META_IDENTITY) != self.identity:
            return "identidade_mudou"
        if database.get_meta(META_SCHEMA) != str(head["schema_version"]):
            return "schema_version_mudou"
        # Permissoes mudaram: entidades a mais precisam de carga, a menos precisam sumir.
        if database.get_meta(META_ENTITIES) != ",".join(head["entities"]):
            return "entidades_mudaram"
        return None

    def _sync(self) -> SyncResult:
        head = self.api.head()
        result = SyncResult()
        reason = self._bootstrap_reason(head)
        if reason:
            self._bootstrap(head, reason, result)
        self._incremental(result)
        if result.mode != MODE_NOOP:
            log.info(
                "replica_sync.done mode=%s seq=%s applied=%s entities=%s reason=%s",
                result.mode, result.seq, result.applied_changes, sorted(result.changed_entities), result.bootstrap_reason,
            )
        return result

    # ---- carga inicial ------------------------------------------------------
    def _bootstrap(self, head: dict[str, Any], reason: str, result: SyncResult) -> None:
        log.info("replica_sync.bootstrap_started reason=%s head_seq=%s", reason, head["seq"])
        tables: dict[str, list[dict[str, Any]]] = {}
        for entity in head["entities"]:
            rows: list[dict[str, Any]] = []
            after_id = 0
            for _ in range(MAX_PAGES_PER_SYNC):
                page = self.api.snapshot(entity, after_id)
                if str(page["schema_version"]) != str(head["schema_version"]):
                    raise ReplicaSyncError("schema_version mudou durante a carga inicial; tente novamente.")
                rows.extend(page["rows"])
                after_id = page["next_after_id"]
                if not page["has_more"]:
                    break
            else:
                raise ReplicaSyncError(f"Carga inicial de {entity} nao terminou.")
            tables[entity] = rows
        now = _now()
        self.database.replace_all(
            tables=tables,
            meta={
                META_IDENTITY: self.identity,
                META_SCHEMA: head["schema_version"],
                META_ENTITIES: ",".join(head["entities"]),
                # seq lido ANTES dos snapshots: o incremental reaplica o que mudou durante a carga.
                META_CURSOR: int(head["seq"]),
                META_LAST_SYNC: now,
                META_LAST_FULL_SYNC: now,
            },
        )
        result.mode = MODE_BOOTSTRAP
        result.bootstrap_reason = reason
        result.seq = int(head["seq"])
        result.changed_entities.update(tables)

    # ---- incremental --------------------------------------------------------
    def _incremental(self, result: SyncResult) -> None:
        for _ in range(MAX_PAGES_PER_SYNC):
            cursor = self.database.cursor() or 0
            page = self.api.changes(cursor)
            if page["resync_required"] or str(page["schema_version"]) != self.database.get_meta(META_SCHEMA):
                if result.mode == MODE_BOOTSTRAP:
                    raise ReplicaSyncError("Servidor pediu nova carga logo apos uma carga inicial.")
                self._bootstrap(self.api.head(), "resync_exigido", result)
                continue
            changes = page["changes"]
            next_seq = int(page["next_seq"])
            if changes or next_seq != cursor:
                touched = self.database.apply_changes(changes, cursor=next_seq, meta={META_LAST_SYNC: _now()})
                result.changed_entities.update(touched)
                result.applied_changes += len(changes)
                if changes and result.mode == MODE_NOOP:
                    result.mode = MODE_INCREMENTAL
            result.seq = max(next_seq, cursor)
            if not page["has_more"]:
                return
        raise ReplicaSyncError("Sincronizacao incremental nao terminou.")
