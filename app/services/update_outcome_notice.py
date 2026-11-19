"""Aviso de falha de atualizacao que o dialogo nao viu.

Depois de um rollback (ou de uma falha com o app ja fechado) a versao antiga
reabre sozinha, sem dialogo. Na abertura, le o status mais recente do Updater
e, se for uma falha recente ainda nao mostrada, devolve o texto UMA vez
(marcador `<request_id>.shown` ao lado do status).
"""

from __future__ import annotations

import time
from pathlib import Path

from app.updater.paths import status_dir as default_status_dir
from app.updater.status import PHASE_FAILED, PHASE_ROLLED_BACK, read_status

# Falhas com o app ja fechado (rollback sem permissao no ponteiro / sem versao anterior) usam 100;
# as de preparacao/ativacao com o app aberto ficam abaixo disso e ja foram mostradas no dialogo.
POST_CLOSE_FAILURE_PERCENT = 100


def pending_update_failure_notice(status_dir: Path | None = None, now: float | None = None, max_age_seconds: float = 900) -> str | None:
    directory = Path(status_dir) if status_dir is not None else default_status_dir()
    try:
        newest = max(directory.glob("*.json"), key=lambda path: path.stat().st_mtime, default=None)
        if newest is None:
            return None
        age = (time.time() if now is None else now) - newest.stat().st_mtime
    except OSError:
        return None
    if age > max_age_seconds:
        return None
    status = read_status(newest.stem, directory=directory)
    if status is None:
        return None
    reportable = status.phase == PHASE_ROLLED_BACK or (status.phase == PHASE_FAILED and status.percent >= POST_CLOSE_FAILURE_PERCENT)
    marker = directory / f"{status.request_id}.shown"
    if not reportable or marker.exists():
        return None
    try:
        marker.write_text("shown", encoding="utf-8")
    except OSError:
        return None  # sem como marcar, melhor nao avisar do que avisar a cada abertura
    return f"{status.message}\n\nDetalhe tecnico: {status.error}" if status.error else status.message
