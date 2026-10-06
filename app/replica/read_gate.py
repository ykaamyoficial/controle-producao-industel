from __future__ import annotations

import threading
from typing import Callable, Iterable

from app.replica.replica_db import META_ENTITIES, ReplicaDatabase

# Escritas nesses caminhos nao mexem em entidades replicadas.
_UNREPLICATED_PREFIXES = ("/api/v1/chat", "/api/v1/notifications", "/api/v1/auth")


class ReplicaReadGate:
    """Decide se uma tela pode ler da replica agora, ou deve ir a API.

    A replica so e usada quando esta comprovadamente em dia com tudo que ESTE
    Desktop gravou: toda escrita pela API fecha a porta ate terminar uma
    sincronizacao iniciada depois dela. Assim o usuario nunca salva algo e ve
    a tela com o dado antigo. Mudanca de outro usuario chega pelo aviso em
    tempo real (atraso de fracao de segundo)."""

    def __init__(self, database: ReplicaDatabase, *, on_write: Callable[[], None] | None = None):
        self.database = database
        self.on_write = on_write
        self._lock = threading.Lock()
        self._write_generation = 0
        self._synced_generation = -1  # nenhuma sincronizacao concluida nesta sessao

    @staticmethod
    def is_write(method: str, path: str) -> bool:
        return method.upper() not in ("GET", "HEAD", "OPTIONS") and not path.startswith(_UNREPLICATED_PREFIXES)

    def write_started(self) -> None:
        """Fecha a porta enquanto a escrita esta em voo."""
        with self._lock:
            self._write_generation += 1

    def write_finished(self) -> None:
        """So um sync iniciado DEPOIS da resposta da API garante enxergar a escrita."""
        with self._lock:
            self._write_generation += 1
        if self.on_write is not None:
            self.on_write()

    def begin_sync(self) -> int:
        with self._lock:
            return self._write_generation

    def complete_sync(self, generation: int) -> None:
        with self._lock:
            self._synced_generation = max(self._synced_generation, generation)

    def can_read(self, entities: Iterable[str]) -> bool:
        with self._lock:
            if self._synced_generation != self._write_generation:
                return False
        if self.database.cursor() is None:
            return False
        # Entidade que o usuario nao pode ver nao esta na replica: a API responde (e nega).
        available = set((self.database.get_meta(META_ENTITIES) or "").split(","))
        return set(entities) <= available
