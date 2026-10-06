"""Aviso em tempo real "o banco mudou" para as replicas locais.

O WebSocket `/sync/ws` so AVISA (`{"type": "sync.head", "seq": N}`); os dados
continuam vindo de `GET /sync/changes`. Aviso perdido nao faz mal: o Desktop
recupera pelo cursor no proximo poll.

Registro em memoria, como `chat/ws_manager.py`: vale para API em processo
unico. Com varias replicas da API sera preciso propagar o aviso entre
processos (ex.: LISTEN/NOTIFY do PostgreSQL).
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket

log = logging.getLogger("api.sync.notifier")

# Rajada de commits (importacao em lote) vira um aviso so.
DEBOUNCE_SECONDS = 0.2
EVENT_TYPE = "sync.head"


class SyncNotifier:
    def __init__(self, debounce_seconds: float = DEBOUNCE_SECONDS) -> None:
        self._connections: set[WebSocket] = set()
        self._debounce_seconds = debounce_seconds
        self._pending_seq = 0
        self._task: asyncio.Task | None = None

    def register(self, websocket: WebSocket) -> None:
        self._connections.add(websocket)

    def unregister(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    def connection_count(self) -> int:
        return len(self._connections)

    def notify_committed(self, seq: int) -> None:
        """Chamado depois de um COMMIT que gravou no change_log (thread do event loop)."""
        if not self._connections:
            # Ninguem ouvindo: nao guardar seq antigo para um cliente futuro
            # (ele recebe o seq atual ao conectar).
            self._pending_seq = 0
            return
        self._pending_seq = max(self._pending_seq, int(seq))
        if self._task is not None and not self._task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Commit fora de um event loop (script/CLI): ninguem para avisar.
            return
        self._task = loop.create_task(self._flush_later())

    async def _flush_later(self) -> None:
        # Commit que chega durante o envio nao agenda outra tarefa: repete aqui.
        while self._pending_seq:
            await asyncio.sleep(self._debounce_seconds)
            # Zera a cada envio: o maior seq vale so dentro da rajada (o seq do
            # banco pode voltar atras numa restauracao de backup).
            seq, self._pending_seq = self._pending_seq, 0
            await self.broadcast(seq)

    async def broadcast(self, seq: int) -> None:
        payload = {"type": EVENT_TYPE, "seq": int(seq)}
        for websocket in list(self._connections):
            try:
                await websocket.send_json(payload)
            except Exception:
                log.warning("Falha ao enviar aviso de sync; removendo conexao", exc_info=True)
                self.unregister(websocket)


notifier = SyncNotifier()
