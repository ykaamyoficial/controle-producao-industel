"""Efeito de cancelar uma proposta ou trocar o Pedido (PD) dela sobre a Inspecao e a Logistica.

`impact` descreve o que existe (inspecao do PD, LOG ativo) e serve ao 409 de confirmacao
(flag `confirm_inspection_logistics`); `apply_*` executa depois da confirmacao, sem commit
(quem chama, em proposals/service.py, faz o commit junto com a alteracao da proposta).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core import error_codes
from api.app.core.exceptions import ApiError
from api.app.modules.auth.models import User
from api.app.modules.inspection import service as inspection_service
from api.app.modules.inspection.models import Inspection
from api.app.modules.logistics import service as logistics_service
from api.app.modules.logistics.models import LogisticsLogItem
from api.app.modules.proposals.models import Proposal


def _key(pd: str | None) -> str:
    return (pd or "").strip().lower()


async def _inspection_of(session: AsyncSession, pd: str | None) -> Inspection | None:
    if not _key(pd):
        return None
    return (await session.execute(select(Inspection).where(func.lower(Inspection.pd_code) == _key(pd)))).scalars().first()


async def _other_live_proposals(session: AsyncSession, proposal: Proposal, pd: str | None) -> int:
    return (
        await session.execute(
            select(func.count()).select_from(Proposal).where(
                func.lower(func.trim(Proposal.order_reference)) == _key(pd), Proposal.active.is_(True), Proposal.is_cancelled.is_(False), Proposal.id != proposal.id,
            )
        )
    ).scalar_one()


async def impact(session: AsyncSession, proposal: Proposal, *, old_pd: str | None, new_pd: str | None = None, cancelling: bool = False) -> dict | None:
    """None se a proposta nao tem inspecao nem LOG ativo; senao o resumo do que acontece ao confirmar."""
    insp = await _inspection_of(session, old_pd)
    in_log = await logistics_service.active_log_item_of(session, proposal.id)
    if insp is None and in_log is None:
        return None
    log = in_log[0] if in_log else None
    others = await _other_live_proposals(session, proposal, old_pd) if insp else 0
    new_insp = None if cancelling else await _inspection_of(session, new_pd)
    follows = bool(insp and not cancelling and others == 0 and _key(new_pd) and new_insp is None)
    if log is None:
        leaves_log = False
    elif cancelling:
        leaves_log = True
    elif follows:
        leaves_log = insp.stage != "fim"
    else:
        leaves_log = not await inspection_service.is_pd_inspection_finished(session, new_pd)
    in_log_items = 0
    if leaves_log and log.load_id is not None:
        in_log_items = (await session.execute(
            select(func.count()).select_from(LogisticsLogItem).where(LogisticsLogItem.log_id == log.id, LogisticsLogItem.removed_at.is_(None))
        )).scalar_one()
    return {
        "action": "cancel" if cancelling else "change_order",
        "inspection_orphaned": bool(insp and others == 0 and not follows),
        "log_stays_empty_in_load": in_log_items == 1,
        "inspection": {"id": insp.id, "pd_code": insp.pd_code, "nqt_code": insp.nqt_code, "stage": insp.stage} if insp else None,
        "log": {"id": log.id, "code": log.code, "stage": log.stage, "in_load": log.load_id is not None} if log else None,
        "other_proposals_with_old_pd": others,
        "inspection_follows_new_pd": follows,
        "new_pd_has_inspection": new_insp is not None,
        "leaves_log": leaves_log,
    }


def _message(info: dict, proposal: Proposal) -> str:
    parts = []
    insp, log = info["inspection"], info["log"]
    if info["action"] == "cancel":
        if log:
            parts.append(f"Ao cancelar, a proposta {proposal.proposal_number} sai do {log['code']} (o histórico fica registrado).")
        if insp:
            parts.append(f"A inspeção do PD {insp['pd_code']} continua com o PD e recebe uma anotação do cancelamento.")
            if info["inspection_orphaned"]:
                parts.append("Ela fica sem proposta ativa até outra proposta usar o PD.")
    else:
        if insp and info["inspection_follows_new_pd"]:
            parts.append(f"A proposta é a única com o PD {insp['pd_code']}: a inspeção passa a acompanhar o novo PD.")
        elif insp and info["new_pd_has_inspection"]:
            parts.append(f"O novo PD já tem inspeção própria: a inspeção do PD {insp['pd_code']} fica como está.")
        elif insp:
            parts.append(f"A inspeção do PD {insp['pd_code']} fica como está.")
        if insp and info["inspection_orphaned"]:
            parts.append("Ela fica sem proposta ativa até outra proposta usar o PD.")
        if log and info["leaves_log"]:
            parts.append(f"A proposta sai do {log['code']}, porque a inspeção do novo PD não está finalizada (o histórico fica registrado).")
        elif log:
            parts.append(f"A proposta continua no {log['code']}.")
    if log and info["log_stays_empty_in_load"]:
        parts.append(f"O {log['code']} está numa carga e fica sem propostas.")
    return "Esta proposta tem inspeção ou LOG. " + " ".join(parts) + " Confirme para continuar."


async def require_confirmation(session: AsyncSession, proposal: Proposal, *, old_pd, new_pd=None, cancelling=False, confirmed: bool) -> dict | None:
    info = await impact(session, proposal, old_pd=old_pd, new_pd=new_pd, cancelling=cancelling)
    if info is not None and not confirmed:
        raise ApiError(error_codes.INSPECTION_LOGISTICS_CONFIRMATION_REQUIRED, _message(info, proposal), status_code=409, details=info)
    return info


async def _leave_log(session: AsyncSession, proposal: Proposal, actor: User, request_id: str | None, reason: str) -> None:
    found = await logistics_service.active_log_item_of(session, proposal.id)
    if found:
        await logistics_service.detach_item(session, found[0], found[1], proposal, actor, request_id, reason)


async def apply_cancel(session: AsyncSession, proposal: Proposal, actor: User, request_id: str | None, reason: str) -> None:
    await _leave_log(session, proposal, actor, request_id, f"Proposta cancelada: {reason}")
    insp = await _inspection_of(session, proposal.order_reference)
    if insp:
        orphaned = await _other_live_proposals(session, proposal, proposal.order_reference) == 0
        inspection_service.add_note_event(session, insp, actor, f"Proposta {proposal.proposal_number} cancelada" + (": inspeção sem proposta ativa" if orphaned else ""), reason)


async def apply_order_change(session: AsyncSession, proposal: Proposal, old_pd: str | None, new_pd: str | None, actor: User, request_id: str | None) -> None:
    """Chamado com `proposal.order_reference` ja trocado."""
    insp = await _inspection_of(session, old_pd)
    if insp is not None:
        others = await _other_live_proposals(session, proposal, old_pd)
        new_pd = (new_pd or "").strip()
        if others == 0 and new_pd and await _inspection_of(session, new_pd) is None:
            old_code = insp.pd_code
            insp.pd_code = new_pd
            await session.flush()
            inspection_service.add_note_event(session, insp, actor, f"PD alterado de {old_code} para {new_pd}: o Pedido da proposta {proposal.proposal_number} foi trocado e ela era a única com esse PD")
        else:
            orphaned = ": inspeção sem proposta ativa" if others == 0 else ""
            inspection_service.add_note_event(session, insp, actor, f"Proposta {proposal.proposal_number} mudou o Pedido de {insp.pd_code} para {new_pd or '(vazio)'}{orphaned}")
    if not await inspection_service.is_pd_inspection_finished(session, new_pd):
        await _leave_log(session, proposal, actor, request_id, f"Pedido da proposta alterado de {old_pd or '(vazio)'} para {new_pd or '(vazio)'}; a inspeção do novo PD não está finalizada")
