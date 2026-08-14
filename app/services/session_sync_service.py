from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from app.services.app_logging import get_logger
from app.ui.background_worker import start_worker


log = get_logger("session_sync_service")

STATE_IDLE = "IDLE"
STATE_SYNCING = "SYNCING"
STATE_SYNCED = "SYNCED"
STATE_FAILED = "FAILED"


class SessionSyncService(QObject):
    """ETAPA 8: reconciliacao formal do estado apos login/reconexao.

    Busca sempre o snapshot ABSOLUTO de /chat/unread-summary (nunca soma
    incremento local + delta) — por isso nao precisa de fila/buffer de
    eventos: duas chamadas concorrentes nunca duplicam contagem, cada uma
    calcula o numero certo pro estado do banco no momento em que rodou. O
    unico risco real e ordem de chegada das respostas, resolvido pelo
    sequence guard abaixo (so aplica se for mais novo que o ultimo
    aplicado). Nao conhece nada visual — so estado + sinais; quem decide o
    que fazer com o resultado e o chamador (MainWindow)."""

    sync_started = Signal()
    sync_completed = Signal(dict)
    sync_failed = Signal(object)

    def __init__(self, service, parent: QObject | None = None):
        super().__init__(parent)
        self.service = service
        self.state = STATE_IDLE
        self._seq = 0
        self._last_applied_seq = 0
        self._stopped = False
        self._sync_in_flight = False
        self._pending_reason: str | None = None

    def sync(self, reason: str = "") -> None:
        if self._stopped:
            return
        if self._sync_in_flight:
            self._pending_reason = reason or "coalesced"
            return
        self._sync_in_flight = True
        self._seq += 1
        seq = self._seq
        self.state = STATE_SYNCING
        self.sync_started.emit()
        log.info("session_sync.started reason=%s seq=%s", reason, seq)
        start_worker(
            self,
            lambda: self.service.chat_unread_summary(),
            lambda result: self._on_success(seq, reason, result),
            lambda exc: self._on_error(seq, reason, exc),
        )

    def stop(self) -> None:
        self._stopped = True

    def _on_success(self, seq: int, reason: str, result: dict[str, Any]) -> None:
        if self._stopped or seq < self._last_applied_seq:
            self._finish_sync()
            return
        self._last_applied_seq = seq
        self.state = STATE_SYNCED
        log.info(
            "session_sync.completed reason=%s seq=%s total_unread=%s notification_unread_count=%s "
            "unread_mentions=%s pending_questions=%s conversation_count_with_unread=%s",
            reason,
            seq,
            result.get("total_unread"),
            result.get("notification_unread_count"),
            result.get("unread_mentions"),
            result.get("pending_questions"),
            len(result.get("conversations") or []),
        )
        self.sync_completed.emit(result)
        self._finish_sync()

    def _on_error(self, seq: int, reason: str, exc: Exception) -> None:
        if self._stopped or seq < self._last_applied_seq:
            self._finish_sync()
            return
        self.state = STATE_FAILED
        log.warning("session_sync.failed reason=%s seq=%s error=%s", reason, seq, exc)
        self.sync_failed.emit(exc)
        self._finish_sync()

    def _finish_sync(self) -> None:
        self._sync_in_flight = False
        if self._stopped or self._pending_reason is None:
            return
        reason = self._pending_reason
        self._pending_reason = None
        QTimer.singleShot(0, lambda: self.sync(reason))
