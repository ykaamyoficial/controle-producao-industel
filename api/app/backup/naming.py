from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


def _slug(value: str) -> str:
    return _UNSAFE_CHARS.sub("-", value.strip()) or "unknown"


def build_backup_id(*, server_version: str, database_revision: str, now: datetime | None = None) -> str:
    """Nome legivel e unico (Secao 9). A identidade oficial de um backup e o
    backup_id (nunca o nome de arquivo isolado): inclui timestamp UTC + versao +
    revisao + um sufixo aleatorio de 8 hex, para nunca colidir e nunca sobrescrever
    um backup anterior silenciosamente (nunca gera 'backup.dump'/'ultimo.dump')."""
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    timestamp = moment.strftime("%Y%m%dT%H%M%SZ")
    suffix = secrets.token_hex(4)
    return f"predeploy_{timestamp}_server-{_slug(server_version)}_db-rev{_slug(database_revision)}_{suffix}"


def dump_filename(backup_id: str) -> str:
    return f"{backup_id}.dump"


def manifest_filename(backup_id: str) -> str:
    return f"{backup_id}.manifest.json"
