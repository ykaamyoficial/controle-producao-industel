"""Observador do pedido de saida do Updater (ver app/updater/quit_signal.py).

Instalado na janela principal e no agente --notifier: quando o Updater grava
o pedido, o processo fecha de forma limpa (mesmo caminho do Sair), em vez de
ficar segurando arquivos da versao antiga ate ser encerrado a forca.
"""

from __future__ import annotations

import time
from typing import Callable

from app.updater.quit_signal import quit_requested

PROCESS_STARTED_AT = time.time()
CHECK_INTERVAL_MS = 1500


def install_quit_watcher(
    parent,
    on_quit: Callable[[], None],
    *,
    interval_ms: int = CHECK_INTERVAL_MS,
    started_at: float | None = None,
    checker: Callable[[float], bool] = quit_requested,
):
    """Cria o QTimer (filho de `parent`) e o devolve. `on_quit` roda uma vez."""
    from PySide6.QtCore import QTimer

    origin = PROCESS_STARTED_AT if started_at is None else started_at
    timer = QTimer(parent)
    fired = {"done": False}

    def _tick() -> None:
        if fired["done"] or not checker(origin):
            return
        fired["done"] = True
        timer.stop()
        on_quit()

    timer.timeout.connect(_tick)
    timer.start(interval_ms)
    return timer
