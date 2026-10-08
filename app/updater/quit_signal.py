"""Pedido cooperativo de saida (Updater -> janela principal e agente --notifier).

O Updater grava `updater/quit.request`; cada processo do app verifica
periodicamente e sai de forma limpa. Um pedido so vale para processos que
JA estavam rodando quando ele foi emitido e enquanto for recente -- assim um
arquivo esquecido nunca fecha uma instancia aberta depois da atualizacao.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from app.updater.paths import quit_request_path

MAX_REQUEST_AGE_SECONDS = 180.0


def request_quit(request_id: str, *, path: Path | None = None, now: float | None = None) -> Path:
    target = path or quit_request_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"request_id": request_id, "issued_at": time.time() if now is None else now}
    temp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(temp, target)
    return target


def clear_quit_request(*, path: Path | None = None) -> None:
    (path or quit_request_path()).unlink(missing_ok=True)


def quit_requested(process_started_at: float, *, path: Path | None = None, now: float | None = None) -> bool:
    """True se existe um pedido emitido DEPOIS de este processo iniciar e ainda recente."""
    target = path or quit_request_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        issued_at = float(data["issued_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    current = time.time() if now is None else now
    if current - issued_at > MAX_REQUEST_AGE_SECONDS:
        return False
    return issued_at >= process_started_at
