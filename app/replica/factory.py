"""Montagem da replica local para a sessao atual do Desktop.

Desligada por padrao. No arquivo de configuracao:

* `"local_replica": {"enabled": true}` mantem o arquivo sincronizado;
* `"local_replica": {"enabled": true, "read": true}` tambem faz as telas ja
  migradas lerem dele (hoje: lista de Expedicao).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from app.replica.replica_db import ReplicaDatabase
from app.replica.sync_engine import ReplicaSyncEngine, SyncApiClient
from app.services.app_paths import get_app_data_dir, is_packaged

CONFIG_KEY = "local_replica"


def replica_enabled(config: dict[str, Any] | None) -> bool:
    section = (config or {}).get(CONFIG_KEY)
    return bool(isinstance(section, dict) and section.get("enabled"))


def replica_read_enabled(config: dict[str, Any] | None) -> bool:
    """Telas lendo da replica: exige a replica ligada E `"read": true`."""
    return replica_enabled(config) and bool((config or {})[CONFIG_KEY].get("read"))


def get_replica_dir() -> Path:
    override = os.environ.get("CONTROLE_PRODUCAO_REPLICA_DIR")
    if override:
        return Path(override)
    # Dados por usuario do Windows (nao ProgramData, que e compartilhado na maquina).
    local_app_data = os.environ.get("LOCALAPPDATA")
    if is_packaged() and local_app_data:
        return Path(local_app_data) / "ControleProducao" / "replica"
    return get_app_data_dir() / "replica"


def replica_identity(base_url: str, user_key: str) -> str:
    return f"{str(base_url).strip().rstrip('/').lower()}|{str(user_key).strip().lower()}"


def replica_path(identity: str) -> Path:
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return get_replica_dir() / f"replica_{digest}.db"


def build_replica_sync(service) -> tuple[ReplicaDatabase, ReplicaSyncEngine]:
    """Cria a replica e o motor de sync para o usuario logado em `service` (BackendService)."""
    storage = service.official_proposal_storage
    user = service.user or {}
    user_key = user.get("id") or user.get("login")
    if not user_key:
        raise RuntimeError("Replica local exige um usuario autenticado.")
    identity = replica_identity(storage.api_base_url(), str(user_key))
    database = ReplicaDatabase(replica_path(identity))
    engine = ReplicaSyncEngine(database, SyncApiClient(storage.sync_get_json), identity=identity)
    return database, engine
