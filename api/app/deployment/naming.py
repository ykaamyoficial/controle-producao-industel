from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


def _slug(value: str) -> str:
    return _UNSAFE_CHARS.sub("-", value.strip()) or "unknown"


def build_deployment_id(*, kind: str, version: str, now: datetime | None = None) -> str:
    """Identificador legivel e unico de uma tentativa de deployment/rollback
    (mesmo padrao de api/app/backup/naming.py): timestamp UTC + versao alvo +
    sufixo aleatorio de 8 hex, para nunca colidir e nunca sobrescrever um
    registro anterior silenciosamente."""
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    timestamp = moment.strftime("%Y%m%dT%H%M%SZ")
    suffix = secrets.token_hex(4)
    return f"{_slug(kind)}_{timestamp}_v{_slug(version)}_{suffix}"
