"""Detecta, no flush, as propostas que mudaram de estado (para o Almox+) e avisa depois do commit.

Um único ponto de gancho (listeners da ``Session``) cobre liberação, cancelamento e conclusão
por qualquer caminho, sem tocar em ``proposals/service.py``. Só o que realmente mudou de estado
na transação é enviado; rollback descarta o que foi coletado.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import get_history

from api.app.modules.almox_integration.dispatcher import AlmoxDispatcher
from api.app.modules.almox_integration.state import almox_state
from api.app.modules.proposals.models import Proposal

log = logging.getLogger("api.almox")

_CHAVE = "almox_transicoes"
_CAMPOS_DO_ESTADO = (
    "is_partial",
    "is_cancelled",
    "is_completed",
    "current_status",
    "production_status",
)


@dataclass(frozen=True)
class Transicao:
    numero: str
    estado: str
    ocorrido_em: str


class PendingTransitions:
    """Estado da proposta antes da transação e o mais recente, por número."""

    def __init__(self) -> None:
        self._itens: dict[str, tuple[str | None, str | None, str]] = {}

    @classmethod
    def da_sessao(cls, session: Any) -> PendingTransitions:
        return session.info.setdefault(_CHAVE, cls())

    def registrar(self, numero: str, antes: str | None, depois: str | None) -> None:
        primeiro_antes = self._itens[numero][0] if numero in self._itens else antes
        self._itens[numero] = (primeiro_antes, depois, datetime.now(UTC).isoformat())

    def transicoes(self) -> list[Transicao]:
        return [
            Transicao(numero, depois, quando)
            for numero, (antes, depois, quando) in self._itens.items()
            if depois is not None and depois != antes
        ]


def _visao_anterior(proposal: Proposal) -> SimpleNamespace:
    """Valores que a proposta tinha antes das alterações ainda não gravadas."""
    valores: dict[str, Any] = {}
    for campo in _CAMPOS_DO_ESTADO:
        historico = get_history(proposal, campo)
        if historico.deleted:
            valores[campo] = historico.deleted[0]
        elif historico.unchanged:
            valores[campo] = historico.unchanged[0]
        else:
            valores[campo] = getattr(proposal, campo, None)
    return SimpleNamespace(**valores)


def coletar_transicoes(session: Any) -> None:
    fila = PendingTransitions.da_sessao(session)
    for objeto in (*session.new, *session.dirty):
        if not isinstance(objeto, Proposal) or not objeto.proposal_number:
            continue
        antes = None if objeto in session.new else almox_state(_visao_anterior(objeto))
        fila.registrar(objeto.proposal_number, antes, almox_state(objeto))


_tarefas: set[asyncio.Task[None]] = set()
_dispatcher: AlmoxDispatcher | None = None
_instalado = False


async def _enviar(dispatcher: AlmoxDispatcher, transicoes: list[Transicao]) -> None:
    for transicao in transicoes:
        try:
            await dispatcher.enviar_transicao(
                transicao.numero, transicao.estado, transicao.ocorrido_em
            )
        except Exception:  # noqa: BLE001 - nunca derruba a operação que originou o evento
            log.exception("almox_webhook_erro numero=%s", transicao.numero)


def _apos_commit(session: Any) -> None:
    fila = session.info.pop(_CHAVE, None)
    if fila is None or _dispatcher is None or not _dispatcher.ativo:
        return
    transicoes = fila.transicoes()
    if not transicoes:
        return
    try:
        tarefa = asyncio.get_running_loop().create_task(_enviar(_dispatcher, transicoes))
    except RuntimeError:
        log.warning("almox_webhook_sem_loop transicoes=%d", len(transicoes))
        return
    _tarefas.add(tarefa)
    tarefa.add_done_callback(_tarefas.discard)


def _apos_flush(session: Any, _contexto: Any) -> None:
    coletar_transicoes(session)


def _apos_rollback(session: Any) -> None:
    session.info.pop(_CHAVE, None)


def instalar(dispatcher: AlmoxDispatcher) -> None:
    """Liga a detecção de transições. Chamar de novo só troca o dispatcher."""
    global _dispatcher, _instalado
    _dispatcher = dispatcher
    if _instalado:
        return
    event.listen(Session, "after_flush", _apos_flush)
    event.listen(Session, "after_commit", _apos_commit)
    event.listen(Session, "after_rollback", _apos_rollback)
    _instalado = True
