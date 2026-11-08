from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core import error_codes
from api.app.core.exceptions import ApiError, PermissionDeniedError
from api.app.modules.auth import repository as auth_repository
from api.app.modules.auth.dependencies import user_has_permission
from api.app.modules.auth.models import User
from api.app.modules.auth.permissions import PROPOSALS_UPDATE
from api.app.modules.auth.tokens import utcnow
from api.app.modules.inspection import schemas
from api.app.modules.inspection.models import Inspection, InspectionEvent
from api.app.modules.inspection.pd_extraction import suggest_pd
from api.app.modules.logistics import calendar_rules
from api.app.modules.proposals.models import Proposal


def _pd_key(value: str) -> str:
    return value.strip().lower()


def _pd_match():
    """Condicao SQL: proposals.order_reference == inspections.pd_code (sem caixa/espacos)."""
    return func.lower(func.trim(Proposal.order_reference)) == func.lower(Inspection.pd_code)


def days_in_stage(since: datetime | date, today: date | None = None) -> int:
    """Dias na etapa = hoje - etapa_desde, em data LOCAL (America/Sao_Paulo), calculado na leitura."""
    since_date = calendar_rules.local_date(since) if isinstance(since, datetime) else since
    return max(0, ((today or calendar_rules.local_today()) - since_date).days)


def since_date(row: Inspection) -> date:
    return calendar_rules.local_date(row.stage_since)


def _out(row: Inspection, numbers: list[str], today: date | None = None) -> dict:
    data = {c: getattr(row, c) for c in schemas.InspectionOut.model_fields if hasattr(row, c)}
    data.update(proposal_numbers=numbers, days_in_stage=days_in_stage(since_date(row), today), finished=row.stage == "fim")
    return data


async def _numbers_by_pd(session: AsyncSession, pd_codes: list[str]) -> dict[str, list[str]]:
    if not pd_codes:
        return {}
    key = func.lower(func.trim(Proposal.order_reference))
    rows = (
        await session.execute(
            select(key, Proposal.proposal_number)
            .where(key.in_([_pd_key(p) for p in pd_codes]), Proposal.active.is_(True))
            .order_by(Proposal.proposal_number)
        )
    ).all()
    out: dict[str, list[str]] = defaultdict(list)
    for k, number in rows:
        out[k].append(number)
    return out


async def _get(session: AsyncSession, inspection_id: int, *, lock: bool = False) -> Inspection:
    stmt = select(Inspection).where(Inspection.id == inspection_id)
    if lock:
        stmt = stmt.with_for_update()
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        raise ApiError(error_codes.INSPECTION_NOT_FOUND, "Inspecao nao encontrada.", status_code=404)
    return row


def _event(session: AsyncSession, row: Inspection, actor: User, text: str, reason: str | None = None) -> None:
    session.add(InspectionEvent(inspection_id=row.id, actor_user_id=actor.id, stage=row.stage, attempt=row.attempt, text=text, reason=reason))


async def _audit(session: AsyncSession, row: Inspection, actor: User, event_type: str, request_id: str | None, **extra) -> None:
    await auth_repository.create_security_event(
        session, event_type, actor_user_id=actor.id, request_id=request_id,
        details={"inspection_id": row.id, "pd_code": row.pd_code, "stage": row.stage, "attempt": row.attempt, **extra},
    )


def _ensure_stage(row: Inspection, allowed: tuple[str, ...]) -> None:
    if row.stage not in allowed:
        raise ApiError(
            error_codes.INSPECTION_INVALID_STAGE,
            f"Esta acao nao e permitida na etapa atual da inspecao ({row.stage}).",
            status_code=409, details={"current_stage": row.stage, "allowed_stages": list(allowed)},
        )


async def _move(
    session: AsyncSession, inspection_id: int, actor: User, request_id: str | None, *,
    allowed: tuple[str, ...], to: str, text: str, reason: str | None = None, **fields,
) -> schemas.InspectionDetail:
    row = await _get(session, inspection_id, lock=True)
    _ensure_stage(row, allowed)
    previous = row.stage
    for name, value in fields.items():
        setattr(row, name, value)
    now = utcnow()
    row.stage, row.stage_since, row.updated_at = to, now, now
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError(error_codes.INSPECTION_NQT_ALREADY_EXISTS, "Esse NQT ja esta em outro PD.", status_code=409) from exc
    _event(session, row, actor, text, reason)
    await _audit(session, row, actor, "INSPECTION_STAGE_CHANGED", request_id, from_stage=previous, to_stage=to)
    await session.commit()
    return await get_inspection(session, inspection_id)


async def create_inspection(session: AsyncSession, payload: schemas.InspectionCreate, actor: User, request_id: str | None = None) -> schemas.InspectionDetail:
    key = _pd_key(payload.pd_code)
    canonical = (
        await session.execute(
            select(func.trim(Proposal.order_reference))
            .where(func.lower(func.trim(Proposal.order_reference)) == key, Proposal.active.is_(True))
            .limit(1)
        )
    ).scalars().first()
    if canonical is None:
        raise ApiError(error_codes.INSPECTION_PD_NOT_FOUND, "Nenhuma proposta ativa tem esse PD (pedido).", status_code=404)
    if (await session.execute(select(Inspection.id).where(func.lower(Inspection.pd_code) == key))).first():
        raise ApiError(error_codes.INSPECTION_ALREADY_EXISTS, "Ja existe inspecao para esse PD.", status_code=409)
    row = await _insert_inspection(session, canonical, actor, request_id)
    return await get_inspection(session, row.id)


async def _insert_inspection(session: AsyncSession, pd: str, actor: User, request_id: str | None, **audit_extra) -> Inspection:
    row = Inspection(pd_code=pd, stage="pendente", attempt=1, created_by=actor.id)
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError(error_codes.INSPECTION_ALREADY_EXISTS, "Ja existe inspecao para esse PD.", status_code=409) from exc
    _event(session, row, actor, "Solicitacao pendente")
    await _audit(session, row, actor, "INSPECTION_CREATED", request_id, **audit_extra)
    await session.commit()
    return row


# PD digitado que sera gravado em proposals.order_reference: so letras, digitos e . _ / - espaco.
_TYPED_PD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/\-]{0,59}$")


async def _inspection_id_for_pd(session: AsyncSession, pd: str | None) -> int | None:
    if not pd or not pd.strip():
        return None
    return (await session.execute(select(Inspection.id).where(func.lower(Inspection.pd_code) == _pd_key(pd)))).scalars().first()


async def ensure_can_unmark_inspection(session: AsyncSession, order_reference: str | None) -> None:
    if await _inspection_id_for_pd(session, order_reference) is not None:
        raise ApiError(
            error_codes.INSPECTION_UNMARK_BLOCKED,
            "Ja existe inspecao para o PD desta proposta; a marcacao nao pode ser removida.",
            status_code=409,
        )


async def _conflicting_proposals(session: AsyncSession, pd: str | None, proposal: Proposal) -> list[schemas.PdConflictProposalOut]:
    if not pd or not pd.strip():
        return []
    rows = (
        await session.execute(
            select(Proposal.id, Proposal.proposal_number, Proposal.customer_name)
            .where(
                func.lower(func.trim(Proposal.order_reference)) == _pd_key(pd), Proposal.active.is_(True), Proposal.id != proposal.id,
                func.lower(func.trim(Proposal.customer_name)) != proposal.customer_name.strip().lower(),
            )
            .order_by(Proposal.proposal_number)
        )
    ).all()
    return [schemas.PdConflictProposalOut(id=i, proposal_number=n, customer_name=c) for i, n, c in rows]


def _is_cancelled(proposal: Proposal) -> bool:
    from api.app.modules.proposals.service import _proposal_is_cancelled

    return _proposal_is_cancelled(proposal)


async def pd_suggestion(session: AsyncSession, proposal_id: int) -> schemas.PdSuggestionOut:
    proposal = (await session.execute(select(Proposal).where(Proposal.id == proposal_id, Proposal.active.is_(True)))).scalars().first()
    if proposal is None:
        raise ApiError(error_codes.PROPOSAL_NOT_FOUND, "Proposta nao encontrada.", status_code=404)
    pd, source = suggest_pd(proposal.order_reference, proposal.project_name)
    return schemas.PdSuggestionOut(
        proposal_id=proposal.id, proposal_number=proposal.proposal_number, customer_name=proposal.customer_name,
        is_cancelled=_is_cancelled(proposal), order_reference=proposal.order_reference, project_name=proposal.project_name,
        pd_code=pd, pd_source=source, existing_inspection_id=await _inspection_id_for_pd(session, pd),
        conflicting_proposals=await _conflicting_proposals(session, pd, proposal),
    )


async def start_from_proposal(session: AsyncSession, payload: schemas.InspectionFromProposal, actor: User, request_id: str | None = None) -> schemas.InspectionStartResult:
    from api.app.modules.proposals.service import _record_event, _touch

    if not user_has_permission(actor, PROPOSALS_UPDATE):
        raise PermissionDeniedError()
    proposal = (await session.execute(select(Proposal).where(Proposal.id == payload.proposal_id, Proposal.active.is_(True)).with_for_update())).scalars().first()
    if proposal is None:
        raise ApiError(error_codes.PROPOSAL_NOT_FOUND, "Proposta nao encontrada.", status_code=404)
    if _is_cancelled(proposal):
        raise ApiError(error_codes.PROPOSAL_CANCELLED_TERMINAL, "A proposta esta cancelada e nao pode ir para a inspecao.", status_code=409)

    current = (proposal.order_reference or "").strip()
    if current:
        if _pd_key(current) != _pd_key(payload.pd_code):
            raise ApiError(
                error_codes.INSPECTION_PD_DIFFERS_FROM_ORDER, "O PD informado difere do Pedido ja preenchido na proposta.",
                status_code=409, details={"order_reference": current},
            )
        pd = current
    else:
        if not _TYPED_PD_RE.match(payload.pd_code):
            raise ApiError(error_codes.VALIDATION_ERROR, "PD invalido: use ate 60 caracteres entre letras, digitos, espaco e . _ / -.", status_code=422)
        pd = payload.pd_code

    if not payload.confirm_customer_conflict:
        conflicts = await _conflicting_proposals(session, pd, proposal)
        if conflicts:
            raise ApiError(
                error_codes.INSPECTION_PD_CUSTOMER_CONFLICT, "Esse PD ja e Pedido de proposta de outro cliente. Confirme para continuar.",
                status_code=409, details={"proposals": [c.model_dump() for c in conflicts]},
            )

    if not current:
        proposal.order_reference = pd
        _touch(proposal, actor)
        await _record_event(
            session, proposal, "PROPOSAL_UPDATED", actor, request_id=request_id,
            metadata={"fields": ["order_reference"], "version": proposal.version, "origin": "inspection_start"},
        )

    existing = await _inspection_id_for_pd(session, pd)
    if existing is not None:
        await session.commit()
        return schemas.InspectionStartResult(**(await get_inspection(session, existing)).model_dump(), created=False)
    row = await _insert_inspection(session, pd, actor, request_id, proposal_id=proposal.id)
    return schemas.InspectionStartResult(**(await get_inspection(session, row.id)).model_dump(), created=True)


async def _to_request_rows(session: AsyncSession) -> list[schemas.InspectionToRequestOut]:
    props = (
        await session.execute(
            select(Proposal).where(Proposal.requires_inspection.is_(True), Proposal.active.is_(True), Proposal.is_cancelled.is_(False))
            .order_by(Proposal.proposal_number, Proposal.id)
        )
    ).scalars().all()
    if not props:
        return []
    have = set((await session.execute(select(func.lower(Inspection.pd_code)))).scalars().all())
    groups: dict[str, list[tuple[Proposal, str | None, str | None]]] = {}
    for p in props:
        pd, source = suggest_pd(p.order_reference, p.project_name)
        if pd and _pd_key(pd) in have:
            continue
        groups.setdefault(_pd_key(pd) if pd else f"#{p.id}", []).append((p, pd, source))
    out = []
    for members in groups.values():
        first, pd, source = members[0]
        out.append(schemas.InspectionToRequestOut(
            pd_code=pd, pd_source=source, proposal_id=first.id, proposal_numbers=[m[0].proposal_number for m in members],
            customer_name=first.customer_name,
            proposals=[schemas.ToRequestProposalOut(id=m[0].id, proposal_number=m[0].proposal_number, customer_name=m[0].customer_name) for m in members],
        ))
    return out


async def list_inspections(session: AsyncSession, *, stage: str | None, search: str | None, limit: int, offset: int) -> schemas.InspectionList:
    cond = []
    if stage == "open":
        cond.append(Inspection.stage != "fim")
    elif stage:
        cond.append(Inspection.stage == stage)
    if search and search.strip():
        like = f"%{search.strip()}%"
        cond.append(or_(
            Inspection.pd_code.ilike(like), Inspection.nqt_code.ilike(like),
            select(Proposal.id).where(_pd_match(), Proposal.active.is_(True), Proposal.proposal_number.ilike(like)).exists(),
        ))
    total = (await session.execute(select(func.count()).select_from(Inspection).where(*cond))).scalar_one()
    rows = (await session.execute(select(Inspection).where(*cond).order_by(Inspection.stage_since, Inspection.id).limit(limit).offset(offset))).scalars().all()
    numbers = await _numbers_by_pd(session, [r.pd_code for r in rows])
    finished = (await session.execute(select(func.count()).select_from(Inspection).where(Inspection.stage == "fim"))).scalar_one()
    everything = (await session.execute(select(func.count()).select_from(Inspection))).scalar_one()
    today = calendar_rules.local_today()
    to_request = await _to_request_rows(session)
    shown = to_request if stage in (None, "open") else []
    if shown and search and search.strip():
        needle = search.strip().lower()
        shown = [r for r in shown if needle in (r.pd_code or "").lower() or needle in r.customer_name.lower() or any(needle in n.lower() for n in r.proposal_numbers)]
    return schemas.InspectionList(
        items=[_out(r, numbers.get(_pd_key(r.pd_code), []), today) for r in rows], total=total,
        counts=schemas.InspectionCounts(open=everything - finished, finished=finished, to_request=len(to_request)),
        to_request=shown,
    )


async def get_inspection(session: AsyncSession, inspection_id: int) -> schemas.InspectionDetail:
    row = await _get(session, inspection_id)
    numbers = (await _numbers_by_pd(session, [row.pd_code])).get(_pd_key(row.pd_code), [])
    events = (
        await session.execute(
            select(InspectionEvent, User.display_name)
            .outerjoin(User, User.id == InspectionEvent.actor_user_id)
            .where(InspectionEvent.inspection_id == row.id)
            .order_by(InspectionEvent.created_at.desc(), InspectionEvent.id.desc())
        )
    ).all()
    data = _out(row, numbers)
    data["events"] = [
        {"id": e.id, "stage": e.stage, "attempt": e.attempt, "text": e.text, "reason": e.reason,
         "actor_user_id": e.actor_user_id, "actor_name": name, "created_at": e.created_at}
        for e, name in events
    ]
    return schemas.InspectionDetail(**data)


# --- acoes (um passo do fluxo 5.1 da spec cada) ---------------------------------------------


async def request_inspection(session, inspection_id, payload: schemas.RequestPayload, actor, request_id=None):
    to, text = ("solicitada", "Inspecao solicitada no portal") if payload.pd_registered else ("cadastro", "Aguardando cadastro do PD no portal")
    return await _move(session, inspection_id, actor, request_id, allowed=("pendente",), to=to, text=text)


async def register_pd(session, inspection_id, actor, request_id=None):
    return await _move(session, inspection_id, actor, request_id, allowed=("cadastro",), to="solicitada",
                       text="PD cadastrado, inspecao solicitada no portal")


async def register_nqt(session, inspection_id, payload: schemas.NqtPayload, actor, request_id=None):
    dup = (await session.execute(select(Inspection.id).where(Inspection.nqt_code == payload.nqt_code, Inspection.id != inspection_id))).first()
    if dup:
        raise ApiError(error_codes.INSPECTION_NQT_ALREADY_EXISTS, "Esse NQT ja esta em outro PD.", status_code=409)
    return await _move(session, inspection_id, actor, request_id, allowed=("solicitada",), to="nqt",
                       text=f"{payload.nqt_code} registrado", nqt_code=payload.nqt_code)


async def register_decision(session, inspection_id, payload: schemas.DecisionPayload, actor, request_id=None):
    if payload.decision == "dispensa":
        return await _move(session, inspection_id, actor, request_id, allowed=("nqt",), to="dispensa",
                           text="Equatorial dispensou a inspecao", decision_type="dispensa", visit_date=None)
    if payload.visit_date is None:
        raise ApiError(error_codes.VALIDATION_ERROR, "Informe a data da visita.", status_code=422)
    _ensure_stage(await _get(session, inspection_id), ("nqt",))
    calendar_rules.ensure_dates_confirmed(
        await calendar_rules.schedule_warnings(session, "visit_date", payload.visit_date, exclude_inspection_id=inspection_id), payload.confirm_dates,
    )
    return await _move(session, inspection_id, actor, request_id, allowed=("nqt",), to="inloco",
                       text=f"In loco: visita agendada para {payload.visit_date.strftime('%d/%m/%Y')}",
                       decision_type="inloco", visit_date=payload.visit_date)


async def register_pit(session, inspection_id, payload: schemas.PitPayload, actor, request_id=None):
    return await _move(session, inspection_id, actor, request_id, allowed=("dispensa",), to="doc",
                       text="PIT anexado", pit_link=payload.pit_link)


async def approve(session, inspection_id, actor, request_id=None):
    return await _move(session, inspection_id, actor, request_id, allowed=("inloco",), to="doc", text="In loco aprovada")


async def reject(session, inspection_id, payload: schemas.RejectPayload, actor, request_id=None):
    row = await _get(session, inspection_id)
    attempt = row.attempt + 1
    # attempt sobe junto com a etapa: o evento "Reprovada..." ja pertence a nova tentativa, como no prototipo.
    return await _move(session, inspection_id, actor, request_id, allowed=("inloco",), to="pendente",
                       text=f"Reprovada no in loco: {payload.reason}. Nova tentativa {attempt}", reason=payload.reason,
                       attempt=attempt, rejection_reason=payload.reason, decision_type=None, visit_date=None, pit_link=None)


async def register_doc(session, inspection_id, payload: schemas.DocPayload, actor, request_id=None):
    return await _move(session, inspection_id, actor, request_id, allowed=("doc",), to="fim",
                       text="Finalizada: DOC BIM em PDF registrado", doc_link=payload.doc_link)


# --- consulta para a Logistica ---------------------------------------------------------------


async def finished_dates(session: AsyncSession, pd_codes: list[str]) -> dict[str, date]:
    """Data (local) em que a inspecao de cada PD finalizou, por PD em minusculas."""
    keys = [_pd_key(p) for p in pd_codes if p and p.strip()]
    if not keys:
        return {}
    rows = (await session.execute(select(Inspection).where(func.lower(Inspection.pd_code).in_(keys), Inspection.stage == "fim"))).scalars().all()
    return {_pd_key(r.pd_code): since_date(r) for r in rows}


async def is_pd_inspection_finished(session: AsyncSession, pd_code: str | None) -> bool:
    """True se o PD (proposals.order_reference) tem inspecao finalizada (DOC BIM em PDF registrado)."""
    if not pd_code or not pd_code.strip():
        return False
    found = await session.execute(
        select(Inspection.id).where(func.lower(Inspection.pd_code) == _pd_key(pd_code), Inspection.stage == "fim")
    )
    return found.first() is not None


async def list_finished(session: AsyncSession, pd_code: str | None = None) -> schemas.FinishedInspectionList:
    stmt = select(Inspection).where(Inspection.stage == "fim").order_by(Inspection.pd_code)
    if pd_code and pd_code.strip():
        stmt = stmt.where(func.lower(Inspection.pd_code) == _pd_key(pd_code))
    rows = (await session.execute(stmt)).scalars().all()
    by_pd: dict[str, list[schemas.FinishedProposalOut]] = defaultdict(list)
    if rows:
        key = func.lower(func.trim(Proposal.order_reference))
        props = (
            await session.execute(
                select(key, Proposal.id, Proposal.proposal_number, Proposal.customer_name)
                .where(key.in_([_pd_key(r.pd_code) for r in rows]), Proposal.active.is_(True))
                .order_by(Proposal.proposal_number)
            )
        ).all()
        for k, pid, number, customer in props:
            by_pd[k].append(schemas.FinishedProposalOut(id=pid, proposal_number=number, customer_name=customer))
    items = [
        schemas.FinishedInspectionOut(pd_code=r.pd_code, nqt_code=r.nqt_code, doc_link=r.doc_link, finished_at=r.stage_since, proposals=by_pd.get(_pd_key(r.pd_code), []))
        for r in rows
    ]
    return schemas.FinishedInspectionList(items=items, total=len(items))
