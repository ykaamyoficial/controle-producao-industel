from __future__ import annotations

import secrets
from datetime import datetime, timezone


def new_correlation_id(*, prefix: str = "upd", now: datetime | None = None) -> str:
    """Identificador que percorre todas as etapas de um mesmo fluxo de
    update/deploy (Fase 16, Secao 11) -- mesmo padrao de
    api.app.maintenance.naming.build_maintenance_id: timestamp UTC + sufixo
    aleatorio, nunca colide, nunca e inferido por horario."""
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    date_part = moment.strftime("%Y%m%d")
    suffix = secrets.token_hex(4)
    return f"{prefix}-{date_part}-{suffix}"
