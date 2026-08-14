from __future__ import annotations

import json
from collections import deque

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QAbstractSocket, QNetworkRequest
from PySide6.QtWebSockets import QWebSocket

from app.integrations.api.config import DesktopApiConfigStore, normalize_api_base_url
from app.services.app_logging import get_logger


log = get_logger("chat_realtime")

MIN_RECONNECT_DELAY_MS = 1000
MAX_RECONNECT_DELAY_MS = 30000
SUPPORTED_ENVELOPE_VERSION = 1
# Todos reagem do mesmo jeito hoje (poll do resumo + refresh do painel
# aberto) — o servidor manda o tipo de dominio certo (ETAPA 7), mas o
# cliente ainda nao precisa de uma reacao diferente por tipo; so precisa
# saber que o tipo e conhecido, pra nunca quebrar num evento novo/futuro.
KNOWN_EVENT_TYPES = {
    "message.created",
    "conversation.read",
    "action_required.created",
    "action_required.resolved",
    "action_required.cancelled",
    "notification.created",
    "notification.read",
    "notification.read_all",
}
# ETAPA 10: eventos notification.* nao tem necessariamente conversation_id
# no payload (notification.read/notification.read_all so precisam avisar
# "algo mudou no sino/Central pra este usuario") — por isso tem sinal
# proprio em vez de reaproveitar conversation_updated, que e sempre
# keyed por conversa.
NOTIFICATION_EVENT_PREFIX = "notification."
RECENT_EVENT_ID_CACHE_SIZE = 200


class ChatRealtimeClient(QObject):
    """Push em tempo real do chat via websocket. Roda direto no event loop
    do Qt — QWebSocket ja e assincrono via sinais (connected/disconnected/
    textMessageReceived/errorOccurred), entao nao precisa de QThread aqui,
    diferente do padrao de app/ui/background_worker.py (que existe pra
    operacoes de um tiro so, nao pra uma conexao de longa duracao).

    O servidor so manda avisos minimos ("essa conversa mudou"), nunca a
    mensagem inteira — quem recebe o sinal decide se e o caso de chamar
    refresh() em algo que esta na tela."""

    conversation_updated = Signal(int)
    read_state_updated = Signal()
    connection_changed = Signal(bool)
    notification_event = Signal(str, dict)

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._stopped = True
        self._reconnect_delay_ms = MIN_RECONNECT_DELAY_MS
        # dedup de event_id: reconnect/retry no servidor nao pode virar
        # refresh duplicado na tela — cache pequena e limitada, a
        # deduplicacao definitiva continua no banco (ver ETAPA 3/service.py).
        self._recent_event_ids: deque[str] = deque(maxlen=RECENT_EVENT_ID_CACHE_SIZE)
        self._recent_event_id_set: set[str] = set()

        self._socket = QWebSocket()
        self._socket.connected.connect(self._on_connected)
        self._socket.disconnected.connect(self._on_disconnected)
        self._socket.textMessageReceived.connect(self._on_text_message)
        self._socket.errorOccurred.connect(self._on_error)

        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._connect)

    def start(self) -> None:
        self._stopped = False
        self._reconnect_delay_ms = MIN_RECONNECT_DELAY_MS
        self._connect()

    def stop(self) -> None:
        self._stopped = True
        self._reconnect_timer.stop()
        self._socket.close()

    def _connect(self) -> None:
        if self._stopped:
            return
        if self._socket.state() != QAbstractSocket.SocketState.UnconnectedState:
            return
        try:
            token = self.service.official_proposal_storage.current_access_token()
        except Exception:
            self._schedule_reconnect()
            return
        if not token:
            self._schedule_reconnect()
            return
        try:
            base_url = normalize_api_base_url(DesktopApiConfigStore().load_settings().base_url)
        except Exception:
            self._schedule_reconnect()
            return

        ws_url = base_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/api/v1/chat/ws"
        request = QNetworkRequest(QUrl(ws_url))
        request.setRawHeader(b"Authorization", f"Bearer {token}".encode("utf-8"))
        self._socket.open(request)

    def _schedule_reconnect(self) -> None:
        if self._stopped:
            return
        self._reconnect_timer.start(self._reconnect_delay_ms)
        self._reconnect_delay_ms = min(self._reconnect_delay_ms * 2, MAX_RECONNECT_DELAY_MS)

    def _on_connected(self) -> None:
        log.info("Websocket de chat conectado")
        self._reconnect_delay_ms = MIN_RECONNECT_DELAY_MS
        self.connection_changed.emit(True)

    def _on_disconnected(self) -> None:
        self.connection_changed.emit(False)
        self._schedule_reconnect()

    def _on_error(self, _error) -> None:
        log.debug("Erro no websocket de chat: %s", self._socket.errorString())

    def _on_text_message(self, message: str) -> None:
        try:
            payload = json.loads(message)
        except ValueError:
            return
        if not isinstance(payload, dict):
            return
        # envelope desconhecido (version futura, tipo novo que este build
        # ainda nao entende) e ignorado silenciosamente — nunca derruba o
        # cliente (ETAPA 7: compatibilidade com evolucao do contrato).
        if payload.get("version") != SUPPORTED_ENVELOPE_VERSION:
            log.debug("Evento realtime com version desconhecida ignorado: %r", payload.get("version"))
            return
        event_type = payload.get("type")
        if event_type not in KNOWN_EVENT_TYPES:
            log.debug("Tipo de evento realtime desconhecido ignorado: %r", event_type)
            return
        event_id = payload.get("event_id")
        if isinstance(event_id, str):
            if event_id in self._recent_event_id_set:
                return
            self._remember_event_id(event_id)
        data = payload.get("data")
        if not isinstance(data, dict):
            return
        if event_type.startswith(NOTIFICATION_EVENT_PREFIX):
            self.notification_event.emit(event_type, data)
            return
        # Leitura altera apenas cursores e contadores. Recarregar a timeline
        # aqui cria realimentacao: refresh -> mark_read -> conversation.read
        # -> refresh, ate sobrecarregar o event loop do Qt.
        if event_type == "conversation.read":
            self.read_state_updated.emit()
            return
        conversation_id = data.get("conversation_id")
        if isinstance(conversation_id, int):
            self.conversation_updated.emit(conversation_id)

    def _remember_event_id(self, event_id: str) -> None:
        if len(self._recent_event_ids) == self._recent_event_ids.maxlen:
            oldest = self._recent_event_ids.popleft()
            self._recent_event_id_set.discard(oldest)
        self._recent_event_ids.append(event_id)
        self._recent_event_id_set.add(event_id)
