from __future__ import annotations

import secrets
from datetime import datetime, timezone


def build_maintenance_id(*, now: datetime | None = None) -> str:
    """Identificador legivel e unico de uma janela/incidente de manutencao
    (Secao 6: "maintenance_id deve identificar uma janela/incidente
    especifico"). Mesmo padrao de api/app/deployment/naming.py: timestamp UTC
    + sufixo aleatorio, para nunca colidir nem sobrescrever silenciosamente
    um identificador anterior."""
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    date_part = moment.strftime("%Y%m%d")
    suffix = secrets.token_hex(3)
    return f"mnt-{date_part}-{suffix}"
