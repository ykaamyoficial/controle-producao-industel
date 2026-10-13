from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from app.services import notifier_credentials as creds
from app.services.app_logging import get_logger
from app.ui.components.modern_button import ModernButton


log = get_logger("notifier_status_widget")

REFRESH_INTERVAL_MS = 5000


def _format_time(timestamp: float, now: float) -> str:
    moment = datetime.fromtimestamp(timestamp)
    if datetime.fromtimestamp(now).date() == moment.date():
        return moment.strftime("%H:%M")
    return moment.strftime("%d/%m %H:%M")


def describe_status(running: bool, status: dict, *, now: float | None = None) -> str:
    """Texto da situacao dos avisos do Windows, em linguagem simples. Funcao
    pura (a tela so mostra o que ela devolve)."""
    now = time.time() if now is None else now
    if not running:
        return "Avisos do Windows: desligados. Eles voltam a ligar quando o programa for aberto."
    owner = str(status.get("owner") or "").strip()
    if not owner:
        return "Avisos do Windows: ligados, aguardando um login neste computador."
    parts = [f"Avisos do Windows: ligados para {owner}"]
    unread = int(status.get("unread") or 0)
    parts.append(f"{unread} nao lida(s)" if unread else "nenhuma nao lida")
    last_toast = float(status.get("last_toast_at") or 0)
    parts.append(f"ultimo aviso as {_format_time(last_toast, now)}" if last_toast else "nenhum aviso mostrado ainda")
    return " — ".join(parts)


class NotifierStatusWidget(QWidget):
    """Uma linha com a situacao do agente de avisos (ligado/desligado, para quem
    e o ultimo login) e o botao para liga-lo na hora."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.label = QLabel("")
        self.label.setObjectName("Caption")
        self.label.setWordWrap(True)
        layout.addWidget(self.label, 1)
        self.turn_on_btn = ModernButton("Ligar agora", "refresh")
        self.turn_on_btn.clicked.connect(self._turn_on)
        layout.addWidget(self.turn_on_btn)
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh()
        self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def refresh(self) -> None:
        try:
            from app.services.notifier_agent import is_notifier_running

            running = is_notifier_running()
        except Exception:
            running = False
        self.label.setText(describe_status(running, creds.read_status()))
        self.turn_on_btn.setVisible(not running)

    def _turn_on(self) -> None:
        try:
            from app.services.notifier_agent import ensure_notifier_running

            started = ensure_notifier_running()
        except Exception:
            log.exception("Falha ao ligar o avisador pela tela de Configuracoes")
            started = False
        if not started:
            self.label.setText(
                "Nao foi possivel ligar agora. Isso so funciona na versao instalada do programa."
            )
            return
        QTimer.singleShot(1500, self.refresh)
