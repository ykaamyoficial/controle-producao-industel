from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QTimer

from app.services.app_logging import get_logger


log = get_logger("chat_sync_coordinator")

# Heartbeat curto: websocket caido/reconectando (comportamento historico).
FAST_HEARTBEAT_MS = 20_000
# Heartbeat longo: websocket conectado e saudavel; o push cobre as mudancas e o
# poll vira so rede de seguranca.
SLOW_HEARTBEAT_MS = 120_000
# Janela de coalescencia: rajada de eventos (ex.: leitura local + eco
# conversation.read do websocket + message.created) vira 1 sync.
COALESCE_WINDOW_MS = 400


class ChatSyncCoordinator(QObject):
    """Decide QUANDO sincronizar contadores de chat/notificacoes.

    Nao faz I/O: chama `run_sync(reasons, with_notifications)` (injetado pela
    MainWindow, que continua usando SessionSyncService + sequence guard).
    - heartbeat adaptativo conforme saude do websocket;
    - coalescencia de gatilhos em rajada (trailing, janela curta);
    - lista de notificacoes (limit=50) so quando pedido (evento
      notification.created, heartbeat, login, reconexao)."""

    def __init__(
        self,
        run_sync: Callable[[tuple[str, ...], bool], None],
        parent: QObject | None = None,
        *,
        fast_ms: int = FAST_HEARTBEAT_MS,
        slow_ms: int = SLOW_HEARTBEAT_MS,
        coalesce_ms: int = COALESCE_WINDOW_MS,
    ):
        super().__init__(parent)
        self._run_sync = run_sync
        self._fast_ms = fast_ms
        self._slow_ms = slow_ms
        self._realtime_healthy = False
        self._pending_reasons: list[str] = []
        self._pending_notifications = False

        self._heartbeat = QTimer(self)
        self._heartbeat.timeout.connect(self._on_heartbeat)
        self._coalesce = QTimer(self)
        self._coalesce.setSingleShot(True)
        self._coalesce.setInterval(coalesce_ms)
        self._coalesce.timeout.connect(self._flush)

    @property
    def realtime_healthy(self) -> bool:
        return self._realtime_healthy

    @property
    def heartbeat_interval_ms(self) -> int:
        return self._heartbeat.interval()

    def start(self) -> None:
        self._heartbeat.start(self._slow_ms if self._realtime_healthy else self._fast_ms)

    def stop(self) -> None:
        self._heartbeat.stop()
        self._coalesce.stop()
        self._pending_reasons.clear()
        self._pending_notifications = False

    def set_realtime_healthy(self, healthy: bool) -> None:
        healthy = bool(healthy)
        if healthy == self._realtime_healthy:
            return
        self._realtime_healthy = healthy
        if self._heartbeat.isActive():
            self._heartbeat.start(self._slow_ms if healthy else self._fast_ms)
        log.info("chat_sync.heartbeat realtime_healthy=%s interval_ms=%s", healthy, self._heartbeat.interval())

    def request(self, reason: str, with_notifications: bool = False, immediate: bool = False) -> None:
        if reason not in self._pending_reasons:
            self._pending_reasons.append(reason)
        self._pending_notifications = self._pending_notifications or with_notifications
        if immediate:
            self._coalesce.stop()
            self._flush()
        elif not self._coalesce.isActive():
            self._coalesce.start()

    def _on_heartbeat(self) -> None:
        # Heartbeat sempre busca tudo (rede de seguranca contra evento perdido).
        self.request("heartbeat", with_notifications=True)

    def _flush(self) -> None:
        if not self._pending_reasons:
            return
        reasons = tuple(self._pending_reasons)
        with_notifications = self._pending_notifications
        self._pending_reasons.clear()
        self._pending_notifications = False
        self._run_sync(reasons, with_notifications)
