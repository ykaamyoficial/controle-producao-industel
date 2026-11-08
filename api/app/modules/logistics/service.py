from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from api.app.core import error_codes
from api.app.core.exceptions import ApiError
from api.app.modules.auth import repository as auth_repository
from api.app.modules.auth.models import User
from api.app.modules.auth.tokens import utcnow
from api.app.modules.inspection.models import Inspection
from api.app.modules.inspection.service import days_in_stage, finished_dates, is_pd_inspection_finished
from api.app.modules.logistics import calendar_rules, schemas
from api.app.modules.logistics.models import LogisticsEvent, LogisticsLoad, LogisticsLog, LogisticsLogItem, load_code
from api.app.modules.logistics.state_resolver import resolve_state
from api.app.modules.proposals.models import Proposal


def _fmt(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _pd_of(proposal: Proposal) -> str | None:
    value = (proposal.order_reference or "").strip()
    return value or None


def _event(session: AsyncSession, actor: User, text: str, *, log_id: int | None = None, load_id: int | None = None, reason: str | None = None) -> None:
    session.add(LogisticsEvent(log_id=log_id, load_id=load_id, actor_user_id=actor.id, text=text, reason=reason))


async def _audit(session: AsyncSession, actor: User, event_type: str, request_id: str | None, **details) -> None:
    await auth_repository.create_security_event(session, event_type, actor_user_id=actor.id, request_id=request_id, details=details)


# --- leitura ----------------------------------------------------------------------------------


async def _get_log(session: AsyncSession, log_id: int, *, lock: bool = False) -> LogisticsLog:
    stmt = select(LogisticsLog).where(LogisticsLog.id == log_id)
    if lock:
        stmt = stmt.with_for_update()
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        raise ApiError(error_codes.LOGISTICS_LOG_NOT_FOUND, "LOG nao encontrado.", status_code=404)
    return row


async def _get_load(session: AsyncSession, load_id: int, *, lock: bool = False) -> LogisticsLoad:
    stmt = select(LogisticsLoad).where(LogisticsLoad.id == load_id)
    if lock:
        stmt = stmt.with_for_update()
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        raise ApiError(error_codes.LOGISTICS_LOAD_NOT_FOUND, "Carga de entrega nao encontrada.", status_code=404)
    return row


async def _active_counts(session: AsyncSession, log_ids: list[int]) -> dict[int, int]:
    if not log_ids:
        return {}
    rows = (
        await session.execute(
            select(LogisticsLogItem.log_id, func.count())
            .where(LogisticsLogItem.log_id.in_(log_ids), LogisticsLogItem.removed_at.is_(None))
            .group_by(LogisticsLogItem.log_id)
        )
    ).all()
    return {log_id: n for log_id, n in rows}


def _log_dict(row: LogisticsLog, count: int, today: date) -> dict:
    data = {c: getattr(row, c) for c in schemas.LogOut.model_fields if hasattr(row, c)}
    data.update(days_in_stage=days_in_stage(row.stage_since, today), proposal_count=count, load_code=load_code(row.load_id) if row.load_id else None)
    return data


async def _items_by_log(session: AsyncSession, log_ids: list[int], *, removed: bool = False) -> dict[int, list[schemas.LogItemOut]]:
    if not log_ids:
        return {}
    remover = aliased(User)
    stmt = (
        select(LogisticsLogItem, Proposal, remover.display_name)
        .join(Proposal, Proposal.id == LogisticsLogItem.proposal_id)
        .outerjoin(remover, remover.id == LogisticsLogItem.removed_by)
        .where(LogisticsLogItem.log_id.in_(log_ids), LogisticsLogItem.removed_at.is_not(None) if removed else LogisticsLogItem.removed_at.is_(None))
        .order_by(LogisticsLogItem.id)
    )
    out: dict[int, list[schemas.LogItemOut]] = defaultdict(list)
    for item, proposal, remover_name in (await session.execute(stmt)).all():
        out[item.log_id].append(
            schemas.LogItemOut(
                id=item.id, proposal_id=proposal.id, proposal_number=proposal.proposal_number, customer_name=proposal.customer_name,
                project_name=proposal.project_name, pd_code=_pd_of(proposal), status=item.status, added_at=item.added_at,
                removed_at=item.removed_at, removal_reason=item.removal_reason, removed_by_name=remover_name,
            )
        )
    return out


async def _events(session: AsyncSession, *, log_id: int | None = None, load_id: int | None = None) -> list[schemas.EventOut]:
    cond = LogisticsEvent.log_id == log_id if log_id is not None else LogisticsEvent.load_id == load_id
    rows = (
        await session.execute(
            select(LogisticsEvent, User.display_name)
            .outerjoin(User, User.id == LogisticsEvent.actor_user_id)
            .where(cond)
            .order_by(LogisticsEvent.created_at.desc(), LogisticsEvent.id.desc())
        )
    ).all()
    return [
        schemas.EventOut(id=e.id, text=e.text, reason=e.reason, actor_user_id=e.actor_user_id, actor_name=name, created_at=e.created_at)
        for e, name in rows
    ]


async def get_log(session: AsyncSession, log_id: int) -> schemas.LogDetail:
    row = await _get_log(session, log_id)
    items = await _items_by_log(session, [row.id])
    removed = await _items_by_log(session, [row.id], removed=True)
    data = _log_dict(row, len(items.get(row.id, [])), calendar_rules.local_today())
    return schemas.LogDetail(**data, items=items.get(row.id, []), removed_items=removed.get(row.id, []), events=await _events(session, log_id=row.id))


async def list_logs(
    session: AsyncSession, *, stage: str | None, search: str | None, in_load: bool | None, limit: int, offset: int,
) -> schemas.LogList:
    cond = []
    if stage:
        cond.append(LogisticsLog.stage == stage)
    if in_load is not None:
        cond.append(LogisticsLog.load_id.is_not(None) if in_load else LogisticsLog.load_id.is_(None))
    if search and search.strip():
        like = f"%{search.strip()}%"
        cond.append(or_(
            LogisticsLog.code.ilike(like), LogisticsLog.state.ilike(like),
            select(LogisticsLogItem.id)
            .join(Proposal, Proposal.id == LogisticsLogItem.proposal_id)
            .where(LogisticsLogItem.log_id == LogisticsLog.id, LogisticsLogItem.removed_at.is_(None), Proposal.proposal_number.ilike(like))
            .exists(),
        ))
    total = (await session.execute(select(func.count()).select_from(LogisticsLog).where(*cond))).scalar_one()
    rows = (await session.execute(select(LogisticsLog).where(*cond).order_by(LogisticsLog.stage_since, LogisticsLog.id).limit(limit).offset(offset))).scalars().all()
    counts = await _active_counts(session, [r.id for r in rows])
    today = calendar_rules.local_today()
    return schemas.LogList(items=[_log_dict(r, counts.get(r.id, 0), today) for r in rows], total=total)


async def list_eligible(session: AsyncSession, *, search: str | None, limit: int, offset: int) -> schemas.EligibleProposalList:
    """Propostas ativas, com PD de inspecao finalizada (DOC BIM em PDF) e fora de qualquer LOG ativo."""
    in_log = select(LogisticsLogItem.id).where(LogisticsLogItem.proposal_id == Proposal.id, LogisticsLogItem.removed_at.is_(None)).exists()
    cond = [
        Proposal.active.is_(True), Proposal.is_cancelled.is_(False), Proposal.order_reference.is_not(None),
        Inspection.stage == "fim", ~in_log,
    ]
    if search and search.strip():
        like = f"%{search.strip()}%"
        cond.append(or_(Proposal.proposal_number.ilike(like), Proposal.customer_name.ilike(like), Proposal.order_reference.ilike(like)))
    base = select(Proposal, Inspection).join(Inspection, func.lower(Inspection.pd_code) == func.lower(func.trim(Proposal.order_reference))).where(*cond)
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await session.execute(base.order_by(Proposal.proposal_number).limit(limit).offset(offset))).all()
    items = [
        schemas.EligibleProposalOut(
            id=p.id, proposal_number=p.proposal_number, customer_name=p.customer_name, project_name=p.project_name,
            pd_code=i.pd_code, nqt_code=i.nqt_code, state=resolve_state(p.customer_name),
        )
        for p, i in rows
    ]
    return schemas.EligibleProposalList(items=items, total=total)


# --- elegibilidade (D5) ------------------------------------------------------------------------


async def _eligible_proposals(session: AsyncSession, proposal_ids: list[int]) -> list[Proposal]:
    ids = list(dict.fromkeys(proposal_ids))
    found = {
        p.id: p
        for p in (await session.execute(select(Proposal).where(Proposal.id.in_(ids), Proposal.active.is_(True), Proposal.is_cancelled.is_(False)))).scalars().all()
    }
    out = []
    for pid in ids:
        proposal = found.get(pid)
        if proposal is None:
            raise ApiError(error_codes.LOGISTICS_PROPOSAL_NOT_FOUND, f"Proposta {pid} nao encontrada ou inativa.", status_code=404, details={"proposal_id": pid})
        pd = _pd_of(proposal)
        if not await is_pd_inspection_finished(session, pd):
            raise ApiError(
                error_codes.LOGISTICS_INSPECTION_NOT_FINISHED,
                f"A proposta {proposal.proposal_number} nao pode entrar em LOG: a inspecao do PD {pd or '(sem PD)'} nao esta finalizada (falta o DOC BIM em PDF).",
                status_code=409, details={"proposal_id": pid, "proposal_number": proposal.proposal_number, "pd_code": pd},
            )
        current = (
            await session.execute(
                select(LogisticsLog.code)
                .join(LogisticsLogItem, LogisticsLogItem.log_id == LogisticsLog.id)
                .where(LogisticsLogItem.proposal_id == pid, LogisticsLogItem.removed_at.is_(None))
            )
        ).scalars().first()
        if current:
            raise ApiError(
                error_codes.LOGISTICS_PROPOSAL_ALREADY_IN_LOG,
                f"A proposta {proposal.proposal_number} ja esta no {current}.",
                status_code=409, details={"proposal_id": pid, "proposal_number": proposal.proposal_number, "log_code": current},
            )
        out.append(proposal)
    return out


def _state_error(message: str, **details) -> ApiError:
    return ApiError(error_codes.LOGISTICS_STATE_MISMATCH, message, status_code=409, details=details)


def _check_states(proposals: list[Proposal], current: str | None) -> str | None:
    """Estado unico do LOG. `current` = estado ja definido (enviado ou do LOG). Regra mista: derivavel + nao derivavel = erro."""
    derived = {p.proposal_number: resolve_state(p.customer_name) for p in proposals}
    states = {s for s in derived.values() if s}
    if not states:
        return current
    if len(states) > 1:
        raise _state_error("Um LOG pertence a um unico estado da Equatorial, mas as propostas sao de estados diferentes: "
                           + ", ".join(f"{n} ({s or 'sem estado'})" for n, s in derived.items()) + ".", states=sorted(states))
    state = states.pop()
    unknown = [n for n, s in derived.items() if not s]
    if unknown:
        raise _state_error(f"Nao e possivel misturar propostas do {state} com propostas sem estado identificavel: {', '.join(unknown)}.", state=state, proposals=unknown)
    if current and current != state:
        raise _state_error(f"O estado do LOG ({current}) difere do estado das propostas ({state}).", state=state, log_state=current)
    return state


# --- avisos de data (calendar_rules) -----------------------------------------------------------


async def _log_warnings(
    session: AsyncSession, state: str | None, proposals: list[Proposal], *,
    requested=None, reserved=None, loading=None, delivery=None, exclude_log_id: int | None = None,
) -> list[dict]:
    """Avisos das datas informadas (None = campo nao alterado, nao avalia). R7, R2, R1/R6, R3 e R4."""
    today = calendar_rules.local_today()
    out = calendar_rules.warn_past("requested_date", requested, today)
    if reserved != requested:
        out += calendar_rules.warn_past("reserved_date", reserved, today)
    out += await calendar_rules.schedule_warnings(session, "loading_date", loading, today=today, exclude_log_id=exclude_log_id)
    out += await calendar_rules.schedule_warnings(session, "delivery_date", delivery, today=today, cd_state=state, exclude_log_id=exclude_log_id)
    if delivery is not None and loading is not None:
        out += calendar_rules.warn_delivery_before_loading(delivery, loading)
    if delivery is not None and proposals:
        done = await finished_dates(session, [p.order_reference for p in proposals])
        out += calendar_rules.warn_delivery_before_inspection(
            delivery, [(f"{p.proposal_number} (PD {_pd_of(p)})", done[_pd_of(p).lower()]) for p in proposals if _pd_of(p) and _pd_of(p).lower() in done],
        )
    return out


async def _departure_warnings(session: AsyncSession, departure: date, logs: list[LogisticsLog], *, load_id: int | None = None) -> list[dict]:
    out = await calendar_rules.schedule_warnings(session, "departure_date", departure, exclude_load_id=load_id)
    return out + calendar_rules.warn_departure_vs_loading(departure, [(lg.code, lg.loading_date) for lg in logs])


# --- LOG ----------------------------------------------------------------------------------------


async def create_log(session: AsyncSession, payload: schemas.LogCreate, actor: User, request_id: str | None = None) -> schemas.LogDetail:
    if (await session.execute(select(LogisticsLog.id).where(LogisticsLog.code == payload.code))).first():
        raise ApiError(error_codes.LOGISTICS_LOG_CODE_ALREADY_EXISTS, f"O codigo {payload.code} ja existe.", status_code=409)
    proposals = await _eligible_proposals(session, payload.proposal_ids)
    state = _check_states(proposals, payload.state)
    reserved = payload.reserved_date or payload.requested_date
    calendar_rules.ensure_dates_confirmed(
        await _log_warnings(
            session, state, proposals, requested=payload.requested_date, reserved=reserved, loading=payload.loading_date, delivery=payload.delivery_date,
        ),
        payload.confirm_dates,
    )
    row = LogisticsLog(
        code=payload.code, state=state, requested_date=payload.requested_date, reserved_date=reserved,
        loading_date=payload.loading_date, delivery_date=payload.delivery_date, stage="reservada", created_by=actor.id,
    )
    session.add(row)
    try:
        await session.flush()
        for proposal in proposals:
            session.add(LogisticsLogItem(log_id=row.id, proposal_id=proposal.id, status="ok", added_by=actor.id))
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError(error_codes.LOGISTICS_LOG_CODE_ALREADY_EXISTS, "O codigo LOG ja existe ou uma das propostas acabou de entrar em outro LOG.", status_code=409) from exc
    what = "Data reservada" if reserved == payload.requested_date else "Data pedida indisponivel, reservada a mais proxima"
    _event(session, actor, f"{what}, {row.code} gerado", log_id=row.id)
    await _audit(session, actor, "LOGISTICS_LOG_CREATED", request_id, log_id=row.id, code=row.code, proposal_ids=[p.id for p in proposals])
    await session.commit()
    return await get_log(session, row.id)


async def _move(session, log_id, actor, request_id, *, allowed: str, to: str, text: str, **fields) -> schemas.LogDetail:
    row = await _get_log(session, log_id, lock=True)
    if row.stage != allowed:
        raise ApiError(
            error_codes.LOGISTICS_INVALID_STAGE, f"Esta acao nao e permitida na etapa atual do LOG ({row.stage}).",
            status_code=409, details={"current_stage": row.stage, "allowed_stages": [allowed]},
        )
    previous = row.stage
    for name, value in fields.items():
        setattr(row, name, value)
    now = utcnow()
    row.stage, row.stage_since, row.updated_at = to, now, now
    _event(session, actor, text, log_id=row.id)
    await _audit(session, actor, "LOGISTICS_LOG_STAGE_CHANGED", request_id, log_id=row.id, code=row.code, from_stage=previous, to_stage=to)
    await session.commit()
    return await get_log(session, log_id)


async def send_docs(session, log_id, payload: schemas.DocsPayload, actor, request_id=None):
    return await _move(session, log_id, actor, request_id, allowed="reservada", to="docs", text="Documentacao enviada (NF, XML, BIM)",
                       nf_link=payload.nf_link, xml_link=payload.xml_link, bim_link=payload.bim_link)


async def approve_log(session, log_id, actor, request_id=None):
    return await _move(session, log_id, actor, request_id, allowed="docs", to="aprovada", text="Data aprovada para entrega")


async def add_proposals(session, log_id, payload: schemas.AddProposalsPayload, actor, request_id=None) -> schemas.LogDetail:
    row = await _get_log(session, log_id, lock=True)
    if row.load_id is not None:
        raise ApiError(
            error_codes.LOGISTICS_LOG_IN_LOAD, f"O {row.code} esta na carga {load_code(row.load_id)}. Tire o LOG da carga para incluir propostas.",
            status_code=409, details={"load_id": row.load_id, "load_code": load_code(row.load_id)},
        )
    proposals = await _eligible_proposals(session, payload.proposal_ids)
    _check_states(proposals, row.state)  # estado do LOG vale; proposta sem estado derivavel entra livremente num LOG manual
    try:
        for proposal in proposals:
            session.add(LogisticsLogItem(log_id=row.id, proposal_id=proposal.id, status="pendente", added_by=actor.id))
            _event(session, actor, f"{proposal.proposal_number} incluida, aguardando aprovacao", log_id=row.id)
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError(error_codes.LOGISTICS_PROPOSAL_ALREADY_IN_LOG, "Uma das propostas acabou de entrar em outro LOG.", status_code=409) from exc
    row.updated_at = utcnow()
    await _audit(session, actor, "LOGISTICS_PROPOSALS_ADDED", request_id, log_id=row.id, code=row.code, proposal_ids=[p.id for p in proposals])
    await session.commit()
    return await get_log(session, log_id)


async def _active_item(session: AsyncSession, log_id: int, item_id: int) -> tuple[LogisticsLogItem, Proposal]:
    found = (
        await session.execute(
            select(LogisticsLogItem, Proposal)
            .join(Proposal, Proposal.id == LogisticsLogItem.proposal_id)
            .where(LogisticsLogItem.id == item_id, LogisticsLogItem.log_id == log_id, LogisticsLogItem.removed_at.is_(None))
            .with_for_update(of=LogisticsLogItem)
        )
    ).first()
    if found is None:
        raise ApiError(error_codes.LOGISTICS_ITEM_NOT_FOUND, "Proposta nao encontrada neste LOG.", status_code=404)
    return found[0], found[1]


async def resolve_item(session, log_id, item_id, payload: schemas.ResolveItemPayload, actor, request_id=None) -> schemas.LogDetail:
    row = await _get_log(session, log_id, lock=True)
    item, proposal = await _active_item(session, log_id, item_id)
    if item.status != "pendente":
        raise ApiError(error_codes.LOGISTICS_ITEM_NOT_PENDING, "Esta inclusao ja foi resolvida.", status_code=409, details={"status": item.status})
    item.status = payload.result
    row.updated_at = utcnow()
    if payload.result == "reprovada":
        # Reprovada sai do LOG (fica no historico de removidas) e a proposta fica livre para outro LOG.
        item.removed_at, item.removed_by, item.removal_reason = utcnow(), actor.id, "Inclusao reprovada"
        _event(session, actor, f"Inclusao de {proposal.proposal_number} reprovada: saiu do LOG", log_id=row.id, reason="Inclusao reprovada")
    else:
        _event(session, actor, f"Inclusao de {proposal.proposal_number} aprovada", log_id=row.id)
    await _audit(session, actor, "LOGISTICS_INCLUSION_RESOLVED", request_id, log_id=row.id, code=row.code, proposal_id=proposal.id, result=payload.result)
    await session.commit()
    return await get_log(session, log_id)


async def _proposal_history(session: AsyncSession, proposal: Proposal, actor: User, request_id: str | None, text: str, **extra) -> None:
    """Registra no historico da proposta (sobrevive a exclusao do LOG/carga)."""
    from api.app.modules.proposals.service import _record_event

    await _record_event(session, proposal, "LOGISTICS_HISTORY", actor, request_id=request_id, metadata={"text": text, **{k: v for k, v in extra.items() if v}})


async def _events_dump(session: AsyncSession, *, log_id: int | None = None, load_id: int | None = None) -> list[dict]:
    """Historico em texto, gravado na auditoria antes de excluir LOG/carga (os eventos somem em cascata)."""
    return [{"at": e.created_at.isoformat(), "text": e.text, "reason": e.reason, "actor": e.actor_name} for e in reversed(await _events(session, log_id=log_id, load_id=load_id))]


async def detach_item(
    session: AsyncSession, row: LogisticsLog, item: LogisticsLogItem, proposal: Proposal, actor: User, request_id: str | None, reason: str,
) -> bool:
    """Tira a proposta do LOG (sem commit). Se era a ultima, o LOG deixa de existir, mas o historico vai para a auditoria e para a proposta.
    Retorna True se o LOG foi excluido."""
    item.removed_at, item.removed_by, item.removal_reason = utcnow(), actor.id, reason
    row.updated_at = utcnow()
    await session.flush()
    remaining = (
        await session.execute(select(func.count()).select_from(LogisticsLogItem).where(LogisticsLogItem.log_id == row.id, LogisticsLogItem.removed_at.is_(None)))
    ).scalar_one()
    await _audit(session, actor, "LOGISTICS_PROPOSAL_REMOVED", request_id, log_id=row.id, code=row.code, proposal_id=proposal.id, reason=reason)
    await _proposal_history(session, proposal, actor, request_id, f"{proposal.proposal_number} saiu do {row.code}", reason=reason, log_code=row.code)
    if remaining == 0:
        # Como no prototipo: LOG sem propostas deixa de existir (o codigo volta a ficar livre).
        history = await _events_dump(session, log_id=row.id)
        await _audit(session, actor, "LOGISTICS_LOG_DELETED", request_id, log_id=row.id, code=row.code, reason=f"Ultima proposta removida: {reason}", history=history)
        await session.delete(row)
        return True
    _event(session, actor, f"{proposal.proposal_number} removida: {reason}", log_id=row.id, reason=reason)
    return False


async def remove_item(session, log_id, item_id, payload: schemas.ReasonPayload, actor, request_id=None) -> schemas.RemoveResult:
    row = await _get_log(session, log_id, lock=True)
    if row.load_id is not None:
        raise ApiError(
            error_codes.LOGISTICS_LOG_IN_LOAD, f"O {row.code} esta na carga {load_code(row.load_id)}. Tire o LOG da carga para remover propostas.",
            status_code=409, details={"load_id": row.load_id, "load_code": load_code(row.load_id)},
        )
    item, proposal = await _active_item(session, log_id, item_id)
    deleted = await detach_item(session, row, item, proposal, actor, request_id, payload.reason)
    await session.commit()
    return schemas.RemoveResult(log_deleted=True, log=None) if deleted else schemas.RemoveResult(log_deleted=False, log=await get_log(session, log_id))


async def active_log_item_of(session: AsyncSession, proposal_id: int) -> tuple[LogisticsLog, LogisticsLogItem] | None:
    found = (
        await session.execute(
            select(LogisticsLog, LogisticsLogItem)
            .join(LogisticsLogItem, LogisticsLogItem.log_id == LogisticsLog.id)
            .where(LogisticsLogItem.proposal_id == proposal_id, LogisticsLogItem.removed_at.is_(None))
            .with_for_update(of=LogisticsLog)
        )
    ).first()
    return (found[0], found[1]) if found else None


# --- carga de entrega ---------------------------------------------------------------------------


async def _logs_for_load(session: AsyncSession, log_ids: list[int]) -> list[LogisticsLog]:
    ids = list(dict.fromkeys(log_ids))
    rows = {r.id: r for r in (await session.execute(select(LogisticsLog).where(LogisticsLog.id.in_(ids)).with_for_update())).scalars().all()}
    out = []
    for lid in ids:
        row = rows.get(lid)
        if row is None:
            raise ApiError(error_codes.LOGISTICS_LOG_NOT_FOUND, f"LOG {lid} nao encontrado.", status_code=404, details={"log_id": lid})
        if row.load_id is not None:
            raise ApiError(
                error_codes.LOGISTICS_LOG_ALREADY_IN_LOAD, f"O {row.code} ja esta na carga {load_code(row.load_id)}.",
                status_code=409, details={"log_id": lid, "load_code": load_code(row.load_id)},
            )
        if row.stage != "aprovada":
            raise ApiError(
                error_codes.LOGISTICS_LOG_NOT_APPROVED, f"O {row.code} ainda nao esta aprovado para entrega.",
                status_code=409, details={"log_id": lid, "stage": row.stage},
            )
        out.append(row)
    return out


async def _loads_out(session: AsyncSession, loads: list[LogisticsLoad]) -> list[dict]:
    logs_by_load: dict[int, list[LogisticsLog]] = defaultdict(list)
    counts: dict[int, int] = {}
    if loads:
        logs = (await session.execute(select(LogisticsLog).where(LogisticsLog.load_id.in_([x.id for x in loads])).order_by(LogisticsLog.code))).scalars().all()
        counts = await _active_counts(session, [x.id for x in logs])
        for log in logs:
            logs_by_load[log.load_id].append(log)
    return [
        {
            "id": x.id, "code": load_code(x.id), "departure_date": x.departure_date, "created_at": x.created_at, "updated_at": x.updated_at,
            "log_count": len(logs_by_load[x.id]), "proposal_count": sum(counts.get(lg.id, 0) for lg in logs_by_load[x.id]),
            "log_codes": [lg.code for lg in logs_by_load[x.id]], "states": sorted({lg.state for lg in logs_by_load[x.id]}),
        }
        for x in loads
    ]


async def list_loads(session: AsyncSession, *, limit: int, offset: int) -> schemas.LoadList:
    total = (await session.execute(select(func.count()).select_from(LogisticsLoad))).scalar_one()
    rows = (await session.execute(select(LogisticsLoad).order_by(LogisticsLoad.departure_date.desc(), LogisticsLoad.id.desc()).limit(limit).offset(offset))).scalars().all()
    return schemas.LoadList(items=[schemas.LoadOut(**d) for d in await _loads_out(session, list(rows))], total=total)


async def get_load(session: AsyncSession, load_id: int) -> schemas.LoadDetail:
    row = await _get_load(session, load_id)
    (base,) = await _loads_out(session, [row])
    logs = (await session.execute(select(LogisticsLog).where(LogisticsLog.load_id == load_id).order_by(LogisticsLog.code))).scalars().all()
    ids = [x.id for x in logs]
    items = await _items_by_log(session, ids)
    today = calendar_rules.local_today()
    detail = [schemas.LoadLogOut(**_log_dict(lg, len(items.get(lg.id, [])), today), items=items.get(lg.id, [])) for lg in logs]
    return schemas.LoadDetail(**base, logs=detail, events=await _events(session, load_id=load_id))


async def create_load(session: AsyncSession, payload: schemas.LoadCreate, actor: User, request_id: str | None = None) -> schemas.LoadDetail:
    logs = await _logs_for_load(session, payload.log_ids)
    calendar_rules.ensure_dates_confirmed(await _departure_warnings(session, payload.departure_date, logs), payload.confirm_dates)
    load = LogisticsLoad(departure_date=payload.departure_date, created_by=actor.id)
    session.add(load)
    await session.flush()
    code = load_code(load.id)
    for log in logs:
        log.load_id, log.updated_at = load.id, utcnow()
        _event(session, actor, f"Incluido na carga {code}", log_id=log.id)
    _event(session, actor, f"Carga criada com {', '.join(lg.code for lg in logs)}; saida em {_fmt(load.departure_date)}", load_id=load.id)
    await _audit(session, actor, "LOGISTICS_LOAD_CREATED", request_id, load_id=load.id, load_code=code, log_ids=[lg.id for lg in logs])
    await session.commit()
    return await get_load(session, load.id)


async def update_load(session, load_id, payload: schemas.LoadUpdate, actor, request_id=None) -> schemas.LoadDetail:
    load = await _get_load(session, load_id, lock=True)
    old = load.departure_date
    members = (await session.execute(select(LogisticsLog).where(LogisticsLog.load_id == load.id))).scalars().all()
    calendar_rules.ensure_dates_confirmed(await _departure_warnings(session, payload.departure_date, list(members), load_id=load.id), payload.confirm_dates)
    load.departure_date, load.updated_at = payload.departure_date, utcnow()
    _event(session, actor, f"Data de saida alterada de {_fmt(old)} para {_fmt(payload.departure_date)}", load_id=load.id)
    await _audit(session, actor, "LOGISTICS_LOAD_UPDATED", request_id, load_id=load.id, load_code=load_code(load.id), departure_date=payload.departure_date.isoformat())
    await session.commit()
    return await get_load(session, load_id)


async def add_log_to_load(session, load_id, payload: schemas.LogIdPayload, actor, request_id=None) -> schemas.LoadDetail:
    load = await _get_load(session, load_id, lock=True)
    (log,) = await _logs_for_load(session, [payload.log_id])
    calendar_rules.ensure_dates_confirmed(
        calendar_rules.warn_departure_vs_loading(load.departure_date, [(log.code, log.loading_date)]), payload.confirm_dates,
    )
    log.load_id, log.updated_at = load.id, utcnow()
    load.updated_at = utcnow()
    _event(session, actor, f"Incluido na carga {load_code(load.id)}", log_id=log.id)
    _event(session, actor, f"{log.code} adicionado a carga", load_id=load.id)
    await _audit(session, actor, "LOGISTICS_LOAD_LOG_ADDED", request_id, load_id=load.id, load_code=load_code(load.id), log_id=log.id, code=log.code)
    await session.commit()
    return await get_load(session, load_id)


async def remove_log_from_load(session, load_id, log_id, actor, request_id=None) -> schemas.LoadDetail:
    load = await _get_load(session, load_id, lock=True)
    log = await _get_log(session, log_id, lock=True)
    if log.load_id != load.id:
        raise ApiError(error_codes.LOGISTICS_LOG_NOT_IN_THIS_LOAD, f"O {log.code} nao esta nesta carga.", status_code=404)
    total = (await session.execute(select(func.count()).select_from(LogisticsLog).where(LogisticsLog.load_id == load.id))).scalar_one()
    if total <= 1:
        raise ApiError(error_codes.LOGISTICS_LOAD_LAST_LOG, "Uma carga precisa de ao menos um LOG. Desfaca a carga para tirar o ultimo.", status_code=409)
    log.load_id, log.updated_at = None, utcnow()
    load.updated_at = utcnow()
    _event(session, actor, f"Retirado da carga {load_code(load.id)}", log_id=log.id)
    _event(session, actor, f"{log.code} retirado da carga", load_id=load.id)
    await _audit(session, actor, "LOGISTICS_LOAD_LOG_REMOVED", request_id, load_id=load.id, load_code=load_code(load.id), log_id=log.id, code=log.code)
    await session.commit()
    return await get_load(session, load_id)


async def delete_load(session, load_id, actor, request_id=None) -> None:
    """Desfazer carga: os LOGs ficam livres; os eventos dos LOGs ficam e o historico da carga vai para a auditoria."""
    load = await _get_load(session, load_id, lock=True)
    logs = (await session.execute(select(LogisticsLog).where(LogisticsLog.load_id == load.id).with_for_update())).scalars().all()
    code = load_code(load.id)
    history = await _events_dump(session, load_id=load.id)  # os eventos da carga somem com ela: ficam na auditoria
    for log in logs:
        log.load_id, log.updated_at = None, utcnow()
        _event(session, actor, f"Carga {code} desfeita", log_id=log.id)
    await _audit(session, actor, "LOGISTICS_LOAD_DELETED", request_id, load_id=load.id, load_code=code, log_ids=[lg.id for lg in logs], history=history)
    await session.flush()
    await session.delete(load)
    await session.commit()
