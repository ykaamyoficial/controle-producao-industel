from __future__ import annotations

import logging

from fastapi import WebSocket

log = logging.getLogger("api.chat.ws")


class ChatConnectionManager:
    """Registro em memoria de conexoes websocket ativas por usuario.

    Processo unico (sem replicas da API em producao hoje, ver
    docker-compose.dev.yml) — nao precisa de Redis/fila pra sincronizar
    entre instancias. Um usuario pode ter mais de uma conexao (duas janelas,
    dois computadores), por isso o valor e um set."""

    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = {}
        # Agentes de aviso (--notifier): registro a parte para nao contarem
        # como "online" no chat e so receberem eventos `notification.*`.
        self._notifier_connections: dict[int, set[WebSocket]] = {}

    def register(self, user_id: int, websocket: WebSocket) -> None:
        self._connections.setdefault(user_id, set()).add(websocket)

    def unregister(self, user_id: int, websocket: WebSocket) -> None:
        sockets = self._connections.get(user_id)
        if not sockets:
            return
        sockets.discard(websocket)
        if not sockets:
            self._connections.pop(user_id, None)

    def register_notifier(self, user_id: int, websocket: WebSocket) -> None:
        self._notifier_connections.setdefault(user_id, set()).add(websocket)

    def unregister_notifier(self, user_id: int, websocket: WebSocket) -> None:
        sockets = self._notifier_connections.get(user_id)
        if not sockets:
            return
        sockets.discard(websocket)
        if not sockets:
            self._notifier_connections.pop(user_id, None)

    def online_user_ids(self) -> set[int]:
        return set(self._connections.keys())

    async def broadcast(self, user_ids: set[int], payload: dict) -> None:
        if not user_ids:
            return
        if str(payload.get("type", "")).startswith("notification."):
            await self._broadcast_to_notifiers(user_ids, payload)
        for user_id in user_ids:
            sockets = self._connections.get(user_id)
            if not sockets:
                continue
            dead: list[WebSocket] = []
            for websocket in list(sockets):
                try:
                    await websocket.send_json(payload)
                except Exception:
                    log.warning("Falha ao enviar via websocket | usuario=%s", user_id, exc_info=True)
                    dead.append(websocket)
            for websocket in dead:
                self.unregister(user_id, websocket)


    async def _broadcast_to_notifiers(self, user_ids: set[int], payload: dict) -> None:
        for user_id in user_ids:
            for websocket in list(self._notifier_connections.get(user_id, ())):
                try:
                    await websocket.send_json(payload)
                except Exception:
                    log.warning("Falha ao enviar via websocket do agente de avisos | usuario=%s", user_id, exc_info=True)
                    self.unregister_notifier(user_id, websocket)


manager = ChatConnectionManager()
