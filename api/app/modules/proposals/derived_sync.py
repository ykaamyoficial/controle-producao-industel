"""Materializacao de dados derivados de Expedicao e Fiscal fora do caminho de leitura.

`ExpeditionItem` e `FiscalRecord`/`FiscalItem` sao derivados do estado das
propostas. Antes eram gerados por `GET` (com commit). Agora:

* Escrita: um listener `after_flush` anota as propostas tocadas na sessao e um
  hook pre-commit (ver `database.session.HookedAsyncSession`) reconcilia so
  essas propostas, na mesma transacao da escrita.
* Backfill idempotente (`backfill_derived_state`): reconcilia todas as
  propostas; roda no startup da API (e pode ser chamado manualmente) para
  cobrir dados existentes e alteracoes feitas fora do ORM.

Limite conhecido: alteracoes por SQL direto (fora do ORM) so sao reconciliadas
no proximo backfill ou na proxima escrita ORM da proposta.
"""

from __future__ import annotations

import logging

from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from api.app.database.session import get_sessionmaker, register_pre_commit_hook
from api.app.modules.proposals import service
from api.app.modules.proposals.models import (
    ExpeditionItem,
    GalvanizationLoadItem,
    ProductionAllocationTransfer,
    Proposal,
    ProposalItem,
    ProposalRemanagementItem,
)

log = logging.getLogger("api.proposals.derived_sync")

_DIRTY_PROPOSALS = "derived_sync_dirty_proposals"
_DIRTY_ITEMS = "derived_sync_dirty_items"
_BUSY = "derived_sync_busy"
_BACKFILL_LOCK_KEY = 7_204_001_017


@event.listens_for(Session, "after_flush")
def _collect_dirty(session: Session, _flush_context) -> None:
    if session.info.get(_BUSY):
        return
    proposals: set[int] = session.info.setdefault(_DIRTY_PROPOSALS, set())
    items: set[int] = session.info.setdefault(_DIRTY_ITEMS, set())
    for obj in (*session.new, *session.dirty):
        if isinstance(obj, Proposal):
            if obj.id is not None:
                proposals.add(int(obj.id))
        elif isinstance(obj, (ProposalItem, ExpeditionItem)):
            if obj.proposal_id is not None:
                proposals.add(int(obj.proposal_id))
        elif isinstance(obj, ProductionAllocationTransfer):
            items.update(int(v) for v in (obj.from_item_id, obj.to_item_id) if v is not None)
        elif isinstance(obj, ProposalRemanagementItem):
            if obj.destination_item_id is not None:
                items.add(int(obj.destination_item_id))
        elif isinstance(obj, GalvanizationLoadItem):
            if obj.proposal_item_id is not None:
                items.add(int(obj.proposal_item_id))


async def reconcile_derived_state(session: AsyncSession, proposal_ids: set[int], item_ids: set[int]) -> bool:
    ids = set(proposal_ids)
    if item_ids:
        ids.update(int(v) for v in (await session.execute(select(ProposalItem.proposal_id).where(ProposalItem.id.in_(item_ids)))).scalars())
    if not ids:
        return False
    # recalculate=False: so materializa linhas. A transicao de area/status da
    # proposta (`_recalculate_expedition_proposal_state`) pertencia a leitura
    # passiva e NAO e reproduzida na escrita -- as operacoes de escrita ja
    # definem o proprio estado e os testes de fluxo misto/hierarquia dependem
    # de a escrita nao mover a proposta de area por tras.
    changed = await service._sync_expedition_from_available_items(session, proposal_ids=ids, recalculate=False)
    changed = await service._sync_fiscal_records(session, proposal_ids=ids) or changed
    return changed


async def _pre_commit(session: AsyncSession) -> None:
    if session.info.get(_BUSY):
        return
    sync_session = session.sync_session
    if sync_session.new or sync_session.dirty or sync_session.deleted:
        await session.flush()  # popula o conjunto de propostas tocadas
    proposals = session.info.pop(_DIRTY_PROPOSALS, None) or set()
    items = session.info.pop(_DIRTY_ITEMS, None) or set()
    if not proposals and not items:
        return
    session.info[_BUSY] = True
    try:
        await reconcile_derived_state(session, proposals, items)
    finally:
        session.info.pop(_BUSY, None)
        session.info.pop(_DIRTY_PROPOSALS, None)
        session.info.pop(_DIRTY_ITEMS, None)


register_pre_commit_hook(_pre_commit)


async def backfill_derived_state() -> bool:
    """Reconcilia ExpeditionItem/FiscalRecord/FiscalItem de todas as propostas. Idempotente.

    Usa advisory lock transacional: com varios workers/instancias subindo ao
    mesmo tempo, so um executa (os demais retornam False sem esperar).
    """
    factory = get_sessionmaker()
    if factory is None:
        return False
    async with factory() as session:
        session.info[_BUSY] = True
        locked = (await session.execute(select(func.pg_try_advisory_xact_lock(_BACKFILL_LOCK_KEY)))).scalar_one()
        if not locked:
            log.info("derived_backfill_skipped reason=lock_held")
            return False
        changed = await service._sync_expedition_from_available_items(session, recalculate=False)
        changed = await service._sync_fiscal_records(session) or changed
        await session.commit()
        log.info("derived_backfill_done changed=%s", changed)
        return changed


if __name__ == "__main__":  # python -m api.app.modules.proposals.derived_sync
    import asyncio

    print("changed" if asyncio.run(backfill_derived_state()) else "nothing to do")
