from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from app.replica.sync_engine import MODE_NOOP, SyncResult
from app.services.app_logging import get_logger
from app.ui.background_worker import start_worker

log = get_logger("replica_sync_agent")

# Poll curto: sem websocket saudavel, e o unico jeito de acompanhar o servidor.
POLL_INTERVAL_MS = 30_000
# Poll longo: com o websocket avisando cada mudanca, o poll e so rede de seguranca.
REALTIME_POLL_INTERVAL_MS = 300_000

STATE_IDLE = "idle"
STATE_SYNCING = "syncing"
STATE_READY = "ready"
STATE_FAILED = "failed"


class ReplicaSyncAgent(QObject):
    """Decide QUANDO sincronizar a replica local e avisa a UI do que mudou.

    O trabalho (rede + SQLite) roda em worker thread via `start_worker`; este
    objeto vive no thread da UI e so coordena: um sync por vez, pedidos que
    chegam durante um sync viram um unico sync seguinte."""

    data_changed = Signal(object)  # set[str] com as entidades alteradas
    sync_finished = Signal(object)  # SyncResult
    sync_failed = Signal(object)
    state_changed = Signal(str)
    # Pedido de sync vindo de outro thread (ex.: worker que acabou de gravar pela API).
    sync_requested = Signal(str)

    def __init__(
        self,
        sync_once: Callable[[], SyncResult],
        parent: QObject | None = None,
        *,
        poll_interval_ms: int = POLL_INTERVAL_MS,
        realtime_poll_interval_ms: int = REALTIME_POLL_INTERVAL_MS,
    ):
        super().__init__(parent)
        self.setObjectName("ReplicaSyncAgent")
        self._sync_once = sync_once
        self._in_flight = False
        self._pending = False
        self._stopped = True
        self.state = STATE_IDLE
        self._poll_interval_ms = poll_interval_ms
        self._realtime_poll_interval_ms = realtime_poll_interval_ms
        self._realtime_healthy = False
        self._last_seq: int | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(poll_interval_ms)
        self._timer.timeout.connect(lambda: self.request_sync("poll"))
        self.sync_requested.connect(self.request_sync)

    def start(self) -> None:
        self._stopped = False
        self._timer.start()
        self.request_sync("start")

    def stop(self) -> None:
        self._stopped = True
        self._pending = False
        self._timer.stop()

    def request_sync(self, reason: str = "") -> None:
        if self._stopped:
            return
        if self._in_flight:
            self._pending = True
            return
        self._in_flight = True
        self._set_state(STATE_SYNCING)
        log.debug("replica_sync.requested reason=%s", reason)
        start_worker(self, self._sync_once, self._on_success, self._on_error, operation_name="worker:replica.sync_once")

    def set_realtime_healthy(self, healthy: bool) -> None:
        healthy = bool(healthy)
        if healthy == self._realtime_healthy:
            return
        self._realtime_healthy = healthy
        self._timer.setInterval(self._realtime_poll_interval_ms if healthy else self._poll_interval_ms)
        log.info("replica_sync.poll realtime_healthy=%s interval_ms=%s", healthy, self._timer.interval())

    def notify_head(self, seq: int) -> None:
        """Aviso do servidor (`sync.head`): sincroniza so se a replica nao esta nesse seq."""
        if self._last_seq is None or int(seq) != self._last_seq or self._in_flight:
            self.request_sync("push")

    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self.state_changed.emit(state)

    def _on_success(self, result: SyncResult) -> None:
        self._in_flight = False
        if self._stopped:
            return
        self._last_seq = int(result.seq)
        self._set_state(STATE_READY)
        self.sync_finished.emit(result)
        if result.mode != MODE_NOOP and result.changed_entities:
            self.data_changed.emit(set(result.changed_entities))
        self._run_pending()

    def _on_error(self, exc: Exception) -> None:
        self._in_flight = False
        if self._stopped:
            return
        # Falha de rede/servidor nao invalida a replica: as telas seguem lendo o
        # ultimo estado bom e o proximo poll tenta de novo.
        log.warning("replica_sync.failed error_type=%s error=%s", type(exc).__name__, exc)
        self._set_state(STATE_FAILED)
        self.sync_failed.emit(exc)
        self._run_pending()

    def _run_pending(self) -> None:
        if self._pending and not self._stopped:
            self._pending = False
            QTimer.singleShot(0, lambda: self.request_sync("pending"))
