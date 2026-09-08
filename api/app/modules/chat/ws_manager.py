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

    def register(self, user_id: int, websocket: WebSocket) -> None:
        self._connections.setdefault(user_id, set()).add(websocket)

    def unregister(self, user_id: int, websocket: WebSocket) -> None:
        sockets = self._connections.get(user_id)
        if not sockets:
            return
        sockets.discard(websocket)
        if not sockets:
            self._connections.pop(user_id, None)

    def online_user_ids(self) -> set[int]:
        return set(self._connections.keys())

    async def broadcast(self, user_ids: set[int], payload: dict) -> None:
        if not user_ids:
            return
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


manager = ChatConnectionManager()
