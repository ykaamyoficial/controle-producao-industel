"""Captura automatica de mudancas das entidades replicadas.

Listeners do SQLAlchemy, validos para qualquer sessao ORM da API:

* `after_flush`: anota em `session.info` as linhas inseridas, alteradas ou
  removidas das entidades de `registry.SYNC_ENTITIES`.
* `before_commit`: grava essas anotacoes em `change_log`, na MESMA transacao
  (rollback descarta o evento junto com o dado).
* `after_rollback`: descarta as anotacoes pendentes.
* `after_commit`: avisa as replicas conectadas em `/sync/ws` (`notifier.py`).

Ordem: o `seq` so e atribuido no commit, sob um advisory lock transacional
que dura do INSERT ate o COMMIT. Assim a ordem dos `seq` e a ordem dos
commits e um leitor nunca ve o seq 11 antes de o 10 estar visivel -- sem
isso um Desktop poderia avancar o cursor e perder uma mudanca para sempre.

Limite conhecido: UPDATE/DELETE em massa via Core (`session.execute(update(
Model)...)`) nao passam pelo ORM e nao sao capturados; nesses casos chame
`record_change` explicitamente.
"""

from __future__ import annotations

import logging

from sqlalchemy import event, func, insert, select
from sqlalchemy.orm import Session

from api.app.modules.sync.models import ChangeLog
from api.app.modules.sync.notifier import notifier
from api.app.modules.sync.registry import ENTITY_BY_MODEL, ENTITY_BY_NAME

log = logging.getLogger("api.sync.capture")

OP_UPSERT = "upsert"
OP_DELETE = "delete"

_PENDING = "sync_pending_changes"
_COMMITTING_SEQ = "sync_committing_seq"
_SEQ_LOCK_KEY = 7_204_001_018


def record_change(session: Session, entity: str, entity_id: int, op: str = OP_UPSERT) -> None:
    """Anota manualmente uma mudanca (para escritas que nao passam pelo ORM)."""
    if entity not in ENTITY_BY_NAME:
        raise ValueError(f"Entidade nao replicada: {entity}")
    if op not in (OP_UPSERT, OP_DELETE):
        raise ValueError(f"Operacao invalida: {op}")
    # dict preserva a ordem e a ultima operacao vence (upsert depois delete => delete).
    pending: dict[tuple[str, int], str] = session.info.setdefault(_PENDING, {})
    key = (entity, int(entity_id))
    pending.pop(key, None)
    pending[key] = op


def _entity_of(obj) -> str | None:
    entity = ENTITY_BY_MODEL.get(type(obj))
    return entity.name if entity is not None else None


@event.listens_for(Session, "after_flush")
def _collect_changes(session: Session, _flush_context) -> None:
    for obj in session.new:
        name = _entity_of(obj)
        if name and obj.id is not None:
            record_change(session, name, obj.id)
    for obj in session.dirty:
        name = _entity_of(obj)
        if name and obj.id is not None and session.is_modified(obj, include_collections=False):
            record_change(session, name, obj.id)
    for obj in session.deleted:
        name = _entity_of(obj)
        if name and obj.id is not None:
            record_change(session, name, obj.id, OP_DELETE)


@event.listens_for(Session, "before_commit")
def _write_change_log(session: Session) -> None:
    # before_commit roda antes do flush do commit: forca-o para enxergar tudo.
    session.flush()
    pending: dict[tuple[str, int], str] | None = session.info.pop(_PENDING, None)
    if not pending:
        return
    connection = session.connection()
    connection.execute(select(func.pg_advisory_xact_lock(_SEQ_LOCK_KEY)))
    result = connection.execute(
        insert(ChangeLog).returning(ChangeLog.seq),
        [{"entity": entity, "entity_id": entity_id, "op": op} for (entity, entity_id), op in pending.items()],
    )
    session.info[_COMMITTING_SEQ] = max(result.scalars().all())


@event.listens_for(Session, "after_commit")
def _notify_replicas(session: Session) -> None:
    seq = session.info.pop(_COMMITTING_SEQ, None)
    if seq is None:
        return
    try:
        notifier.notify_committed(seq)
    except Exception:  # o aviso e best-effort; o commit ja aconteceu
        log.warning("Falha ao agendar aviso de sync", exc_info=True)


@event.listens_for(Session, "after_rollback")
def _discard_changes(session: Session) -> None:
    session.info.pop(_PENDING, None)
    session.info.pop(_COMMITTING_SEQ, None)
