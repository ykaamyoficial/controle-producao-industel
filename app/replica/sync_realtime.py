from __future__ import annotations

import json
from typing import Callable

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QAbstractSocket, QNetworkRequest
from PySide6.QtWebSockets import QWebSocket

from app.integrations.api.config import normalize_api_base_url
from app.services.app_logging import get_logger

log = get_logger("replica_realtime")

MIN_RECONNECT_DELAY_MS = 1000
MAX_RECONNECT_DELAY_MS = 30000
PING_INTERVAL_MS = 30000
PONG_TIMEOUT_MS = 10000
EVENT_TYPE = "sync.head"


class ReplicaRealtimeClient(QObject):
    """Escuta `/api/v1/sync/ws`: o servidor avisa que o `seq` avancou.

    So o aviso passa aqui -- os dados vem de `/sync/changes`, pelo
    `ReplicaSyncAgent`. Mesmo desenho de `app/ui/chat_realtime.py`
    (QWebSocket no event loop do Qt, reconexao com backoff, watchdog de ping);
    sao canais separados porque o chat exige permissao propria e a replica nao."""

    head_advanced = Signal(int)
    connection_changed = Signal(bool)

    def __init__(self, get_token: Callable[[], str], get_base_url: Callable[[], str], parent=None):
        super().__init__(parent)
        self._get_token = get_token
        self._get_base_url = get_base_url
        self._stopped = True
        self._reconnect_delay_ms = MIN_RECONNECT_DELAY_MS

        self._socket = QWebSocket()
        self._socket.connected.connect(self._on_connected)
        self._socket.disconnected.connect(self._on_disconnected)
        self._socket.textMessageReceived.connect(self._on_text_message)
        self._socket.pong.connect(self._on_pong)

        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._connect)
        self._ping_timer = QTimer(self)
        self._ping_timer.setInterval(PING_INTERVAL_MS)
        self._ping_timer.timeout.connect(self._send_ping)
        self._pong_timer = QTimer(self)
        self._pong_timer.setSingleShot(True)
        self._pong_timer.setInterval(PONG_TIMEOUT_MS)
        self._pong_timer.timeout.connect(self._on_pong_timeout)

    def start(self) -> None:
        self._stopped = False
        self._reconnect_delay_ms = MIN_RECONNECT_DELAY_MS
        self._connect()

    def stop(self) -> None:
        self._stopped = True
        self._reconnect_timer.stop()
        self._stop_watchdog()
        self._socket.close()

    def _connect(self) -> None:
        if self._stopped or self._socket.state() != QAbstractSocket.SocketState.UnconnectedState:
            return
        try:
            token = self._get_token()
            base_url = normalize_api_base_url(self._get_base_url())
        except Exception:
            self._schedule_reconnect()
            return
        if not token:
            self._schedule_reconnect()
            return
        ws_url = base_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/api/v1/sync/ws"
        request = QNetworkRequest(QUrl(ws_url))
        request.setRawHeader(b"Authorization", f"Bearer {token}".encode("utf-8"))
        self._socket.open(request)

    def _schedule_reconnect(self) -> None:
        if self._stopped:
            return
        self._reconnect_timer.start(self._reconnect_delay_ms)
        self._reconnect_delay_ms = min(self._reconnect_delay_ms * 2, MAX_RECONNECT_DELAY_MS)

    def _on_connected(self) -> None:
        log.info("Websocket da replica conectado")
        self._reconnect_delay_ms = MIN_RECONNECT_DELAY_MS
        self._ping_timer.start()
        self.connection_changed.emit(True)

    def _on_disconnected(self) -> None:
        self._stop_watchdog()
        self.connection_changed.emit(False)
        self._schedule_reconnect()

    def _stop_watchdog(self) -> None:
        self._ping_timer.stop()
        self._pong_timer.stop()

    def _send_ping(self) -> None:
        if self._pong_timer.isActive():
            return
        self._socket.ping()
        self._pong_timer.start()

    def _on_pong(self, *_args) -> None:
        self._pong_timer.stop()

    def _on_pong_timeout(self) -> None:
        log.warning("Websocket da replica sem resposta ao ping; reconectando")
        self._socket.abort()

    def _on_text_message(self, message: str) -> None:
        try:
            payload = json.loads(message)
        except ValueError:
            return
        # Tipo desconhecido (servidor mais novo) e ignorado, nunca derruba o cliente.
        if not isinstance(payload, dict) or payload.get("type") != EVENT_TYPE:
            return
        seq = payload.get("seq")
        if isinstance(seq, int) and not isinstance(seq, bool):
            self.head_advanced.emit(seq)
