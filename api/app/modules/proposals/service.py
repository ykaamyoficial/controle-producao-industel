from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Select, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.app.core import error_codes
from api.app.core.exceptions import ApiError
from api.app.modules.auth import repository as auth_repository
from api.app.modules.auth.models import User
from api.app.modules.proposals.domain import ProposalStateMachine
from api.app.modules.proposals.models import ExpeditionEvent, ExpeditionItem, FiscalEvent, FiscalInvoice, FiscalInvoiceItem, FiscalRecord, FiscalItem, GalvanizationLoad, GalvanizationLoadEvent, GalvanizationLoadItem, Proposal, ProposalEvent, ProposalItem, SyncRun
from api.app.modules.proposals.schemas import (
    ExpeditionItemsRequest,
    ExpeditionItemSummary,
    ExpeditionProposalDetail,
    ExpeditionProposalSummary,
    ExpeditionRemanagementDeliveryRequest,
    ExpeditionRemanageRequest,
    ExpeditionVersionRequest,
    FiscalCancelInvoiceItemRequest,
    FiscalEmissionItemInput,
    FiscalEventSummary,
    FiscalIndicators,
    FiscalInvoiceItemSummary,
    FiscalInvoiceSummary,
    FiscalItemSummary,
    FiscalRecordDetail,
    FiscalRecordSummary,
    FiscalRegisterInvoiceRequest,
    FiscalWithdrawalRequest,
    GalvanizationLoadCreate,
    GalvanizationLoadDetail,
    GalvanizationLoadSummary,
    GalvanizationLoadUpdate,
    GalvanizationLoadVersionRequest,
    GalvanizationReturnRequest,
    PaginatedExpeditionResponse,
    PaginatedFiscalResponse,
    PaginatedProposalResponse,
    PaginatedGalvanizationCandidateResponse,
    PaginatedGalvanizationLoadResponse,
    PaginatedPartialProposalResponse,
    PaginatedProductionItemResponse,
    PaginatedProductionResponse,
    PaginatedWarehouseProposalResponse,
    PartialProposalSummary,
    ProposalAdministrativeCorrectionRequest,
    ProposalCancelRequest,
    ProposalCreate,
    ProposalDetail,
    ProposalHistoryItem,
    ProposalItemCreate,
    ProposalItemDetail,
    ProposalItemSummary,
    ProposalSyncBatch,
    ProposalSyncPayload,
    ProposalStatusChangeRequest,
    ProposalUpdate,
    ProductionCompleteItemsRequest,
    ProductionItemFlowRequest,
    ProductionItemRow,
    ProductionItemWeightsRequest,
    ProductionProgress,
    ProductionProposalDetail,
    ProductionProposalListItem,
    ProductionStartRequest,
    SyncSummary,
    ProposalItemUpdate,
    WarehouseProposalSummary,
    WarehouseStatusRequest,
)


SORT_FIELDS = {
    "proposal_number": Proposal.proposal_number,
    "proposal_date": Proposal.proposal_date,
    "deadline_date": Proposal.deadline_date,
    "legacy_updated_at": Proposal.legacy_updated_at,
    "synced_at": Proposal.synced_at,
    "updated_at": Proposal.updated_at,
}
PRODUCTION_SORT_STATUS = {
    "NAO_INICIADO": 0,
    "LIBERADO_PRODUCAO": 0,
    "ITEM_PENDENTE_FABRICACAO": 1,
    "INICIADO": 2,
    "PARADO": 3,
    "FINALIZADO_PARCIAL": 4,
    "FINALIZADO": 5,
}
PRODUCTION_ACTIVE_STATUSES = {"LIBERADO_PRODUCAO", "NAO_INICIADO", "ITEM_PENDENTE_FABRICACAO", "INICIADO", "PARADO", "FINALIZADO_PARCIAL"}
PRODUCTION_STARTABLE_STATUSES = {"LIBERADO_PRODUCAO", "NAO_INICIADO", "ITEM_PENDENTE_FABRICACAO", "PARADO"}
PRODUCTION_COMPLETABLE_STATUSES = {"INICIADO", "FINALIZADO_PARCIAL"}
WAREHOUSE_STATUSES = {"AGUARDANDO_CONFIRMACAO", "EM_SEPARACAO", "SEPARADO", "SEM_PARAFUSOS", "ALMOXARIFADO_ENTREGUE", "ALMOXARIFADO_ENTREGUE_PARCIAL"}
WAREHOUSE_NEXT_STATUSES = {
    "AGUARDANDO_CONFIRMACAO": {"EM_SEPARACAO", "SEM_PARAFUSOS"},
    "EM_SEPARACAO": {"SEPARADO"},
    "SEPARADO": {"ALMOXARIFADO_ENTREGUE", "ALMOXARIFADO_ENTREGUE_PARCIAL"},
    "ALMOXARIFADO_ENTREGUE_PARCIAL": {"ALMOXARIFADO_ENTREGUE"},
}
PARTIAL_TRACKED_STATUSES = {
    "FINALIZADO_PARCIAL",
    "ITEM_PENDENTE_FABRICACAO",
    "DISPONIVEL_PARCIAL",
    "RETORNOU_PARCIAL",
    "AGUARDANDO_SEPARACAO_PARCIAL",
    "ENTREGUE_PARCIAL",
    "ALMOXARIFADO_ENTREGUE_PARCIAL",
    "NOTA_FISCAL_PARCIAL",
}
GALVANIZATION_LOAD_EDITABLE_STATUSES = {"AGUARDANDO_LIBERACAO"}
GALVANIZATION_LOAD_RETURNABLE_STATUSES = {"LIBERADA_PARA_ENVIO", "RETORNO_PARCIAL"}
EXPEDITION_ACTIVE_STATUSES = {"EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL", "SEPARACAO_INICIADA", "SEPARADO", "ENTREGUE_PARCIAL"}
SYNC_LOCK_ID = 202607200003
ADMINISTRATIVE_STATUS_OPTIONS = {
    "CONTROLE_GERAL": {"AGUARDANDO_LIBERACAO", "LIBERADO_PRODUCAO", "EM_PRODUCAO", "EM_GALVANIZACAO", "EM_EXPEDICAO", "ENTREGUE", "CANCELADA"},
    "PRODUCAO": {"NAO_INICIADO", "ITEM_PENDENTE_FABRICACAO", "INICIADO", "PARADO", "FINALIZADO_PARCIAL", "FINALIZADO"},
    "GALVANIZACAO": {"AGUARDANDO_ENVIO", "DISPONIVEL_PARCIAL", "EM_CARGA", "ENVIADO_GALVANIZACAO", "RETORNOU_PARCIAL", "RETORNOU_GALVANIZACAO"},
    "EXPEDICAO": {"EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL", "SEPARACAO_INICIADA", "SEPARADO", "ENTREGUE_PARCIAL", "ENTREGUE"},
    "ALMOXARIFADO": WAREHOUSE_STATUSES,
}
ADMINISTRATIVE_STATUS_FIELDS = {
    "CONTROLE_GERAL": "general_status",
    "PRODUCAO": "production_status",
    "GALVANIZACAO": "galvanization_status",
    "EXPEDICAO": "shipping_status",
    "ALMOXARIFADO": "warehouse_status",
}
ADMINISTRATIVE_FLOW_ORDER = ("CONTROLE_GERAL", "PRODUCAO", "GALVANIZACAO", "EXPEDICAO")


def proposal_list_item(row: Proposal):
    return {
        "id": row.id,
        "legacy_id": row.legacy_id,
        "proposal_number": row.proposal_number,
        "customer_name": row.customer_name,
        "project_name": row.project_name,
        "order_reference": row.order_reference,
        "lot": row.lot,
        "proposal_date": row.proposal_date,
        "deadline_date": row.deadline_date,
        "current_area": row.current_area,
        "current_status": row.current_status,
        "is_partial": row.is_partial,
        "is_cancelled": row.is_cancelled,
        "is_completed": row.is_completed,
        "legacy_updated_at": row.legacy_updated_at,
        "synced_at": row.synced_at,
        "version": row.version,
        "active": row.active,
    }


def item_summary(row: ProposalItem) -> ProposalItemSummary:
    return ProposalItemSummary(
        id=row.id,
        legacy_id=row.legacy_id,
        item_number=row.item_number,
        product_code=row.product_code,
        description=row.description,
        quantity=row.quantity,
        unit=row.unit,
        unit_weight=row.unit_weight,
        total_weight=row.total_weight,
        produce_internally=row.produce_internally,
        requires_galvanization=row.requires_galvanization,
        flow_defined=row.flow_defined,
        produced=row.produced,
        galvanized=row.galvanized,
        delivered=row.delivered,
        synced_at=row.synced_at,
        source_hash=row.source_hash,
        version=row.version,
        active=row.active,
        notes=row.notes,
    )


async def list_proposals(
    session: AsyncSession,
    *,
    proposal_number: str | None,
    customer: str | None,
    project: str | None,
    current_area: str | None,
    current_status: str | None,
    is_partial: bool | None,
    is_cancelled: bool | None,
    is_completed: bool | None,
    date_from,
    date_to,
    updated_after,
    sort_by: str,
    sort_dir: str,
    limit: int,
    offset: int,
) -> PaginatedProposalResponse:
    stmt = _filtered_select(
        select(Proposal),
        proposal_number=proposal_number,
        customer=customer,
        project=project,
        current_area=current_area,
        current_status=current_status,
        is_partial=is_partial,
        is_cancelled=is_cancelled,
        is_completed=is_completed,
        date_from=date_from,
        date_to=date_to,
        updated_after=updated_after,
    )
    total = int((await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
    sort_column = SORT_FIELDS.get(sort_by, Proposal.synced_at)
    order = sort_column.desc() if sort_dir == "desc" else sort_column.asc()
    rows = (await session.execute(stmt.order_by(order, Proposal.id.asc()).limit(limit).offset(offset))).scalars().all()
    return PaginatedProposalResponse(items=[proposal_list_item(row) for row in rows], total=total, limit=limit, offset=offset)


async def list_production_proposals(
    session: AsyncSession,
    *,
    search: str | None,
    status: str | None,
    limit: int,
    offset: int,
) -> PaginatedProductionResponse:
    stmt = (
        select(Proposal)
        .options(selectinload(Proposal.items))
        .where(Proposal.current_area == "PRODUCAO")
        .where(Proposal.is_cancelled.is_(False))
        .where(Proposal.active.is_(True))
    )
    if status:
        normalized_status = _production_status_value(status)
        stmt = stmt.where(or_(Proposal.production_status == normalized_status, Proposal.current_status == normalized_status))
    if search:
        value = f"%{search}%"
        stmt = stmt.where(or_(Proposal.proposal_number.ilike(value), Proposal.customer_name.ilike(value), Proposal.project_name.ilike(value), Proposal.lot.ilike(value)))
    rows = (await session.execute(stmt)).scalars().unique().all()
    active = [row for row in rows if _production_status_value(row.production_status or row.current_status) in PRODUCTION_ACTIVE_STATUSES]
    active.sort(key=lambda row: (_production_sort_key(row), -(row.updated_at.timestamp() if row.updated_at else 0), row.id))
    paged = active[offset:offset + limit]
    return PaginatedProductionResponse(items=[_production_list_item(row) for row in paged], total=len(active), limit=limit, offset=offset)


async def list_production_items(session: AsyncSession, *, search: str | None, pending: bool | None, limit: int, offset: int) -> PaginatedProductionItemResponse:
    stmt = (
        select(Proposal)
        .options(selectinload(Proposal.items))
        .where(Proposal.current_area == "PRODUCAO")
        .where(Proposal.is_cancelled.is_(False))
        .where(Proposal.active.is_(True))
    )
    if search:
        value = f"%{search}%"
        stmt = stmt.where(or_(Proposal.proposal_number.ilike(value), Proposal.customer_name.ilike(value), Proposal.project_name.ilike(value), Proposal.lot.ilike(value)))
    rows = (await session.execute(stmt)).scalars().unique().all()
    result: list[ProductionItemRow] = []
    for proposal in rows:
        status_value = _production_status_value(proposal.production_status or proposal.current_status)
        if status_value not in PRODUCTION_ACTIVE_STATUSES:
            continue
        for item in _internal_items(proposal):
            if pending is True and item.produced:
                continue
            if pending is False and not item.produced:
                continue
            result.append(_production_item_row(proposal, item, status_value))
    result.sort(key=lambda row: (row.produced, row.proposal_number, row.item_number))
    return PaginatedProductionItemResponse(items=result[offset:offset + limit], total=len(result), limit=limit, offset=offset)


async def list_partial_proposals(session: AsyncSession, *, search: str | None, limit: int, offset: int) -> PaginatedPartialProposalResponse:
    stmt = (
        select(Proposal)
        .options(
            selectinload(Proposal.items),
            selectinload(Proposal.galvanization_load_items),
            selectinload(Proposal.expedition_items).selectinload(ExpeditionItem.proposal_item),
            selectinload(Proposal.fiscal_record).selectinload(FiscalRecord.items),
        )
        .where(Proposal.active.is_(True))
        .where(Proposal.is_cancelled.is_(False))
    )
    rows = (await session.execute(stmt)).scalars().unique().all()
    needle = (search or "").strip().lower()
    filtered = []
    for proposal in rows:
        if not _proposal_has_partial_movement(proposal):
            continue
        text = " ".join([proposal.proposal_number, proposal.customer_name, proposal.project_name or "", proposal.lot or ""]).lower()
        if needle and needle not in text:
            continue
        filtered.append(proposal)
    filtered.sort(key=lambda row: (-(row.updated_at.timestamp() if row.updated_at else 0), row.proposal_number, row.id))
    paged = filtered[offset:offset + limit]
    return PaginatedPartialProposalResponse(items=[_partial_proposal_summary(row) for row in paged], total=len(filtered), limit=limit, offset=offset)


async def list_warehouse_proposals(session: AsyncSession, *, search: str | None, status: str | None, limit: int, offset: int) -> PaginatedWarehouseProposalResponse:
    stmt = (
        select(Proposal)
        .options(selectinload(Proposal.items))
        .where(Proposal.active.is_(True))
        .where(Proposal.is_cancelled.is_(False))
        .where(Proposal.warehouse_status.in_(WAREHOUSE_STATUSES))
    )
    if status:
        stmt = stmt.where(Proposal.warehouse_status == status.strip().upper())
    if search:
        value = f"%{search}%"
        stmt = stmt.where(or_(Proposal.proposal_number.ilike(value), Proposal.customer_name.ilike(value), Proposal.project_name.ilike(value), Proposal.lot.ilike(value)))
    rows = (await session.execute(stmt)).scalars().unique().all()
    rows.sort(key=lambda row: (_warehouse_sort_key(row), -(row.updated_at.timestamp() if row.updated_at else 0), row.id))
    paged = rows[offset:offset + limit]
    return PaginatedWarehouseProposalResponse(items=[_warehouse_proposal_summary(row) for row in paged], total=len(rows), limit=limit, offset=offset)


async def update_warehouse_status(session: AsyncSession, proposal_id: int, payload: WarehouseStatusRequest, actor: User, *, request_id: str | None) -> WarehouseProposalSummary:
    proposal = await get_proposal(session, proposal_id)
    _ensure_version(proposal.version, payload.version)
    next_status = payload.status
    if next_status not in WAREHOUSE_STATUSES:
        raise ApiError(error_codes.PROPOSAL_INVALID_STATE, "Status de Almoxarifado invalido.", status_code=409)
    current = proposal.warehouse_status or "AGUARDANDO_CONFIRMACAO"
    if next_status not in WAREHOUSE_NEXT_STATUSES.get(current, set()) and next_status != current:
        raise ApiError(error_codes.PROPOSAL_INVALID_STATE, "Transicao de Almoxarifado nao permitida.", status_code=409)
    proposal.warehouse_status = next_status
    _touch(proposal, actor)
    await _record_event(
        session,
        proposal,
        "WAREHOUSE_STATUS_CHANGED",
        actor,
        request_id=request_id,
        from_area="ALMOXARIFADO",
        from_status=current,
        to_area="ALMOXARIFADO",
        to_status=next_status,
        metadata={"observation": payload.observation, "version": proposal.version},
    )
    await session.commit()
    refreshed = await get_proposal(session, proposal_id)
    return _warehouse_proposal_summary(refreshed)


async def get_production_detail(session: AsyncSession, proposal_id: int) -> ProductionProposalDetail:
    proposal = await get_proposal(session, proposal_id)
    _ensure_production_area(proposal)
    return _production_detail(proposal)


async def list_galvanization_candidates(session: AsyncSession, *, search: str | None, situation: str | None = None, limit: int, offset: int) -> PaginatedGalvanizationCandidateResponse:
    proposals = (
        (await session.execute(
            select(Proposal)
            .options(selectinload(Proposal.items))
            .where(Proposal.active.is_(True))
            .where(Proposal.is_cancelled.is_(False))
            .where(or_(Proposal.current_area == "GALVANIZACAO", Proposal.galvanization_status.in_(["AGUARDANDO_ENVIO", "DISPONIVEL_PARCIAL"])))
        ))
        .scalars()
        .unique()
        .all()
    )
    rows = []
    needle = (search or "").strip().lower()
    situation_filter = (situation or "").strip().upper() or None
    for proposal in proposals:
        for item in _eligible_galvanization_items(proposal):
            available = await _galvanization_available_quantity(session, item)
            item_situation = "DISPONIVEL" if available > Decimal("0") else "EM_GALVANIZACAO"
            if situation_filter and item_situation != situation_filter:
                continue
            pending_away = await _galvanization_pending_quantity(session, item)
            row = _galvanization_candidate_item(proposal, item, available, item_situation, pending_away)
            text = " ".join(str(row.get(field) or "") for field in ("proposal_number", "customer_name", "project_name", "lot", "description", "item_number")).lower()
            if needle and needle not in text:
                continue
            rows.append(row)
    rows.sort(key=lambda row: (row["situation"] == "DISPONIVEL", row["production_completed_at"] or datetime.min.replace(tzinfo=UTC), row["proposal_id"], row["item_id"]), reverse=True)
    return PaginatedGalvanizationCandidateResponse(items=rows[offset:offset + limit], total=len(rows), limit=limit, offset=offset)


async def list_galvanization_loads(session: AsyncSession, *, status: str | None, search: str | None, limit: int, offset: int) -> PaginatedGalvanizationLoadResponse:
    stmt = select(GalvanizationLoad).options(selectinload(GalvanizationLoad.items).selectinload(GalvanizationLoadItem.proposal), selectinload(GalvanizationLoad.items).selectinload(GalvanizationLoadItem.proposal_item)).where(GalvanizationLoad.active.is_(True))
    if status:
        stmt = stmt.where(GalvanizationLoad.status == status)
    rows = (await session.execute(stmt.order_by(GalvanizationLoad.created_at.desc(), GalvanizationLoad.id.desc()))).scalars().unique().all()
    if search:
        needle = search.lower()
        rows = [load for load in rows if needle in _galvanization_load_search_text(load)]
    return PaginatedGalvanizationLoadResponse(items=[_galvanization_load_summary(row) for row in rows[offset:offset + limit]], total=len(rows), limit=limit, offset=offset)


async def get_galvanization_load_detail(session: AsyncSession, load_id: int) -> GalvanizationLoadDetail:
    load = await _get_galvanization_load(session, load_id)
    return _galvanization_load_detail(load)


async def create_galvanization_load(session: AsyncSession, payload: GalvanizationLoadCreate, actor: User, *, request_id: str | None) -> GalvanizationLoadDetail:
    load = GalvanizationLoad(
        driver_name=payload.driver_name,
        max_weight=payload.max_weight,
        expected_return_date=payload.expected_return_date,
        notes=payload.notes,
        created_by=actor.id,
        updated_by=actor.id,
    )
    session.add(load)
    await session.flush()
    load.code = f"CG{int(load.id):05d}"
    await _replace_galvanization_load_items(session, load, payload.items, actor, request_id=request_id)
    _ensure_load_capacity(load)
    await _record_load_event(session, load, "GALVANIZATION_LOAD_CREATED", actor, request_id=request_id, metadata={"items": len(payload.items)})
    await session.commit()
    return await get_galvanization_load_detail(session, int(load.id))


async def update_galvanization_load(session: AsyncSession, load_id: int, payload: GalvanizationLoadUpdate, actor: User, *, request_id: str | None) -> GalvanizationLoadDetail:
    load = await _get_galvanization_load(session, load_id)
    _ensure_load_version(load, payload.version)
    _ensure_load_editable(load)
    if payload.driver_name is not None:
        load.driver_name = payload.driver_name
    if payload.max_weight is not None:
        load.max_weight = payload.max_weight
    if "expected_return_date" in payload.model_fields_set:
        load.expected_return_date = payload.expected_return_date
    if payload.notes is not None:
        load.notes = payload.notes
    if payload.items is not None:
        await _replace_galvanization_load_items(session, load, payload.items, actor, request_id=request_id)
    _ensure_load_capacity(load)
    _touch(load, actor)
    await _record_load_event(session, load, "GALVANIZATION_LOAD_UPDATED", actor, request_id=request_id, metadata={"version": load.version})
    await session.commit()
    return await get_galvanization_load_detail(session, load_id)


async def release_galvanization_load(session: AsyncSession, load_id: int, payload: GalvanizationLoadVersionRequest, actor: User, *, request_id: str | None) -> GalvanizationLoadDetail:
    load = await _get_galvanization_load(session, load_id)
    _ensure_load_version(load, payload.version)
    if load.status != "AGUARDANDO_LIBERACAO":
        raise ApiError(error_codes.GALVANIZATION_LOAD_INVALID_STATE, "Somente cargas aguardando liberacao podem ser enviadas.", status_code=409)
    active_items = [item for item in load.items if item.active]
    if not active_items:
        raise ApiError(error_codes.GALVANIZATION_LOAD_EMPTY, "A carga nao possui itens.", status_code=409)
    now = datetime.now(UTC)
    previous = load.status
    load.status = "LIBERADA_PARA_ENVIO"
    load.sent_at = now
    for load_item in active_items:
        proposal = load_item.proposal
        from_status = proposal.galvanization_status or proposal.current_status
        proposal.current_area = "GALVANIZACAO"
        proposal.current_status = "ENVIADO_GALVANIZACAO"
        proposal.general_status = "EM_GALVANIZACAO"
        proposal.galvanization_status = "ENVIADO_GALVANIZACAO"
        _touch(proposal, actor)
        await _record_event(session, proposal, "GALVANIZATION_ITEM_SENT", actor, item_id=load_item.proposal_item_id, request_id=request_id, from_area="GALVANIZACAO", from_status=from_status, to_area="GALVANIZACAO", to_status="ENVIADO_GALVANIZACAO", metadata={"load_id": load.id, "sent_quantity": str(load_item.sent_quantity)})
    _touch(load, actor)
    await _record_load_event(session, load, "GALVANIZATION_LOAD_RELEASED", actor, request_id=request_id, from_status=previous, to_status=load.status, metadata={"observation": payload.observation})
    await session.commit()
    return await get_galvanization_load_detail(session, load_id)


async def register_galvanization_return(session: AsyncSession, load_id: int, payload: GalvanizationReturnRequest, actor: User, *, request_id: str | None) -> GalvanizationLoadDetail:
    load = await _get_galvanization_load(session, load_id)
    _ensure_load_version(load, payload.version)
    if load.status not in GALVANIZATION_LOAD_RETURNABLE_STATUSES:
        raise ApiError(error_codes.GALVANIZATION_LOAD_INVALID_STATE, "Somente cargas enviadas ou com retorno parcial podem receber retorno.", status_code=409)
    selected = _selected_return_items(load, payload)
    if not selected:
        raise ApiError(error_codes.GALVANIZATION_RETURN_INVALID, "Selecione itens ou propostas para retorno.", status_code=422)
    now = datetime.now(UTC)
    affected_proposals: set[int] = set()
    for load_item, qty in selected:
        pending = load_item.sent_quantity - load_item.returned_quantity
        if qty <= Decimal("0") or qty > pending:
            raise ApiError(error_codes.GALVANIZATION_RETURN_INVALID, "Quantidade retornada excede o saldo enviado.", status_code=409)
        previous = load_item.status
        load_item.returned_quantity = (load_item.returned_quantity + qty).quantize(Decimal("0.0001"))
        load_item.returned_weight = (load_item.returned_quantity * load_item.unit_weight).quantize(Decimal("0.0001"))
        load_item.status = "RETORNADO" if load_item.returned_quantity >= load_item.sent_quantity else "RETORNO_PARCIAL"
        load_item.returned_at = now if load_item.status == "RETORNADO" else load_item.returned_at
        _touch(load_item, actor)
        affected_proposals.add(int(load_item.proposal_id))
        await _record_load_event(session, load, "GALVANIZATION_ITEM_RETURNED", actor, load_item=load_item, request_id=request_id, from_status=previous, to_status=load_item.status, metadata={"quantity": str(qty), "observation": payload.observation})
    for proposal_id in affected_proposals:
        proposal = next(item.proposal for item in load.items if int(item.proposal_id) == proposal_id)
        await _recalculate_galvanization_proposal_state(session, proposal, actor, request_id=request_id, load_id=load.id, observation=payload.observation)
    previous_load_status = load.status
    _recalculate_load_return_state(load, now)
    _touch(load, actor)
    await _record_load_event(session, load, "GALVANIZATION_RETURN_REGISTERED", actor, request_id=request_id, from_status=previous_load_status, to_status=load.status, metadata={"affected_proposals": sorted(affected_proposals), "observation": payload.observation})
    await session.commit()
    return await get_galvanization_load_detail(session, load_id)


async def close_galvanization_load(session: AsyncSession, load_id: int, payload: GalvanizationLoadVersionRequest, actor: User, *, request_id: str | None) -> GalvanizationLoadDetail:
    load = await _get_galvanization_load(session, load_id)
    _ensure_load_version(load, payload.version)
    if load.status != "RETORNADA_GALVANIZACAO":
        raise ApiError(error_codes.GALVANIZATION_LOAD_INVALID_STATE, "A carga so pode ser encerrada depois do retorno total.", status_code=409)
    if any(item.active and item.returned_quantity < item.sent_quantity for item in load.items):
        raise ApiError(error_codes.GALVANIZATION_RETURN_INVALID, "Nao e possivel encerrar carga com item pendente.", status_code=409)
    load.closed_at = datetime.now(UTC)
    _touch(load, actor)
    await _record_load_event(session, load, "GALVANIZATION_LOAD_CLOSED", actor, request_id=request_id, metadata={"observation": payload.observation})
    await session.commit()
    return await get_galvanization_load_detail(session, load_id)


async def list_expedition_proposals(session: AsyncSession, *, search: str | None, limit: int, offset: int) -> PaginatedExpeditionResponse:
    await _sync_expedition_from_available_items(session)
    stmt = (
        select(Proposal)
        .options(selectinload(Proposal.items), selectinload(Proposal.expedition_items).selectinload(ExpeditionItem.proposal_item))
        .where(Proposal.active.is_(True))
        .where(Proposal.is_cancelled.is_(False))
    )
    rows = (await session.execute(stmt)).scalars().unique().all()
    filtered = []
    needle = (search or "").strip().lower()
    for proposal in rows:
        exp_items = _active_expedition_items(proposal)
        if not exp_items:
            continue
        if not any(item.available_quantity > item.delivered_quantity + item.remanaged_quantity for item in exp_items):
            continue
        text = " ".join([proposal.proposal_number, proposal.customer_name, proposal.project_name or "", proposal.lot or ""]).lower()
        if needle and needle not in text:
            continue
        filtered.append(proposal)
    filtered.sort(key=lambda proposal: (_expedition_sort_key(proposal), -(proposal.updated_at.timestamp() if proposal.updated_at else 0), proposal.id))
    return PaginatedExpeditionResponse(items=[_expedition_summary(row) for row in filtered[offset:offset + limit]], total=len(filtered), limit=limit, offset=offset)


async def get_expedition_detail(session: AsyncSession, proposal_id: int) -> ExpeditionProposalDetail:
    await _sync_expedition_from_available_items(session)
    proposal = await _get_expedition_proposal(session, proposal_id)
    return _expedition_detail(proposal)


async def start_expedition_separation(session: AsyncSession, proposal_id: int, payload: ExpeditionVersionRequest, actor: User, *, request_id: str | None) -> ExpeditionProposalDetail:
    proposal = await _get_expedition_proposal(session, proposal_id)
    _ensure_version(proposal.version, payload.version)
    await _ensure_expedition_items_for_proposal(session, proposal)
    items = _active_expedition_items(proposal)
    if not items:
        raise ApiError(error_codes.EXPEDITION_ITEM_NOT_AVAILABLE, "Nao existem itens disponiveis para Expedicao.", status_code=409)
    now = datetime.now(UTC)
    from_status = proposal.shipping_status or proposal.current_status
    for item in items:
        if item.status == "EM_SEPARACAO":
            item.status = "SEPARACAO_INICIADA"
            item.separation_started_at = now
            _touch(item, actor)
            await _record_expedition_event(session, proposal, "EXPEDITION_SEPARATION_STARTED", actor, expedition_item=item, request_id=request_id, from_status="EM_SEPARACAO", to_status=item.status, metadata={"observation": payload.observation})
    proposal.current_area = "EXPEDICAO"
    proposal.current_status = "SEPARACAO_INICIADA"
    proposal.shipping_status = "SEPARACAO_INICIADA"
    proposal.general_status = "EM_EXPEDICAO"
    _touch(proposal, actor)
    await _record_event(session, proposal, "EXPEDITION_SEPARATION_STARTED", actor, request_id=request_id, from_area="EXPEDICAO", from_status=from_status, to_area="EXPEDICAO", to_status="SEPARACAO_INICIADA", metadata={"observation": payload.observation})
    await session.commit()
    return await get_expedition_detail(session, proposal_id)


async def separate_expedition_items(session: AsyncSession, proposal_id: int, payload: ExpeditionItemsRequest, actor: User, *, request_id: str | None) -> ExpeditionProposalDetail:
    proposal = await _get_expedition_proposal(session, proposal_id)
    _ensure_version(proposal.version, payload.version)
    await _ensure_expedition_items_for_proposal(session, proposal)
    selected = _selected_expedition_items(proposal, payload.items)
    for exp_item, qty in selected:
        pending = exp_item.available_quantity - exp_item.separated_quantity - exp_item.remanaged_quantity
        if qty <= Decimal("0") or qty > pending:
            raise ApiError(error_codes.EXPEDITION_QUANTITY_INVALID, "Quantidade separada excede o saldo disponivel.", status_code=409)
        previous = exp_item.status
        exp_item.separated_quantity = (exp_item.separated_quantity + qty).quantize(Decimal("0.0001"))
        exp_item.status = "SEPARADO" if exp_item.separated_quantity + exp_item.remanaged_quantity >= exp_item.available_quantity else "SEPARACAO_INICIADA"
        exp_item.separated_at = datetime.now(UTC) if exp_item.status == "SEPARADO" else exp_item.separated_at
        _touch(exp_item, actor)
        await _record_expedition_event(session, proposal, "EXPEDITION_ITEM_SEPARATED", actor, expedition_item=exp_item, request_id=request_id, from_status=previous, to_status=exp_item.status, metadata={"quantity": str(qty), "observation": payload.observation})
    _recalculate_expedition_proposal_state(proposal, actor)
    await _record_event(session, proposal, "EXPEDITION_SEPARATION_RECALCULATED", actor, request_id=request_id, to_area="EXPEDICAO", to_status=proposal.current_status, metadata={"observation": payload.observation})
    await session.commit()
    return await get_expedition_detail(session, proposal_id)


async def deliver_expedition_items(session: AsyncSession, proposal_id: int, payload: ExpeditionItemsRequest, actor: User, *, request_id: str | None) -> ExpeditionProposalDetail:
    proposal = await _get_expedition_proposal(session, proposal_id)
    _ensure_version(proposal.version, payload.version)
    await _ensure_expedition_items_for_proposal(session, proposal)
    selected = _selected_expedition_items(proposal, payload.items, only_separated=True)
    now = datetime.now(UTC)
    for exp_item, qty in selected:
        pending = exp_item.separated_quantity - exp_item.delivered_quantity
        if qty <= Decimal("0") or qty > pending:
            raise ApiError(error_codes.EXPEDITION_QUANTITY_INVALID, "Quantidade entregue excede o saldo separado.", status_code=409)
        previous = exp_item.status
        exp_item.delivered_quantity = (exp_item.delivered_quantity + qty).quantize(Decimal("0.0001"))
        exp_item.status = "ENTREGUE" if exp_item.delivered_quantity + exp_item.remanaged_quantity >= exp_item.available_quantity else "ENTREGUE_PARCIAL"
        exp_item.delivered_at = now
        if exp_item.status == "ENTREGUE":
            exp_item.proposal_item.delivered = True
            exp_item.proposal_item.delivered_at = now
            _touch(exp_item.proposal_item, actor)
        _touch(exp_item, actor)
        await _record_expedition_event(session, proposal, "EXPEDITION_ITEM_DELIVERED", actor, expedition_item=exp_item, request_id=request_id, from_status=previous, to_status=exp_item.status, metadata={"quantity": str(qty), "observation": payload.observation})
    _recalculate_expedition_proposal_state(proposal, actor)
    await _record_event(session, proposal, "EXPEDITION_DELIVERY_RECALCULATED", actor, request_id=request_id, to_area=proposal.current_area, to_status=proposal.current_status, metadata={"observation": payload.observation})
    await session.commit()
    return await get_expedition_detail(session, proposal_id)


async def remanage_expedition_items(session: AsyncSession, proposal_id: int, payload: ExpeditionRemanageRequest, actor: User, *, request_id: str | None) -> ExpeditionProposalDetail:
    proposal = await _get_expedition_proposal(session, proposal_id)
    _ensure_version(proposal.version, payload.version)
    await _ensure_expedition_items_for_proposal(session, proposal)
    selected = _selected_expedition_items(proposal, payload.items)
    for exp_item, qty in selected:
        pending = exp_item.available_quantity - exp_item.delivered_quantity - exp_item.remanaged_quantity
        if qty <= Decimal("0") or qty > pending:
            raise ApiError(error_codes.EXPEDITION_REMANAGEMENT_INVALID, "Quantidade remanejada excede o saldo pendente.", status_code=409)
        previous = exp_item.status
        exp_item.remanaged_quantity = (exp_item.remanaged_quantity + qty).quantize(Decimal("0.0001"))
        exp_item.separated_quantity = min(exp_item.separated_quantity, exp_item.available_quantity - exp_item.remanaged_quantity)
        exp_item.status = "REMANEJADO" if exp_item.delivered_quantity + exp_item.remanaged_quantity >= exp_item.available_quantity else "ENTREGUE_PARCIAL"
        exp_item.proposal_item.produced = False
        exp_item.proposal_item.galvanized = False if exp_item.proposal_item.requires_galvanization == "SIM" else exp_item.proposal_item.galvanized
        _touch(exp_item.proposal_item, actor)
        _touch(exp_item, actor)
        await _record_expedition_event(session, proposal, "EXPEDITION_ITEM_REMANAGED", actor, expedition_item=exp_item, request_id=request_id, from_status=previous, to_status=exp_item.status, metadata={"quantity": str(qty), "reason": payload.reason})
    proposal.current_area = "PRODUCAO"
    proposal.current_status = "ITEM_PENDENTE_FABRICACAO"
    proposal.general_status = "EM_PRODUCAO"
    proposal.production_status = "ITEM_PENDENTE_FABRICACAO"
    proposal.shipping_status = "ENTREGUE_PARCIAL" if any(item.delivered_quantity > 0 for item in _active_expedition_items(proposal)) else "EM_SEPARACAO"
    proposal.has_production_pending = True
    proposal.flow_situation = "PARCIAL_COM_PENDENCIA"
    _touch(proposal, actor)
    await _record_event(session, proposal, "EXPEDITION_REMANAGEMENT_TO_PRODUCTION", actor, request_id=request_id, from_area="EXPEDICAO", to_area="PRODUCAO", to_status="ITEM_PENDENTE_FABRICACAO", metadata={"reason": payload.reason})
    await session.commit()
    return await get_expedition_detail(session, proposal_id)


async def deliver_proposal_by_remanagement(session: AsyncSession, proposal_id: int, payload: ExpeditionRemanagementDeliveryRequest, actor: User, *, request_id: str | None) -> ProposalDetail:
    destination = await get_proposal(session, proposal_id)
    source = await _get_expedition_proposal(session, payload.source_proposal_id)
    _ensure_version(destination.version, payload.version)
    _ensure_version(source.version, payload.source_version)
    if destination.is_cancelled or not destination.active:
        raise ApiError(error_codes.EXPEDITION_INVALID_STATE, "Proposta de destino nao pode receber entrega.", status_code=409)
    await _ensure_expedition_items_for_proposal(session, source)
    selected = _selected_expedition_items(source, payload.items)
    for exp_item, qty in selected:
        pending = exp_item.available_quantity - exp_item.delivered_quantity - exp_item.remanaged_quantity
        if qty <= Decimal("0") or qty > pending:
            raise ApiError(error_codes.EXPEDITION_REMANAGEMENT_INVALID, "Quantidade remanejada excede o saldo pendente.", status_code=409)
        previous = exp_item.status
        exp_item.remanaged_quantity = (exp_item.remanaged_quantity + qty).quantize(Decimal("0.0001"))
        exp_item.separated_quantity = min(exp_item.separated_quantity, exp_item.available_quantity - exp_item.remanaged_quantity)
        exp_item.status = "REMANEJADO" if exp_item.delivered_quantity + exp_item.remanaged_quantity >= exp_item.available_quantity else "ENTREGUE_PARCIAL"
        exp_item.proposal_item.produced = False
        if exp_item.proposal_item.requires_galvanization == "SIM":
            exp_item.proposal_item.galvanized = False
        _touch(exp_item.proposal_item, actor)
        _touch(exp_item, actor)
        await _record_expedition_event(session, source, "EXPEDITION_ITEM_REMANAGED_TO_EARLY_DELIVERY", actor, expedition_item=exp_item, request_id=request_id, from_status=previous, to_status=exp_item.status, metadata={"quantity": str(qty), "destination_proposal_id": destination.id, "reason": payload.reason})
    source.current_area = "PRODUCAO"
    source.current_status = "ITEM_PENDENTE_FABRICACAO"
    source.general_status = "EM_PRODUCAO"
    source.production_status = "ITEM_PENDENTE_FABRICACAO"
    source.shipping_status = "ENTREGUE_PARCIAL" if any(item.delivered_quantity > 0 for item in _all_expedition_items(source)) else "EM_SEPARACAO"
    source.has_production_pending = True
    source.flow_situation = "PARCIAL_COM_PENDENCIA"
    _touch(source, actor)
    now = datetime.now(UTC)
    for item in _active_items(destination):
        item.delivered = True
        item.delivered_at = now
        _touch(item, actor)
    destination.current_area = "FINALIZADO"
    destination.current_status = "ENTREGUE"
    destination.general_status = "ENTREGUE"
    destination.shipping_status = "ENTREGUE"
    destination.is_completed = True
    destination.flow_situation = "ENTREGA_COM_REMANEJAMENTO"
    _touch(destination, actor)
    await _record_event(session, destination, "EXPEDITION_EARLY_DELIVERY_BY_REMANAGEMENT", actor, request_id=request_id, from_area=destination.current_area, to_area="FINALIZADO", to_status="ENTREGUE", metadata={"source_proposal_id": source.id, "reason": payload.reason})
    await _record_event(session, source, "EXPEDITION_REMANAGEMENT_TO_PRODUCTION", actor, request_id=request_id, from_area="EXPEDICAO", to_area="PRODUCAO", to_status="ITEM_PENDENTE_FABRICACAO", metadata={"destination_proposal_id": destination.id, "reason": payload.reason})
    await session.commit()
    return proposal_detail(await get_proposal(session, proposal_id))


async def list_fiscal_records(session: AsyncSession, *, search: str | None, status: str | None, situation: str | None, limit: int, offset: int) -> PaginatedFiscalResponse:
    if await _sync_fiscal_records(session):
        await session.commit()
    rows = await _load_fiscal_records(session)
    needle = (search or "").strip().lower()
    filtered = []
    for record in rows:
        row_situation = _fiscal_situation(record)
        if status and record.status_fiscal != status:
            continue
        if situation and row_situation != situation:
            continue
        text = " ".join([record.proposal.proposal_number, record.proposal.customer_name, record.proposal.project_name or "", record.proposal.lot or ""]).lower()
        if needle and needle not in text:
            continue
        filtered.append(record)
    filtered.sort(key=lambda record: (_fiscal_sort_key(record), record.entry_date, -record.id))
    return PaginatedFiscalResponse(items=[_fiscal_record_summary(row) for row in filtered[offset:offset + limit]], total=len(filtered), limit=limit, offset=offset)


async def get_fiscal_detail(session: AsyncSession, fiscal_record_id: int) -> FiscalRecordDetail:
    if await _sync_fiscal_records(session):
        await session.commit()
    record = await _get_fiscal_record(session, fiscal_record_id)
    return _fiscal_record_detail(record)


async def fiscal_indicators(session: AsyncSession) -> FiscalIndicators:
    if await _sync_fiscal_records(session):
        await session.commit()
    rows = await _load_fiscal_records(session)
    falta = [row for row in rows if row.status_fiscal == "FALTA_EMITIR_NOTA_FISCAL"]
    partial = [row for row in rows if row.status_fiscal == "NOTA_FISCAL_PARCIAL"]
    emitted = [row for row in rows if row.status_fiscal == "NOTA_FISCAL_EMITIDA"]
    critical = [row for row in rows if _fiscal_situation(row) == "PENDENCIA_FISCAL_CRITICA"]
    old = [row for row in rows if _fiscal_older_than_7_days(row)]
    pending_weight = sum((_fiscal_pending_weight(row) for row in rows if row.status_fiscal != "NOTA_FISCAL_EMITIDA"), Decimal("0")).quantize(Decimal("0.0001"))
    billed_weight = sum((sum((item.billed_weight for item in row.items if item.active), Decimal("0")) for row in rows), Decimal("0")).quantize(Decimal("0.0001"))
    return FiscalIndicators(
        falta_emitir=len(falta),
        nf_parcial=len(partial),
        nf_emitida=len(emitted),
        pendencia_critica=len(critical),
        entregues_sem_nf=len(critical),
        peso_pendente=pending_weight,
        peso_faturado=billed_weight,
        mais_7_dias_sem_emissao=len(old),
    )


async def fiscal_indicator_records(session: AsyncSession, indicator: str) -> list[FiscalRecordSummary]:
    if await _sync_fiscal_records(session):
        await session.commit()
    rows = await _load_fiscal_records(session)
    if indicator == "falta_emitir":
        rows = [row for row in rows if row.status_fiscal == "FALTA_EMITIR_NOTA_FISCAL"]
    elif indicator == "nf_parcial":
        rows = [row for row in rows if row.status_fiscal == "NOTA_FISCAL_PARCIAL"]
    elif indicator == "nf_emitida":
        rows = [row for row in rows if row.status_fiscal == "NOTA_FISCAL_EMITIDA"]
    elif indicator in {"pendencia_critica", "entregues_sem_nf"}:
        rows = [row for row in rows if _fiscal_situation(row) == "PENDENCIA_FISCAL_CRITICA"]
    elif indicator == "mais_7_dias_sem_emissao":
        rows = [row for row in rows if _fiscal_older_than_7_days(row)]
    elif indicator == "peso_pendente":
        rows = [row for row in rows if _fiscal_pending_weight(row) > 0]
    elif indicator == "peso_faturado":
        rows = [row for row in rows if sum((item.billed_weight for item in row.items if item.active), Decimal("0")) > 0]
    else:
        rows = []
    return [_fiscal_record_summary(row) for row in rows]


async def register_fiscal_invoice(session: AsyncSession, fiscal_record_id: int, payload: FiscalRegisterInvoiceRequest, actor: User, *, request_id: str | None) -> FiscalRecordDetail:
    record = await _get_fiscal_record(session, fiscal_record_id)
    _ensure_fiscal_version(record, payload.version)
    if record.status_fiscal == "NOTA_FISCAL_EMITIDA":
        raise ApiError(error_codes.FISCAL_INVALID_STATE, "Esta proposta ja esta fiscalmente concluida.", status_code=409)
    await _ensure_fiscal_items_for_record(session, record)
    existing = (await session.execute(
        select(FiscalInvoice)
        .where(FiscalInvoice.invoice_number == payload.invoice_number)
        .where(FiscalInvoice.series.is_(None) if payload.series is None else FiscalInvoice.series == payload.series)
        .where(FiscalInvoice.active.is_(True))
        .where(FiscalInvoice.status != "CANCELADA")
    )).scalars().first()
    if existing is not None:
        raise ApiError(error_codes.FISCAL_INVOICE_DUPLICATED, "Ja existe nota fiscal registrada com este numero e serie.", status_code=409)
    selected = _selected_fiscal_items(record, payload.items)
    if not selected and record.items:
        raise ApiError(error_codes.FISCAL_ITEM_INVALID, "Selecione pelo menos um item fiscal.", status_code=409)
    now = datetime.now(UTC)
    previous = record.status_fiscal
    invoice = FiscalInvoice(
        fiscal_record_id=record.id,
        proposal_id=record.proposal_id,
        invoice_number=payload.invoice_number,
        series=payload.series or None,
        access_key=payload.access_key or None,
        issued_at=payload.issued_at or now,
        source=payload.source,
        observation=payload.observation,
        created_by=actor.id,
        updated_by=actor.id,
    )
    session.add(invoice)
    await session.flush()
    for item, qty, weight in selected:
        item.billed_quantity = (item.billed_quantity + qty).quantize(Decimal("0.0001"))
        item.billed_weight = (item.billed_weight + weight).quantize(Decimal("0.0001"))
        _recalculate_fiscal_item_status(item)
        _touch(item, actor)
        session.add(
            FiscalInvoiceItem(
                fiscal_invoice_id=invoice.id,
                fiscal_item_id=item.id,
                proposal_id=record.proposal_id,
                proposal_item_id=item.proposal_item_id,
                quantity=qty,
                weight=weight,
                created_by=actor.id,
            )
        )
    if not record.items:
        record.status_fiscal = "NOTA_FISCAL_EMITIDA"
        record.fiscal_situation = "NF_EMITIDA"
        invoice.emission_type = "TOTAL"
    else:
        _recalculate_fiscal_record(record)
        invoice.emission_type = "TOTAL" if record.status_fiscal == "NOTA_FISCAL_EMITIDA" else "PARCIAL"
    record.last_emission_at = now
    record.observation = payload.observation
    _touch(record, actor)
    _touch(invoice, actor)
    await _record_fiscal_event(session, record, "FISCAL_INVOICE_REGISTERED", actor, fiscal_invoice=invoice, request_id=request_id, from_status=previous, to_status=record.status_fiscal, metadata={"invoice_number": invoice.invoice_number})
    await session.commit()
    session.expire_all()
    return await get_fiscal_detail(session, fiscal_record_id)


async def cancel_fiscal_invoice_item(session: AsyncSession, invoice_item_id: int, payload: FiscalCancelInvoiceItemRequest, actor: User, *, request_id: str | None) -> FiscalRecordDetail:
    invoice_item = (
        (await session.execute(
            select(FiscalInvoiceItem)
            .options(
                selectinload(FiscalInvoiceItem.fiscal_item).selectinload(FiscalItem.fiscal_record).selectinload(FiscalRecord.proposal),
                selectinload(FiscalInvoiceItem.invoice),
            )
            .where(FiscalInvoiceItem.id == invoice_item_id)
        ))
        .scalars()
        .first()
    )
    if invoice_item is None or not invoice_item.active:
        raise ApiError(error_codes.FISCAL_ITEM_INVALID, "Vinculo fiscal nao encontrado.", status_code=404)
    record = await _get_fiscal_record(session, invoice_item.fiscal_item.fiscal_record_id)
    _ensure_fiscal_version(record, payload.version)
    previous = record.status_fiscal
    item = next(row for row in record.items if row.id == invoice_item.fiscal_item_id)
    item.billed_quantity = max(Decimal("0"), (item.billed_quantity - invoice_item.quantity)).quantize(Decimal("0.0001"))
    item.billed_weight = max(Decimal("0"), (item.billed_weight - invoice_item.weight)).quantize(Decimal("0.0001"))
    _recalculate_fiscal_item_status(item)
    _touch(item, actor)
    invoice_item.active = False
    invoice_item.cancelled_at = datetime.now(UTC)
    invoice_item.cancelled_by = actor.id
    invoice_item.cancel_reason = payload.reason
    _recalculate_fiscal_record(record)
    _touch(record, actor)
    await _record_fiscal_event(session, record, "FISCAL_INVOICE_ITEM_CANCELLED", actor, fiscal_item=item, fiscal_invoice=invoice_item.invoice, request_id=request_id, from_status=previous, to_status=record.status_fiscal, metadata={"invoice_item_id": invoice_item_id, "reason": payload.reason})
    record_id = record.id
    await session.commit()
    session.expire_all()
    return await get_fiscal_detail(session, record_id)


async def mark_fiscal_invoice_withdrawn(session: AsyncSession, fiscal_record_id: int, payload: FiscalWithdrawalRequest, actor: User, *, request_id: str | None) -> FiscalRecordDetail:
    record = await _get_fiscal_record(session, fiscal_record_id)
    _ensure_fiscal_version(record, payload.version)
    if record.status_fiscal != "NOTA_FISCAL_EMITIDA":
        raise ApiError(error_codes.FISCAL_INVALID_STATE, "A NF precisa estar emitida antes de ser marcada como retirada.", status_code=409)
    previous = record.fiscal_situation
    record.fiscal_situation = "NF_RETIRADA_CLIENTE"
    record.invoice_withdrawn_at = datetime.now(UTC)
    record.withdrawn_by = actor.id
    record.withdrawal_observation = payload.observation
    _touch(record, actor)
    await _record_fiscal_event(session, record, "FISCAL_INVOICE_WITHDRAWN", actor, request_id=request_id, from_status=previous, to_status=record.fiscal_situation, metadata={"observation": payload.observation})
    await session.commit()
    session.expire_all()
    return await get_fiscal_detail(session, fiscal_record_id)


async def _load_fiscal_records(session: AsyncSession) -> list[FiscalRecord]:
    return (
        (await session.execute(
            select(FiscalRecord)
            .options(
                selectinload(FiscalRecord.proposal).selectinload(Proposal.items),
                selectinload(FiscalRecord.items).selectinload(FiscalItem.proposal_item),
                selectinload(FiscalRecord.invoices).selectinload(FiscalInvoice.items).selectinload(FiscalInvoiceItem.fiscal_item).selectinload(FiscalItem.proposal_item),
                selectinload(FiscalRecord.events),
            )
            .where(FiscalRecord.active.is_(True))
        ))
        .scalars()
        .unique()
        .all()
    )


async def _get_fiscal_record(session: AsyncSession, fiscal_record_id: int) -> FiscalRecord:
    record = (
        (await session.execute(
            select(FiscalRecord)
            .options(
                selectinload(FiscalRecord.proposal).selectinload(Proposal.items),
                selectinload(FiscalRecord.items).selectinload(FiscalItem.proposal_item),
                selectinload(FiscalRecord.invoices).selectinload(FiscalInvoice.items).selectinload(FiscalInvoiceItem.fiscal_item).selectinload(FiscalItem.proposal_item),
                selectinload(FiscalRecord.events),
            )
            .where(FiscalRecord.id == fiscal_record_id)
        ))
        .scalars()
        .unique()
        .first()
    )
    if record is None:
        raise ApiError(error_codes.FISCAL_RECORD_NOT_FOUND, "Controle fiscal nao encontrado.", status_code=404)
    return record


async def _sync_fiscal_records(session: AsyncSession) -> bool:
    proposals = (
        (await session.execute(
            select(Proposal)
            .options(selectinload(Proposal.items), selectinload(Proposal.fiscal_record).selectinload(FiscalRecord.items))
            .where(Proposal.active.is_(True))
            .where(Proposal.is_cancelled.is_(False))
        ))
        .scalars()
        .unique()
        .all()
    )
    changed = False
    today = datetime.now(UTC).date()
    for proposal in proposals:
        if proposal.fiscal_record is None:
            record = FiscalRecord(proposal_id=proposal.id, entry_date=today, observation="Entrada fiscal oficial automatica.")
            record.proposal = proposal
            session.add(record)
            await session.flush()
            changed = await _ensure_fiscal_items_for_record(session, record) or changed
            changed = True
        else:
            changed = await _ensure_fiscal_items_for_record(session, proposal.fiscal_record) or changed
    if changed:
        await session.flush()
    return changed


async def _ensure_fiscal_items_for_record(session: AsyncSession, record: FiscalRecord) -> bool:
    existing = {
        int(proposal_item_id)
        for proposal_item_id in (
            await session.execute(
                select(FiscalItem.proposal_item_id)
                .where(FiscalItem.fiscal_record_id == record.id)
                .where(FiscalItem.active.is_(True))
            )
        ).scalars()
    }
    proposal_items = (
        (
            await session.execute(
                select(ProposalItem)
                .where(ProposalItem.proposal_id == record.proposal_id)
                .where(ProposalItem.active.is_(True))
                .order_by(ProposalItem.item_number, ProposalItem.id)
            )
        )
        .scalars()
        .all()
    )
    changed = False
    for proposal_item in proposal_items:
        if not proposal_item.active or int(proposal_item.id) in existing:
            continue
        fiscal_item = FiscalItem(
            fiscal_record_id=record.id,
            proposal_id=record.proposal_id,
            proposal_item_id=proposal_item.id,
            total_quantity=proposal_item.quantity,
            total_weight=proposal_item.total_weight,
        )
        fiscal_item.proposal_item = proposal_item
        session.add(fiscal_item)
        changed = True
    await session.flush()
    return changed


def _selected_fiscal_items(record: FiscalRecord, payload_items) -> list[tuple[FiscalItem, Decimal, Decimal]]:
    active = [item for item in record.items if item.active and item.status != "FATURADO"]
    by_fiscal = {int(item.id): item for item in active}
    by_proposal_item = {int(item.proposal_item_id): item for item in active}
    selected = payload_items or [FiscalEmissionItemInput(fiscal_item_id=item.id) for item in active]
    prepared = []
    seen: set[int] = set()
    for row in selected:
        item = by_fiscal.get(int(row.fiscal_item_id or 0)) if row.fiscal_item_id is not None else by_proposal_item.get(int(row.proposal_item_id or 0))
        if item is None:
            raise ApiError(error_codes.FISCAL_ITEM_INVALID, "Item fiscal invalido para esta proposta.", status_code=409)
        if int(item.id) in seen:
            raise ApiError(error_codes.FISCAL_ITEM_INVALID, "Item fiscal duplicado na nota.", status_code=409)
        seen.add(int(item.id))
        if row.version is not None:
            _ensure_version(item.version, row.version)
        pending_qty = (item.total_quantity - item.billed_quantity).quantize(Decimal("0.0001"))
        pending_weight = (item.total_weight - item.billed_weight).quantize(Decimal("0.0001"))
        qty = (row.quantity or pending_qty).quantize(Decimal("0.0001"))
        weight = (row.weight if row.weight is not None else pending_weight).quantize(Decimal("0.0001"))
        if qty <= Decimal("0") and weight <= Decimal("0"):
            continue
        if qty > pending_qty or weight > pending_weight:
            raise ApiError(error_codes.FISCAL_QUANTITY_EXCEEDED, "Quantidade ou peso fiscal excede o saldo pendente.", status_code=409)
        prepared.append((item, qty, weight))
    return prepared


def _ensure_fiscal_version(record: FiscalRecord, expected: int) -> None:
    if record.version != expected:
        raise ApiError(error_codes.FISCAL_VERSION_CONFLICT, "O controle fiscal foi alterado por outro usuario. Recarregue os dados.", status_code=409)


def _recalculate_fiscal_item_status(item: FiscalItem) -> None:
    qty_done = item.billed_quantity >= item.total_quantity
    weight_done = item.total_weight == Decimal("0") or item.billed_weight >= item.total_weight
    if qty_done and weight_done:
        item.status = "FATURADO"
    elif item.billed_quantity > Decimal("0") or item.billed_weight > Decimal("0"):
        item.status = "PARCIAL"
    else:
        item.status = "PENDENTE"


def _recalculate_fiscal_record(record: FiscalRecord) -> None:
    active = [item for item in record.items if item.active]
    if active and all(item.status == "FATURADO" for item in active):
        record.status_fiscal = "NOTA_FISCAL_EMITIDA"
        record.fiscal_situation = "NF_EMITIDA"
    elif any(item.status in {"PARCIAL", "FATURADO"} for item in active):
        record.status_fiscal = "NOTA_FISCAL_PARCIAL"
        record.fiscal_situation = "NF_PARCIAL"
    else:
        record.status_fiscal = "FALTA_EMITIR_NOTA_FISCAL"
        record.fiscal_situation = "AGUARDANDO_NF"


def _fiscal_situation(record: FiscalRecord) -> str:
    if record.fiscal_situation == "NF_RETIRADA_CLIENTE":
        return "NF_RETIRADA_CLIENTE"
    if record.status_fiscal == "NOTA_FISCAL_EMITIDA":
        return "NF_EMITIDA"
    if record.status_fiscal == "NOTA_FISCAL_PARCIAL":
        return "NF_PARCIAL"
    if record.proposal.shipping_status == "ENTREGUE":
        return "PENDENCIA_FISCAL_CRITICA"
    if record.proposal.shipping_status in {"EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL", "SEPARACAO_INICIADA", "SEPARADO", "ENTREGUE_PARCIAL"}:
        return "DISPONIVEL_PARA_EMISSAO"
    return "CP_EM_PROCESSAMENTO"


def _fiscal_sort_key(record: FiscalRecord) -> int:
    order = {"PENDENCIA_FISCAL_CRITICA": 0, "DISPONIVEL_PARA_EMISSAO": 1, "NF_PARCIAL": 2, "CP_EM_PROCESSAMENTO": 3, "NF_EMITIDA": 4, "NF_RETIRADA_CLIENTE": 5}
    return order.get(_fiscal_situation(record), 99)


def _fiscal_older_than_7_days(record: FiscalRecord) -> bool:
    return bool(record.status_fiscal != "NOTA_FISCAL_EMITIDA" and record.last_emission_at is None and (datetime.now(UTC).date() - record.entry_date).days > 7)


def _fiscal_pending_weight(record: FiscalRecord) -> Decimal:
    return sum(((item.total_weight - item.billed_weight) for item in record.items if item.active), Decimal("0")).quantize(Decimal("0.0001"))


def _fiscal_record_summary(record: FiscalRecord) -> FiscalRecordSummary:
    active_items = [item for item in record.items if item.active]
    pending = [item for item in active_items if item.status != "FATURADO"]
    billed = [item for item in active_items if item.status == "FATURADO"]
    total_weight = sum((item.total_weight for item in active_items), Decimal("0")).quantize(Decimal("0.0001"))
    billed_weight = sum((item.billed_weight for item in active_items), Decimal("0")).quantize(Decimal("0.0001"))
    pending_weight = (total_weight - billed_weight).quantize(Decimal("0.0001"))
    situation = _fiscal_situation(record)
    return FiscalRecordSummary(
        id=record.id,
        proposal_id=record.proposal_id,
        proposal_number=record.proposal.proposal_number,
        customer_name=record.proposal.customer_name,
        project_name=record.proposal.project_name,
        lot=record.proposal.lot,
        current_area=record.proposal.current_area,
        current_status=record.proposal.current_status,
        shipping_status=record.proposal.shipping_status,
        status_fiscal=record.status_fiscal,
        fiscal_situation=situation,
        entry_date=record.entry_date,
        last_emission_at=record.last_emission_at,
        invoice_withdrawn_at=record.invoice_withdrawn_at,
        version=record.version,
        item_count=len(active_items),
        pending_items=len(pending),
        billed_items=len(billed),
        total_weight=total_weight,
        billed_weight=billed_weight,
        pending_weight=pending_weight,
        critical_pending=situation == "PENDENCIA_FISCAL_CRITICA",
        older_than_7_days=_fiscal_older_than_7_days(record),
        actions=_fiscal_actions(record),
    )


def _fiscal_record_detail(record: FiscalRecord) -> FiscalRecordDetail:
    data = _fiscal_record_summary(record).model_dump()
    items = [_fiscal_item_summary(item) for item in sorted([item for item in record.items if item.active], key=lambda row: (row.proposal_item.item_number, row.id))]
    invoices = [_fiscal_invoice_summary(invoice) for invoice in sorted([invoice for invoice in record.invoices if invoice.active], key=lambda row: (row.issued_at, row.id), reverse=True)]
    events = [FiscalEventSummary(id=event.id, event_type=event.event_type, from_status=event.from_status, to_status=event.to_status, actor_user_id=event.actor_user_id, created_at=event.created_at, metadata=event.metadata_) for event in sorted(record.events, key=lambda row: (row.created_at, row.id), reverse=True)]
    return FiscalRecordDetail(**data, items=items, invoices=invoices, events=events)


def _fiscal_item_summary(item: FiscalItem) -> FiscalItemSummary:
    return FiscalItemSummary(
        id=item.id,
        fiscal_record_id=item.fiscal_record_id,
        proposal_id=item.proposal_id,
        proposal_item_id=item.proposal_item_id,
        item_number=item.proposal_item.item_number,
        product_code=item.proposal_item.product_code,
        description=item.proposal_item.description,
        total_quantity=item.total_quantity,
        billed_quantity=item.billed_quantity,
        pending_quantity=(item.total_quantity - item.billed_quantity).quantize(Decimal("0.0001")),
        total_weight=item.total_weight,
        billed_weight=item.billed_weight,
        pending_weight=(item.total_weight - item.billed_weight).quantize(Decimal("0.0001")),
        status=item.status,
        version=item.version,
    )


def _fiscal_invoice_summary(invoice: FiscalInvoice) -> FiscalInvoiceSummary:
    active_items = [item for item in invoice.items if item.active]
    items = [
        FiscalInvoiceItemSummary(
            id=item.id,
            fiscal_invoice_id=item.fiscal_invoice_id,
            fiscal_item_id=item.fiscal_item_id,
            proposal_item_id=item.proposal_item_id,
            item_number=item.fiscal_item.proposal_item.item_number,
            quantity=item.quantity,
            weight=item.weight,
            active=item.active,
            cancelled_at=item.cancelled_at,
            cancel_reason=item.cancel_reason,
        )
        for item in active_items
    ]
    return FiscalInvoiceSummary(
        id=invoice.id,
        fiscal_record_id=invoice.fiscal_record_id,
        proposal_id=invoice.proposal_id,
        invoice_number=invoice.invoice_number,
        series=invoice.series,
        access_key=invoice.access_key,
        issued_at=invoice.issued_at,
        emission_type=invoice.emission_type,
        status=invoice.status,
        source=invoice.source,
        observation=invoice.observation,
        version=invoice.version,
        item_count=len(active_items),
        quantity=sum((item.quantity for item in active_items), Decimal("0")).quantize(Decimal("0.0001")),
        weight=sum((item.weight for item in active_items), Decimal("0")).quantize(Decimal("0.0001")),
        items=items,
    )


def _fiscal_actions(record: FiscalRecord):
    actions = []
    can_register = record.status_fiscal != "NOTA_FISCAL_EMITIDA" and any(item.status != "FATURADO" for item in record.items if item.active)
    actions.append({"id": "REGISTER_FISCAL_INVOICE", "label": "Registrar emissao fiscal", "enabled": can_register, "reason": None if can_register else "Sem saldo fiscal pendente"})
    actions.append({"id": "VIEW_FISCAL_DETAIL", "label": "Ver detalhes", "enabled": True})
    if record.status_fiscal == "NOTA_FISCAL_EMITIDA" and record.fiscal_situation != "NF_RETIRADA_CLIENTE":
        actions.append({"id": "MARK_INVOICE_WITHDRAWN", "label": "Marcar NF retirada", "enabled": True})
    return actions


async def _record_fiscal_event(
    session: AsyncSession,
    record: FiscalRecord,
    event_type: str,
    actor: User,
    *,
    fiscal_item: FiscalItem | None = None,
    fiscal_invoice: FiscalInvoice | None = None,
    request_id: str | None,
    from_status: str | None = None,
    to_status: str | None = None,
    metadata: dict | None = None,
) -> None:
    session.add(
        FiscalEvent(
            fiscal_record_id=record.id,
            proposal_id=record.proposal_id,
            fiscal_item_id=fiscal_item.id if fiscal_item is not None else None,
            fiscal_invoice_id=fiscal_invoice.id if fiscal_invoice is not None else None,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            actor_user_id=actor.id,
            request_id=request_id,
            metadata_=metadata or None,
        )
    )
    await auth_repository.create_security_event(session, event_type, actor_user_id=actor.id, request_id=request_id, details={"fiscal_record_id": record.id, "proposal_id": record.proposal_id})


async def _get_expedition_proposal(session: AsyncSession, proposal_id: int) -> Proposal:
    proposal = (
        (await session.execute(
            select(Proposal)
            .options(
                selectinload(Proposal.items),
                selectinload(Proposal.expedition_items).selectinload(ExpeditionItem.proposal_item),
            )
            .where(Proposal.id == proposal_id)
        ))
        .scalars()
        .unique()
        .first()
    )
    if proposal is None:
        raise ApiError(error_codes.PROPOSAL_NOT_FOUND, "Proposta nao encontrada.", status_code=404)
    return proposal


async def _sync_expedition_from_available_items(session: AsyncSession) -> None:
    proposals = (
        (await session.execute(
            select(Proposal)
            .options(
                selectinload(Proposal.items),
                selectinload(Proposal.expedition_items).selectinload(ExpeditionItem.proposal_item),
            )
            .where(Proposal.active.is_(True))
            .where(Proposal.is_cancelled.is_(False))
        ))
        .scalars()
        .unique()
        .all()
    )
    for proposal in proposals:
        await _ensure_expedition_items_for_proposal(session, proposal)
    await session.flush()


async def _ensure_expedition_items_for_proposal(session: AsyncSession, proposal: Proposal) -> None:
    existing = {int(item.proposal_item_id): item for item in proposal.expedition_items}
    changed = False
    for item in _active_items(proposal):
        available, origin = await _expedition_available_source(session, item)
        exp_item = existing.get(int(item.id))
        if available <= Decimal("0"):
            continue
        if exp_item is None:
            exp_item = ExpeditionItem(
                proposal_id=proposal.id,
                proposal_item_id=item.id,
                available_quantity=available,
                origin=origin,
                status="EM_SEPARACAO",
                created_by=proposal.updated_by,
                updated_by=proposal.updated_by,
            )
            exp_item.proposal = proposal
            exp_item.proposal_item = item
            session.add(exp_item)
            changed = True
            continue
        minimum_available = exp_item.delivered_quantity + exp_item.remanaged_quantity
        normalized_available = max(available, minimum_available).quantize(Decimal("0.0001"))
        if exp_item.available_quantity != normalized_available or exp_item.origin != origin:
            exp_item.available_quantity = normalized_available
            exp_item.origin = origin
            exp_item.updated_at = datetime.now(UTC)
            changed = True
    if changed:
        await session.flush()


async def _expedition_available_source(session: AsyncSession, item: ProposalItem) -> tuple[Decimal, str]:
    if not item.active or item.delivered or not item.flow_defined or not item.produced:
        return Decimal("0"), "PRODUCAO"
    if item.requires_galvanization == "SIM":
        returned = Decimal(str((await session.execute(
            select(func.coalesce(func.sum(GalvanizationLoadItem.returned_quantity), 0))
            .join(GalvanizationLoad, GalvanizationLoad.id == GalvanizationLoadItem.load_id)
            .where(GalvanizationLoadItem.proposal_item_id == item.id)
            .where(GalvanizationLoadItem.active.is_(True))
            .where(GalvanizationLoad.status != "CANCELADA")
        )).scalar_one() or "0")).quantize(Decimal("0.0001"))
        return returned, "GALVANIZACAO"
    if item.requires_galvanization == "NAO":
        return item.quantity.quantize(Decimal("0.0001")), "PRODUCAO"
    return Decimal("0"), "PRODUCAO"


def _active_expedition_items(proposal: Proposal) -> list[ExpeditionItem]:
    return [
        item for item in proposal.expedition_items
        if item.active and item.status != "ENTREGUE" and item.available_quantity > item.delivered_quantity + item.remanaged_quantity
    ]


def _all_expedition_items(proposal: Proposal) -> list[ExpeditionItem]:
    return [item for item in proposal.expedition_items if item.active]


def _expedition_sort_key(proposal: Proposal) -> int:
    status = proposal.shipping_status or proposal.current_status or "EM_SEPARACAO"
    order = {
        "EM_SEPARACAO": 0,
        "AGUARDANDO_SEPARACAO_PARCIAL": 0,
        "SEPARACAO_INICIADA": 1,
        "SEPARADO": 2,
        "ENTREGUE_PARCIAL": 3,
    }
    return order.get(status, 99)


def _expedition_summary(proposal: Proposal) -> ExpeditionProposalSummary:
    items = _all_expedition_items(proposal)
    active_items = [item for item in items if item.available_quantity > item.delivered_quantity + item.remanaged_quantity]
    available = sum((item.available_quantity for item in active_items), Decimal("0")).quantize(Decimal("0.0001"))
    separated = sum((item.separated_quantity for item in active_items), Decimal("0")).quantize(Decimal("0.0001"))
    delivered = sum((item.delivered_quantity for item in items), Decimal("0")).quantize(Decimal("0.0001"))
    pending = sum(((item.available_quantity - item.delivered_quantity - item.remanaged_quantity) for item in active_items), Decimal("0")).quantize(Decimal("0.0001"))
    return ExpeditionProposalSummary(
        id=proposal.id,
        proposal_number=proposal.proposal_number,
        customer_name=proposal.customer_name,
        project_name=proposal.project_name,
        lot=proposal.lot,
        shipping_status=proposal.shipping_status or proposal.current_status,
        general_status=proposal.general_status,
        version=proposal.version,
        item_count=len(active_items),
        available_quantity=available,
        separated_quantity=separated,
        delivered_quantity=delivered,
        pending_quantity=pending,
        origins=sorted({item.origin for item in active_items}),
        actions=_expedition_actions(proposal),
    )


def _expedition_detail(proposal: Proposal) -> ExpeditionProposalDetail:
    summary = _expedition_summary(proposal).model_dump()
    items = [_expedition_item_summary(item) for item in sorted(_all_expedition_items(proposal), key=lambda row: (row.proposal_item.item_number, row.id))]
    return ExpeditionProposalDetail(**summary, items=items)


def _expedition_item_summary(item: ExpeditionItem) -> ExpeditionItemSummary:
    pending = (item.available_quantity - item.delivered_quantity - item.remanaged_quantity).quantize(Decimal("0.0001"))
    return ExpeditionItemSummary(
        id=item.id,
        proposal_id=item.proposal_id,
        proposal_item_id=item.proposal_item_id,
        item_number=item.proposal_item.item_number,
        product_code=item.proposal_item.product_code,
        description=item.proposal_item.description,
        available_quantity=item.available_quantity,
        separated_quantity=item.separated_quantity,
        delivered_quantity=item.delivered_quantity,
        remanaged_quantity=item.remanaged_quantity,
        pending_quantity=max(Decimal("0"), pending),
        unit_weight=item.proposal_item.unit_weight,
        total_weight=(item.available_quantity * (item.proposal_item.unit_weight or Decimal("0"))).quantize(Decimal("0.0001")),
        origin=item.origin,
        status=item.status,
        version=item.version,
    )


def _selected_expedition_items(proposal: Proposal, payload_items, *, only_separated: bool = False) -> list[tuple[ExpeditionItem, Decimal]]:
    candidates = _active_expedition_items(proposal)
    if only_separated:
        candidates = [item for item in candidates if item.separated_quantity > item.delivered_quantity]
    by_exp = {int(item.id): item for item in candidates}
    by_proposal_item = {int(item.proposal_item_id): item for item in candidates}
    if not payload_items:
        if not candidates:
            raise ApiError(error_codes.EXPEDITION_ITEM_NOT_AVAILABLE, "Selecione pelo menos um item disponivel para Expedicao.", status_code=409)
        if only_separated:
            return [(item, (item.separated_quantity - item.delivered_quantity).quantize(Decimal("0.0001"))) for item in candidates]
        return [(item, (item.available_quantity - item.separated_quantity - item.remanaged_quantity).quantize(Decimal("0.0001"))) for item in candidates]
    selected: list[tuple[ExpeditionItem, Decimal]] = []
    seen: set[int] = set()
    for row in payload_items:
        item = by_exp.get(int(row.expedition_item_id or 0)) if row.expedition_item_id is not None else by_proposal_item.get(int(row.proposal_item_id or 0))
        if item is None:
            raise ApiError(error_codes.EXPEDITION_ITEM_NOT_AVAILABLE, "Item nao pertence a fila disponivel da Expedicao.", status_code=409)
        if int(item.id) in seen:
            raise ApiError(error_codes.EXPEDITION_ITEM_NOT_AVAILABLE, "Item duplicado na operacao de Expedicao.", status_code=409)
        seen.add(int(item.id))
        if row.version is not None:
            _ensure_version(item.version, row.version)
        default_qty = (item.separated_quantity - item.delivered_quantity) if only_separated else (item.available_quantity - item.separated_quantity - item.remanaged_quantity)
        selected.append((item, (row.quantity or default_qty).quantize(Decimal("0.0001"))))
    return selected


def _recalculate_expedition_proposal_state(proposal: Proposal, actor: User) -> None:
    items = _all_expedition_items(proposal)
    relevant = [item for item in items if item.available_quantity > Decimal("0")]
    if not relevant:
        return
    remaining = [item for item in relevant if item.delivered_quantity + item.remanaged_quantity < item.available_quantity]
    separated_open = [item for item in remaining if item.separated_quantity > item.delivered_quantity]
    any_delivered = any(item.delivered_quantity > Decimal("0") for item in relevant)
    any_separated = any(item.separated_quantity > Decimal("0") for item in relevant)
    all_proposal_items_delivered = all(item.delivered for item in _active_items(proposal))
    if not remaining and all_proposal_items_delivered and not proposal.has_production_pending:
        proposal.current_area = "FINALIZADO"
        proposal.current_status = "ENTREGUE"
        proposal.general_status = "ENTREGUE"
        proposal.shipping_status = "ENTREGUE"
        proposal.is_completed = True
        proposal.flow_situation = "NORMAL"
    elif any_delivered:
        proposal.current_area = "EXPEDICAO"
        proposal.current_status = "ENTREGUE_PARCIAL"
        proposal.general_status = "EM_EXPEDICAO"
        proposal.shipping_status = "ENTREGUE_PARCIAL"
        proposal.is_completed = False
        proposal.flow_situation = "PARCIAL_COM_PENDENCIA"
    elif remaining and len(separated_open) == len(remaining):
        proposal.current_area = "EXPEDICAO"
        proposal.current_status = "SEPARADO"
        proposal.general_status = "EM_EXPEDICAO"
        proposal.shipping_status = "SEPARADO"
        proposal.is_completed = False
    elif any_separated:
        proposal.current_area = "EXPEDICAO"
        proposal.current_status = "SEPARACAO_INICIADA"
        proposal.general_status = "EM_EXPEDICAO"
        proposal.shipping_status = "SEPARACAO_INICIADA"
        proposal.is_completed = False
    else:
        proposal.current_area = "EXPEDICAO"
        proposal.current_status = "EM_SEPARACAO"
        proposal.general_status = "EM_EXPEDICAO"
        proposal.shipping_status = "EM_SEPARACAO"
        proposal.is_completed = False
    _touch(proposal, actor)


def _expedition_actions(proposal: Proposal):
    items = _active_expedition_items(proposal)
    has_available = any(item.available_quantity > item.separated_quantity + item.remanaged_quantity for item in items)
    has_separated = any(item.separated_quantity > item.delivered_quantity for item in items)
    status = proposal.shipping_status or proposal.current_status or "EM_SEPARACAO"
    actions = []
    if status in {"EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL"}:
        actions.append({"id": "START_SEPARATION", "label": "Iniciar separacao", "enabled": bool(items)})
    actions.append({"id": "SEPARATE_ITEMS", "label": "Registrar separacao", "enabled": has_available})
    actions.append({"id": "REGISTER_DELIVERY", "label": "Registrar entrega", "enabled": has_separated, "reason": None if has_separated else "Separe itens antes da entrega"})
    actions.append({"id": "REMANAGE_MATERIAL", "label": "Remanejar material", "enabled": bool(items)})
    return actions


async def _record_expedition_event(
    session: AsyncSession,
    proposal: Proposal,
    event_type: str,
    actor: User,
    *,
    expedition_item: ExpeditionItem | None = None,
    request_id: str | None,
    from_status: str | None = None,
    to_status: str | None = None,
    metadata: dict | None = None,
) -> None:
    session.add(
        ExpeditionEvent(
            proposal_id=proposal.id,
            proposal_item_id=expedition_item.proposal_item_id if expedition_item is not None else None,
            expedition_item_id=expedition_item.id if expedition_item is not None else None,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            actor_user_id=actor.id,
            request_id=request_id,
            metadata_=metadata or None,
        )
    )
    await auth_repository.create_security_event(session, event_type, actor_user_id=actor.id, request_id=request_id, details={"proposal_id": proposal.id, "expedition_item_id": expedition_item.id if expedition_item is not None else None})


def _filtered_select(stmt: Select, **filters) -> Select:
    if filters["proposal_number"]:
        stmt = stmt.where(Proposal.proposal_number.ilike(f"%{filters['proposal_number']}%"))
    if filters["customer"]:
        stmt = stmt.where(Proposal.customer_name.ilike(f"%{filters['customer']}%"))
    if filters["project"]:
        value = f"%{filters['project']}%"
        stmt = stmt.where(or_(Proposal.project_name.ilike(value), Proposal.lot.ilike(value)))
    if filters["current_area"]:
        stmt = stmt.where(Proposal.current_area == filters["current_area"])
    if filters["current_status"]:
        stmt = stmt.where(Proposal.current_status == filters["current_status"])
    if filters["is_partial"] is not None:
        stmt = stmt.where(Proposal.is_partial.is_(filters["is_partial"]))
    if filters["is_cancelled"] is not None:
        stmt = stmt.where(Proposal.is_cancelled.is_(filters["is_cancelled"]))
    if filters["is_completed"] is not None:
        stmt = stmt.where(Proposal.is_completed.is_(filters["is_completed"]))
    if filters["date_from"] is not None:
        stmt = stmt.where(Proposal.proposal_date >= filters["date_from"])
    if filters["date_to"] is not None:
        stmt = stmt.where(Proposal.proposal_date <= filters["date_to"])
    if filters["updated_after"] is not None:
        stmt = stmt.where(Proposal.legacy_updated_at >= filters["updated_after"])
    return stmt


async def get_proposal(session: AsyncSession, proposal_id: int) -> Proposal:
    proposal = (await session.execute(select(Proposal).options(selectinload(Proposal.items)).where(Proposal.id == proposal_id))).scalars().first()
    if proposal is None:
        raise ApiError(error_codes.PROPOSAL_NOT_FOUND, "Proposta nao encontrada.", status_code=404)
    return proposal


async def list_proposal_history(
    session: AsyncSession,
    *,
    proposal_id: int | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[ProposalHistoryItem]:
    if proposal_id is not None:
        await get_proposal(session, proposal_id)

    proposal_events = (
        await session.execute(
            select(ProposalEvent).where(ProposalEvent.proposal_id == proposal_id if proposal_id is not None else True)
        )
    ).scalars().all()
    expedition_events = (
        await session.execute(
            select(ExpeditionEvent).where(ExpeditionEvent.proposal_id == proposal_id if proposal_id is not None else True)
        )
    ).scalars().all()
    galvanization_events = (
        await session.execute(
            select(GalvanizationLoadEvent).where(GalvanizationLoadEvent.proposal_id == proposal_id if proposal_id is not None else GalvanizationLoadEvent.proposal_id.is_not(None))
        )
    ).scalars().all()
    fiscal_stmt = select(FiscalEvent).join(FiscalRecord, FiscalRecord.id == FiscalEvent.fiscal_record_id)
    if proposal_id is not None:
        fiscal_stmt = fiscal_stmt.where(FiscalRecord.proposal_id == proposal_id)
    fiscal_events = (await session.execute(fiscal_stmt)).scalars().all()

    proposal_ids = {event.proposal_id for event in proposal_events}
    proposal_ids.update(event.proposal_id for event in expedition_events)
    proposal_ids.update(event.proposal_id for event in galvanization_events if event.proposal_id is not None)
    fiscal_record_ids = {event.fiscal_record_id for event in fiscal_events}
    fiscal_record_proposals: dict[int, int] = {}
    if fiscal_record_ids:
        records = (
            await session.execute(select(FiscalRecord).where(FiscalRecord.id.in_(fiscal_record_ids)))
        ).scalars().all()
        fiscal_record_proposals = {record.id: record.proposal_id for record in records}
        proposal_ids.update(record.proposal_id for record in records)

    proposals_by_id = {}
    if proposal_ids:
        proposal_rows = (await session.execute(select(Proposal).where(Proposal.id.in_(proposal_ids)))).scalars().all()
        proposals_by_id = {row.id: row for row in proposal_rows}

    actor_ids = {event.actor_user_id for event in proposal_events if event.actor_user_id is not None}
    actor_ids.update(event.actor_user_id for event in expedition_events if event.actor_user_id is not None)
    actor_ids.update(event.actor_user_id for event in galvanization_events if event.actor_user_id is not None)
    actor_ids.update(event.actor_user_id for event in fiscal_events if event.actor_user_id is not None)
    users_by_id = {}
    if actor_ids:
        users = (await session.execute(select(User).where(User.id.in_(actor_ids)))).scalars().all()
        users_by_id = {row.id: row for row in users}

    rows: list[ProposalHistoryItem] = []
    for event in proposal_events:
        rows.append(_proposal_history_item("proposal", event, event.proposal_id, proposals_by_id, users_by_id))
    for event in expedition_events:
        rows.append(_proposal_history_item("expedition", event, event.proposal_id, proposals_by_id, users_by_id, area="EXPEDICAO"))
    for event in galvanization_events:
        if event.proposal_id is not None:
            rows.append(_proposal_history_item("galvanization", event, event.proposal_id, proposals_by_id, users_by_id, area="GALVANIZACAO"))
    for event in fiscal_events:
        event_proposal_id = fiscal_record_proposals.get(event.fiscal_record_id)
        rows.append(_proposal_history_item("fiscal", event, event_proposal_id, proposals_by_id, users_by_id, area="FISCAL"))

    rows.sort(key=lambda item: (item.created_at, item.source, item.id), reverse=True)
    return rows[offset:offset + limit]


def _proposal_history_item(
    source: str,
    event,
    proposal_id: int | None,
    proposals_by_id: dict[int, Proposal],
    users_by_id: dict[int, User],
    *,
    area: str | None = None,
) -> ProposalHistoryItem:
    metadata = event.metadata_ if isinstance(event.metadata_, dict) else {}
    proposal = proposals_by_id.get(int(proposal_id or 0))
    actor = users_by_id.get(int(event.actor_user_id or 0))
    return ProposalHistoryItem(
        id=int(event.id),
        source=source,
        proposal_id=proposal_id,
        proposal_number=proposal.proposal_number if proposal else None,
        area=area or getattr(event, "to_area", None) or getattr(event, "from_area", None),
        from_status=getattr(event, "from_status", None),
        to_status=getattr(event, "to_status", None),
        event_type=event.event_type,
        actor_user_id=event.actor_user_id,
        actor_name=actor.display_name if actor else None,
        observation=_history_observation(metadata),
        request_id=event.request_id,
        created_at=event.created_at,
    )


def _history_observation(metadata: dict) -> str | None:
    for key in ("observation", "reason", "invoice_number", "load_id", "item_number", "changed"):
        value = metadata.get(key)
        if value not in (None, ""):
            return str(value)
    if metadata:
        return "; ".join(f"{key}: {value}" for key, value in metadata.items() if value not in (None, ""))
    return None


async def get_proposal_by_legacy_id(session: AsyncSession, legacy_id: int) -> Proposal:
    proposal = (await session.execute(select(Proposal).options(selectinload(Proposal.items)).where(Proposal.legacy_id == legacy_id))).scalars().first()
    if proposal is None:
        raise ApiError(error_codes.PROPOSAL_NOT_FOUND, "Proposta nao encontrada.", status_code=404)
    return proposal


def proposal_detail(row: Proposal) -> ProposalDetail:
    return ProposalDetail(
        **proposal_list_item(row),
        general_status=row.general_status,
        production_status=row.production_status,
        galvanization_status=row.galvanization_status,
        shipping_status=row.shipping_status,
        warehouse_status=row.warehouse_status,
        flow_situation=row.flow_situation,
        has_production_pending=row.has_production_pending,
        process_type=row.process_type,
        parent_legacy_id=row.parent_legacy_id,
        partial_number=row.partial_number,
        source=row.source,
        source_hash=row.source_hash,
        legacy_created_at=row.legacy_created_at,
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
        items=[item_summary(item) for item in sorted(row.items, key=lambda item: (item.item_number, item.id))],
    )


async def create_proposal(session: AsyncSession, payload: ProposalCreate, actor: User, *, request_id: str | None) -> ProposalDetail:
    current_area, current_status = ProposalStateMachine.initial_state()
    warehouse_status = _normalize_warehouse_status(payload.warehouse_status)
    proposal = Proposal(
        proposal_number=payload.proposal_number,
        customer_name=payload.customer_name,
        project_name=payload.project_name,
        order_reference=payload.purchase_order,
        lot=payload.batch_reference,
        proposal_date=payload.proposal_date,
        deadline_date=payload.deadline_date,
        current_area=current_area,
        current_status=current_status,
        general_status=current_status,
        warehouse_status=warehouse_status,
        is_partial=False,
        is_cancelled=False,
        is_completed=False,
        source=payload.source,
        notes=payload.notes,
        created_by=actor.id,
        updated_by=actor.id,
    )
    try:
        session.add(proposal)
        await session.flush()
        for item_payload in payload.items:
            session.add(_new_item(proposal.id, item_payload, actor))
        await session.flush()
        await _record_event(session, proposal, "PROPOSAL_CREATED", actor, request_id=request_id, metadata={"items": len(payload.items)})
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError(error_codes.PROPOSAL_NUMBER_ALREADY_EXISTS, "Ja existe proposta com este numero.", status_code=409) from exc
    return proposal_detail(await get_proposal(session, proposal.id))


async def update_proposal(session: AsyncSession, proposal_id: int, payload: ProposalUpdate, actor: User, *, request_id: str | None) -> ProposalDetail:
    proposal = await get_proposal(session, proposal_id)
    _ensure_version(proposal.version, payload.version)
    ProposalStateMachine.ensure_editable(proposal.current_area, proposal.current_status)
    changed: list[str] = []
    field_map = {
        "customer_name": "customer_name",
        "project_name": "project_name",
        "purchase_order": "order_reference",
        "batch_reference": "lot",
        "proposal_date": "proposal_date",
        "deadline_date": "deadline_date",
        "warehouse_status": "warehouse_status",
        "notes": "notes",
    }
    data = payload.model_dump(exclude_unset=True)
    data.pop("version", None)
    if "warehouse_status" in data:
        data["warehouse_status"] = _normalize_warehouse_status(data["warehouse_status"])
    for input_name, model_name in field_map.items():
        if input_name in data and getattr(proposal, model_name) != data[input_name]:
            setattr(proposal, model_name, data[input_name])
            changed.append(model_name)
    if changed:
        _touch(proposal, actor)
        await _record_event(session, proposal, "PROPOSAL_UPDATED", actor, request_id=request_id, metadata={"fields": changed, "version": proposal.version})
    await session.commit()
    return proposal_detail(await get_proposal(session, proposal.id))


async def cancel_proposal(session: AsyncSession, proposal_id: int, payload: ProposalCancelRequest, actor: User, *, request_id: str | None) -> ProposalDetail:
    proposal = await get_proposal(session, proposal_id)
    _ensure_version(proposal.version, payload.version)
    ProposalStateMachine.ensure_can_cancel(proposal.current_status)
    from_area, from_status = proposal.current_area, proposal.current_status
    to_area, to_status = ProposalStateMachine.cancel_state()
    proposal.current_area = to_area
    proposal.current_status = to_status
    proposal.general_status = to_status
    proposal.is_cancelled = True
    _touch(proposal, actor)
    await _record_event(session, proposal, "PROPOSAL_CANCELLED", actor, request_id=request_id, from_area=from_area, from_status=from_status, to_area=to_area, to_status=to_status, metadata={"reason": payload.reason, "version": proposal.version})
    await session.commit()
    return proposal_detail(await get_proposal(session, proposal.id))


async def change_proposal_status(session: AsyncSession, proposal_id: int, payload: ProposalStatusChangeRequest, actor: User, *, request_id: str | None) -> ProposalDetail:
    proposal = await get_proposal(session, proposal_id)
    _ensure_version(proposal.version, payload.version)
    from_area, from_status = proposal.current_area, proposal.current_status
    ProposalStateMachine.validate_transition(from_area, from_status, payload.to_area, payload.to_status)
    proposal.current_area = payload.to_area
    proposal.current_status = payload.to_status
    proposal.general_status = "EM_PRODUCAO" if payload.to_area == "PRODUCAO" else payload.to_status
    if payload.to_area == "PRODUCAO":
        proposal.production_status = "NAO_INICIADO"
        proposal.flow_situation = "NORMAL"
        proposal.has_production_pending = False
    _touch(proposal, actor)
    await _record_event(
        session,
        proposal,
        "PROPOSAL_STATUS_CHANGED",
        actor,
        request_id=request_id,
        from_area=from_area,
        from_status=from_status,
        to_area=payload.to_area,
        to_status=payload.to_status,
        metadata={"reason": payload.reason, "version": proposal.version},
    )
    await session.commit()
    return proposal_detail(await get_proposal(session, proposal.id))


async def administrative_correction(session: AsyncSession, proposal_id: int, payload: ProposalAdministrativeCorrectionRequest, actor: User, *, request_id: str | None) -> ProposalDetail:
    to_area = _administrative_area_value(payload.to_area)
    to_status = _status_value(payload.to_status)
    justification = payload.justification.strip()
    if to_area not in ADMINISTRATIVE_STATUS_OPTIONS:
        raise ApiError(error_codes.PROPOSAL_INVALID_STATE, "Nova area invalida.", status_code=409)
    if to_status not in ADMINISTRATIVE_STATUS_OPTIONS[to_area]:
        raise ApiError(error_codes.PROPOSAL_INVALID_STATE, "Status invalido para a nova area.", status_code=409)
    if not justification:
        raise ApiError(error_codes.VALIDATION_ERROR, "Informe a justificativa da correcao.", status_code=422)

    try:
        proposal = await get_proposal(session, proposal_id)
        from_area, from_status = _administrative_current_location(proposal)
        target_field = ADMINISTRATIVE_STATUS_FIELDS[to_area]
        old_target_status = _status_value(getattr(proposal, target_field))
        if from_area == to_area and old_target_status == to_status:
            raise ApiError(error_codes.PROPOSAL_INVALID_STATE, "A area e o status selecionados ja estao aplicados.", status_code=409)

        setattr(proposal, target_field, to_status)
        if to_area in ADMINISTRATIVE_FLOW_ORDER:
            for downstream_area in ADMINISTRATIVE_FLOW_ORDER[ADMINISTRATIVE_FLOW_ORDER.index(to_area) + 1:]:
                setattr(proposal, ADMINISTRATIVE_STATUS_FIELDS[downstream_area], None)
            proposal.current_area = to_area
            proposal.current_status = to_status

        preview = _administrative_state_preview(proposal)
        general_status = _administrative_general_status_for(to_area, to_status, preview)
        if general_status:
            proposal.general_status = general_status
            preview["general_status"] = general_status
        _apply_administrative_flow_state(proposal, preview)
        proposal.is_cancelled = proposal.general_status == "CANCELADA" or proposal.current_status == "CANCELADA"
        proposal.is_completed = proposal.general_status == "ENTREGUE" or proposal.current_status == "ENTREGUE" or proposal.current_area == "FINALIZADO"
        _touch(proposal, actor)

        history_note = (
            "CORRECAO ADMINISTRATIVA\n"
            f"Area anterior: {from_area.replace('_', ' ').title() if from_area else '-'}\n"
            f"Status anterior: {from_status or '-'}\n"
            f"Nova area: {to_area.replace('_', ' ').title()}\n"
            f"Novo status: {to_status}\n"
            f"Justificativa: {justification}"
        )
        details = {
            "proposal_id": proposal.id,
            "proposal_number": proposal.proposal_number,
            "from_area": from_area,
            "from_status": from_status,
            "to_area": to_area,
            "to_status": to_status,
            "justification": justification,
            "version": proposal.version,
        }
        session.add(
            ProposalEvent(
                proposal_id=proposal.id,
                event_type="PROPOSAL_ADMINISTRATIVE_CORRECTION",
                from_area=from_area,
                from_status=from_status,
                to_area=to_area,
                to_status=to_status,
                actor_user_id=actor.id,
                request_id=request_id,
                metadata_={**details, "observation": history_note},
            )
        )
        await auth_repository.create_security_event(
            session,
            "PROPOSAL_ADMINISTRATIVE_CORRECTION",
            actor_user_id=actor.id,
            request_id=request_id,
            details=details,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return proposal_detail(await get_proposal(session, proposal_id))


async def start_production(session: AsyncSession, proposal_id: int, payload: ProductionStartRequest, actor: User, *, request_id: str | None) -> ProductionProposalDetail:
    proposal = await get_proposal(session, proposal_id)
    _ensure_version(proposal.version, payload.version)
    _ensure_production_area(proposal)
    current = _production_status_value(proposal.production_status or proposal.current_status)
    if current not in PRODUCTION_STARTABLE_STATUSES:
        raise ApiError(error_codes.PRODUCTION_INVALID_STATE, "A producao nao pode ser iniciada no estado atual.", status_code=409)
    if not _active_items(proposal):
        raise ApiError(error_codes.PROPOSAL_REQUIRES_ITEMS, "A proposta precisa possuir itens ativos.", status_code=422)
    if not _internal_items(proposal):
        raise ApiError(error_codes.PRODUCTION_NO_INTERNAL_ITEMS, "Nao existem itens para producao interna.", status_code=409)
    from_status = current
    proposal.production_status = "INICIADO"
    proposal.current_area = "PRODUCAO"
    proposal.current_status = "INICIADO"
    proposal.general_status = "EM_PRODUCAO"
    _touch(proposal, actor)
    await _record_event(session, proposal, "PRODUCTION_STARTED", actor, request_id=request_id, from_area="PRODUCAO", from_status=from_status, to_area="PRODUCAO", to_status="INICIADO", metadata={"observation": payload.observation, "version": proposal.version})
    await session.commit()
    return _production_detail(await get_proposal(session, proposal.id))


async def update_production_item_flow(session: AsyncSession, proposal_id: int, payload: ProductionItemFlowRequest, actor: User, *, request_id: str | None) -> ProductionProposalDetail:
    proposal = await get_proposal(session, proposal_id)
    _ensure_version(proposal.version, payload.version)
    _ensure_production_area(proposal)
    items = _items_by_id(proposal)
    changed = 0
    for definition in payload.items:
        item = items.get(definition.item_id)
        if item is None:
            raise ApiError(error_codes.PRODUCTION_ITEM_NOT_AVAILABLE, "Item nao pertence a proposta oficial.", status_code=409)
        if definition.version is not None:
            _ensure_version(item.version, definition.version)
        previous = {
            "produce_internally": item.produce_internally,
            "requires_galvanization": item.requires_galvanization,
            "non_production_reason": item.non_production_reason or "",
            "notes": item.notes or "",
            "produced": item.produced,
        }
        produce = _flag_value(definition.produce_internally) if definition.produce_internally is not None else item.produce_internally
        galvanize = _flag_value(definition.requires_galvanization) if definition.requires_galvanization is not None else item.requires_galvanization
        reason = (definition.non_production_reason or "").strip()
        if produce == "NAO" and not reason:
            raise ApiError(error_codes.PROPOSAL_ITEM_INVALID, "Informe o motivo quando o item nao sera produzido internamente.", status_code=422)
        if produce != "NAO":
            reason = ""
        notes = definition.notes if definition.notes is not None else item.notes
        produced = item.produced
        if produce == "NAO":
            produced = True
        elif item.produce_internally == "NAO" and _production_status_value(proposal.production_status) != "FINALIZADO":
            produced = False
        if (item.produce_internally, item.requires_galvanization, item.non_production_reason or "", item.notes or "", item.produced) == (produce, galvanize, reason, notes or "", produced):
            continue
        item.produce_internally = produce
        item.requires_galvanization = galvanize
        item.non_production_reason = reason
        item.notes = notes
        item.produced = produced
        item.flow_defined = produce != "INDEFINIDO" and galvanize != "INDEFINIDO"
        _touch(item, actor)
        changed += 1
        await _record_event(session, proposal, "PRODUCTION_ITEM_FLOW_UPDATED", actor, item_id=item.id, request_id=request_id, metadata={"origin": payload.origin, "previous": previous, "current": {"produce_internally": produce, "requires_galvanization": galvanize, "non_production_reason": reason, "notes": notes or "", "produced": produced}, "item_version": item.version})
    if changed:
        _recalculate_production_state(proposal)
        _touch(proposal, actor)
        await _record_event(session, proposal, "PRODUCTION_ITEM_FLOW_BATCH_UPDATED", actor, request_id=request_id, metadata={"changed": changed, "version": proposal.version})
    await session.commit()
    return _production_detail(await get_proposal(session, proposal.id))


async def update_production_item_weights(session: AsyncSession, proposal_id: int, payload: ProductionItemWeightsRequest, actor: User, *, request_id: str | None) -> ProductionProposalDetail:
    proposal = await get_proposal(session, proposal_id)
    _ensure_version(proposal.version, payload.version)
    _ensure_production_area(proposal)
    items = _items_by_id(proposal)
    changed = 0
    for update in payload.items:
        item = items.get(update.item_id)
        if item is None:
            raise ApiError(error_codes.PRODUCTION_ITEM_NOT_AVAILABLE, "Item nao pertence a proposta oficial.", status_code=409)
        if update.version is not None:
            _ensure_version(item.version, update.version)
        weight = update.unit_weight.quantize(Decimal("0.0001"))
        if weight < 0:
            raise ApiError(error_codes.PRODUCTION_WEIGHT_INVALID, "O peso do item nao pode ser negativo.", status_code=422)
        if item.unit_weight == weight:
            continue
        previous = item.unit_weight
        item.unit_weight = weight
        item.total_weight = (item.quantity * weight).quantize(Decimal("0.0001"))
        _touch(item, actor)
        changed += 1
        await _record_event(session, proposal, "PRODUCTION_ITEM_WEIGHT_UPDATED", actor, item_id=item.id, request_id=request_id, metadata={"from": str(previous), "to": str(weight), "item_version": item.version})
    if changed:
        _touch(proposal, actor)
        await _record_event(session, proposal, "PRODUCTION_WEIGHTS_UPDATED", actor, request_id=request_id, metadata={"changed": changed, "version": proposal.version})
    await session.commit()
    return _production_detail(await get_proposal(session, proposal.id))


async def complete_production_items(session: AsyncSession, proposal_id: int, payload: ProductionCompleteItemsRequest, actor: User, *, request_id: str | None) -> ProductionProposalDetail:
    proposal = await get_proposal(session, proposal_id)
    _ensure_version(proposal.version, payload.version)
    _ensure_production_area(proposal)
    current = _production_status_value(proposal.production_status or proposal.current_status)
    if current not in PRODUCTION_COMPLETABLE_STATUSES:
        raise ApiError(error_codes.PRODUCTION_INVALID_STATE, "A producao precisa estar iniciada para concluir itens.", status_code=409)
    _ensure_flow_ready(proposal)
    pending = {item.id: item for item in _internal_items(proposal) if not item.produced}
    if not pending:
        _finalize_production_destination(proposal)
        _touch(proposal, actor)
        await _record_event(session, proposal, "PRODUCTION_COMPLETED", actor, request_id=request_id, metadata={"observation": payload.observation, "version": proposal.version})
        await session.commit()
        return _production_detail(await get_proposal(session, proposal.id))
    selected_ids = [int(item_id) for item_id in (payload.item_ids or list(pending))]
    selected = [pending[item_id] for item_id in selected_ids if item_id in pending]
    if not selected:
        raise ApiError(error_codes.PRODUCTION_ITEM_NOT_AVAILABLE, "Selecione pelo menos um item pendente de producao.", status_code=409)
    for item in selected:
        item.produced = True
        _touch(item, actor)
        await _record_event(session, proposal, "PRODUCTION_ITEM_COMPLETED", actor, item_id=item.id, request_id=request_id, metadata={"item_number": item.item_number, "item_version": item.version})
    remaining = [item for item in _internal_items(proposal) if not item.produced]
    from_status = current
    if remaining:
        proposal.production_status = "FINALIZADO_PARCIAL"
        proposal.current_area = "PRODUCAO"
        proposal.current_status = "FINALIZADO_PARCIAL"
        proposal.general_status = "EM_PRODUCAO"
        proposal.flow_situation = "PARCIAL_COM_PENDENCIA"
        proposal.has_production_pending = True
        event = "PRODUCTION_PARTIALLY_COMPLETED"
    else:
        _finalize_production_destination(proposal)
        event = "PRODUCTION_COMPLETED"
    _touch(proposal, actor)
    await _record_event(session, proposal, event, actor, request_id=request_id, from_area="PRODUCAO", from_status=from_status, to_area=proposal.current_area, to_status=proposal.current_status, metadata={"item_ids": selected_ids, "remaining": len(remaining), "observation": payload.observation, "version": proposal.version})
    await session.commit()
    return _production_detail(await get_proposal(session, proposal.id))


async def set_proposal_active(session: AsyncSession, proposal_id: int, active: bool, actor: User, *, request_id: str | None) -> ProposalDetail:
    proposal = await get_proposal(session, proposal_id)
    if proposal.active != active:
        proposal.active = active
        _touch(proposal, actor)
        await _record_event(session, proposal, "PROPOSAL_REACTIVATED" if active else "PROPOSAL_DEACTIVATED", actor, request_id=request_id, metadata={"version": proposal.version})
    await session.commit()
    return proposal_detail(await get_proposal(session, proposal.id))


async def create_item(session: AsyncSession, proposal_id: int, payload: ProposalItemCreate, actor: User, *, request_id: str | None) -> ProposalItemDetail:
    proposal = await get_proposal(session, proposal_id)
    ProposalStateMachine.ensure_editable(proposal.current_area, proposal.current_status)
    item = _new_item(proposal.id, payload, actor)
    try:
        session.add(item)
        _touch(proposal, actor)
        await session.flush()
        await _record_event(session, proposal, "PROPOSAL_ITEM_CREATED", actor, item_id=item.id, request_id=request_id, metadata={"item_number": item.item_number})
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError(error_codes.PROPOSAL_ITEM_INVALID, "Item invalido ou duplicado para a proposta.", status_code=409) from exc
    return await get_item(session, item.id)


async def update_item(session: AsyncSession, item_id: int, payload: ProposalItemUpdate, actor: User, *, request_id: str | None) -> ProposalItemDetail:
    item = await _get_item_model(session, item_id)
    proposal = await get_proposal(session, item.proposal_id)
    ProposalStateMachine.ensure_editable(proposal.current_area, proposal.current_status)
    _ensure_version(item.version, payload.version)
    changed: list[str] = []
    data = payload.model_dump(exclude_unset=True)
    data.pop("version", None)
    field_map = {"produce_internally": "produce_internally", "requires_galvanization": "requires_galvanization"}
    for key, value in list(data.items()):
        if key in field_map:
            value = _flag_value(value)
        if getattr(item, key) != value:
            setattr(item, key, value)
            changed.append(key)
    if changed:
        item.flow_defined = item.produce_internally != "INDEFINIDO" or item.requires_galvanization != "INDEFINIDO"
        _touch(item, actor)
        _touch(proposal, actor)
        await _record_event(session, proposal, "PROPOSAL_ITEM_UPDATED", actor, item_id=item.id, request_id=request_id, metadata={"fields": changed, "version": item.version})
    await session.commit()
    return await get_item(session, item.id)


async def delete_item(session: AsyncSession, item_id: int, actor: User, *, request_id: str | None) -> None:
    item = await _get_item_model(session, item_id)
    proposal = await get_proposal(session, item.proposal_id)
    ProposalStateMachine.ensure_editable(proposal.current_area, proposal.current_status)
    if item.active:
        item.active = False
        _touch(item, actor)
        _touch(proposal, actor)
        await _record_event(session, proposal, "PROPOSAL_ITEM_DELETED", actor, item_id=item.id, request_id=request_id, metadata={"item_number": item.item_number})
    await session.commit()


async def list_items_for_proposal(session: AsyncSession, proposal_id: int) -> list[ProposalItemSummary]:
    proposal = await get_proposal(session, proposal_id)
    return [item_summary(item) for item in sorted(proposal.items, key=lambda item: (item.item_number, item.id))]


def _production_list_item(row: Proposal) -> ProductionProposalListItem:
    return ProductionProposalListItem(
        **proposal_list_item(row),
        production_status=_production_status_value(row.production_status or row.current_status),
        general_status=row.general_status,
        progress=_production_progress(row),
        actions=_production_actions(row),
    )


def _production_detail(row: Proposal) -> ProductionProposalDetail:
    return ProductionProposalDetail(
        **proposal_detail(row).model_dump(),
        progress=_production_progress(row),
        actions=_production_actions(row),
    )


def _production_item_row(proposal: Proposal, item: ProposalItem, status_value: str) -> ProductionItemRow:
    return ProductionItemRow(
        proposal_id=proposal.id,
        proposal_number=proposal.proposal_number,
        customer_name=proposal.customer_name,
        project_name=proposal.project_name,
        lot=proposal.lot,
        proposal_version=proposal.version,
        proposal_status=status_value,
        item_id=item.id,
        item_number=item.item_number,
        product_code=item.product_code,
        description=item.description,
        quantity=item.quantity,
        unit=item.unit,
        unit_weight=item.unit_weight,
        total_weight=item.total_weight,
        produce_internally=item.produce_internally,
        requires_galvanization=item.requires_galvanization,
        flow_defined=item.flow_defined,
        produced=item.produced,
        notes=item.notes,
        version=item.version,
    )


def _galvanization_candidate_item(proposal: Proposal, item: ProposalItem, available: Decimal, situation: str, pending_away: Decimal) -> dict:
    unit_weight = item.unit_weight or Decimal("0")
    sent = pending_away.quantize(Decimal("0.0001"))
    return {
        "proposal_id": proposal.id,
        "proposal_number": proposal.proposal_number,
        "customer_name": proposal.customer_name,
        "project_name": proposal.project_name,
        "lot": proposal.lot,
        "item_id": item.id,
        "item_number": item.item_number,
        "product_code": item.product_code,
        "description": item.description,
        "quantity": item.quantity,
        "available_quantity": available.quantize(Decimal("0.0001")),
        "unit_weight": unit_weight,
        "available_weight": (available * unit_weight).quantize(Decimal("0.0001")),
        "sent_quantity": sent,
        "sent_weight": (sent * unit_weight).quantize(Decimal("0.0001")),
        "production_completed_at": proposal.updated_at,
        "priority": None,
        "notes": item.notes,
        "version": item.version,
        "situation": situation,
    }


def _galvanization_load_summary(load: GalvanizationLoad) -> GalvanizationLoadSummary:
    active = [item for item in load.items if item.active]
    pending = [item for item in active if item.returned_quantity < item.sent_quantity]
    returned = [item for item in active if item.returned_quantity >= item.sent_quantity]
    pending_weight = sum(((item.sent_weight or Decimal("0")) - (item.returned_weight or Decimal("0")) for item in pending), Decimal("0")).quantize(Decimal("0.0001"))
    proposal_ids = {int(item.proposal_id) for item in active}
    return GalvanizationLoadSummary(
        id=load.id,
        code=load.code,
        driver_name=load.driver_name,
        max_weight=load.max_weight,
        total_weight=(load.total_weight or Decimal("0")).quantize(Decimal("0.0001")),
        status=load.status,
        expected_return_date=load.expected_return_date,
        sent_at=load.sent_at,
        returned_at=load.returned_at,
        closed_at=load.closed_at,
        notes=load.notes,
        version=load.version,
        active=load.active,
        created_at=load.created_at,
        updated_at=load.updated_at,
        proposal_count=len(proposal_ids),
        item_count=len(active),
        returned_item_count=len(returned),
        pending_item_count=len(pending),
        pending_weight=pending_weight,
        overdue=_is_galvanization_load_overdue(load),
    )


def _galvanization_load_detail(load: GalvanizationLoad) -> GalvanizationLoadDetail:
    summary = _galvanization_load_summary(load).model_dump()
    items = [_galvanization_load_item_summary(item) for item in sorted([item for item in load.items if item.active], key=lambda row: (row.proposal.proposal_number, row.proposal_item.item_number, row.id))]
    proposals = []
    for proposal_id in sorted({item.proposal_id for item in load.items if item.active}):
        proposal_items = [item for item in load.items if item.active and item.proposal_id == proposal_id]
        proposal = proposal_items[0].proposal
        sent_weight = sum((item.sent_weight for item in proposal_items), Decimal("0")).quantize(Decimal("0.0001"))
        returned_weight = sum((item.returned_weight for item in proposal_items), Decimal("0")).quantize(Decimal("0.0001"))
        pending_weight = (sent_weight - returned_weight).quantize(Decimal("0.0001"))
        pending_count = sum(1 for item in proposal_items if item.returned_quantity < item.sent_quantity)
        proposals.append(
            {
                "proposal_id": proposal.id,
                "proposal_number": proposal.proposal_number,
                "customer_name": proposal.customer_name,
                "project_name": proposal.project_name,
                "sent_weight": sent_weight,
                "returned_weight": returned_weight,
                "pending_weight": pending_weight,
                "item_count": len(proposal_items),
                "pending_item_count": pending_count,
                "status": "RETORNADO" if pending_count == 0 else ("RETORNO_PARCIAL" if returned_weight > 0 else "AGUARDANDO_RETORNO"),
            }
        )
    return GalvanizationLoadDetail(**summary, items=items, proposals=proposals)


def _galvanization_load_item_summary(item: GalvanizationLoadItem):
    pending_qty = (item.sent_quantity - item.returned_quantity).quantize(Decimal("0.0001"))
    pending_weight = (item.sent_weight - item.returned_weight).quantize(Decimal("0.0001"))
    return {
        "id": item.id,
        "load_id": item.load_id,
        "proposal_id": item.proposal_id,
        "proposal_number": item.proposal.proposal_number,
        "customer_name": item.proposal.customer_name,
        "proposal_item_id": item.proposal_item_id,
        "item_number": item.proposal_item.item_number,
        "product_code": item.proposal_item.product_code,
        "description": item.proposal_item.description,
        "sent_quantity": item.sent_quantity,
        "returned_quantity": item.returned_quantity,
        "pending_quantity": pending_qty,
        "unit_weight": item.unit_weight,
        "sent_weight": item.sent_weight,
        "returned_weight": item.returned_weight,
        "pending_weight": pending_weight,
        "status": item.status,
        "version": item.version,
        "returned_at": item.returned_at,
        "active": item.active,
    }


async def _get_galvanization_load(session: AsyncSession, load_id: int) -> GalvanizationLoad:
    load = (
        (await session.execute(
            select(GalvanizationLoad)
            .options(
                selectinload(GalvanizationLoad.items).selectinload(GalvanizationLoadItem.proposal),
                selectinload(GalvanizationLoad.items).selectinload(GalvanizationLoadItem.proposal_item),
            )
            .where(GalvanizationLoad.id == load_id)
        ))
        .scalars()
        .unique()
        .first()
    )
    if load is None:
        raise ApiError(error_codes.GALVANIZATION_LOAD_NOT_FOUND, "Carga de galvanizacao nao encontrada.", status_code=404)
    return load


async def _replace_galvanization_load_items(session: AsyncSession, load: GalvanizationLoad, items_payload, actor: User, *, request_id: str | None) -> None:
    seen: set[int] = set()
    normalized = []
    for payload in items_payload:
        if payload.proposal_item_id in seen:
            raise ApiError(error_codes.GALVANIZATION_ITEM_DUPLICATED, "Item duplicado na carga.", status_code=409)
        seen.add(payload.proposal_item_id)
        item = await _get_item_model(session, payload.proposal_item_id)
        proposal = await get_proposal(session, item.proposal_id)
        if payload.version is not None:
            _ensure_version(item.version, payload.version)
        _ensure_item_eligible_for_galvanization(proposal, item)
        available = await _galvanization_available_quantity(session, item, exclude_load_id=load.id)
        sent_qty = (payload.sent_quantity or available).quantize(Decimal("0.0001"))
        if sent_qty <= Decimal("0") or sent_qty > available:
            raise ApiError(error_codes.GALVANIZATION_ITEM_NOT_ELIGIBLE, "Quantidade enviada excede o saldo disponivel para galvanizacao.", status_code=409)
        normalized.append((proposal, item, sent_qty, payload.notes))
    existing_items = (await session.execute(select(GalvanizationLoadItem).where(GalvanizationLoadItem.load_id == load.id))).scalars().all()
    for existing in existing_items:
        await session.delete(existing)
    await session.flush()
    load.total_weight = Decimal("0")
    for proposal, item, sent_qty, notes in normalized:
        sent_weight = (sent_qty * (item.unit_weight or Decimal("0"))).quantize(Decimal("0.0001"))
        load_item = GalvanizationLoadItem(
            load_id=load.id,
            proposal_id=proposal.id,
            proposal_item_id=item.id,
            sent_quantity=sent_qty,
            unit_weight=item.unit_weight,
            sent_weight=sent_weight,
            notes=notes,
            created_by=actor.id,
            updated_by=actor.id,
        )
        session.add(load_item)
        load.total_weight = (load.total_weight + sent_weight).quantize(Decimal("0.0001"))
        from_status = proposal.galvanization_status or proposal.current_status
        proposal.current_area = "GALVANIZACAO"
        proposal.current_status = "EM_CARGA"
        proposal.general_status = "EM_GALVANIZACAO"
        proposal.galvanization_status = "EM_CARGA"
        _touch(proposal, actor)
        await _record_event(session, proposal, "GALVANIZATION_ITEM_ADDED_TO_LOAD", actor, item_id=item.id, request_id=request_id, from_area="GALVANIZACAO", from_status=from_status, to_area="GALVANIZACAO", to_status="EM_CARGA", metadata={"load_id": load.id, "sent_quantity": str(sent_qty)})
    await session.flush()


def _ensure_item_eligible_for_galvanization(proposal: Proposal, item: ProposalItem) -> None:
    if proposal.is_cancelled or not proposal.active or not item.active:
        raise ApiError(error_codes.GALVANIZATION_ITEM_NOT_ELIGIBLE, "Item cancelado ou inativo nao pode entrar em carga.", status_code=409)
    if item.requires_galvanization != "SIM":
        raise ApiError(error_codes.GALVANIZATION_ITEM_NOT_ELIGIBLE, "Item nao precisa de galvanizacao.", status_code=409)
    if not item.flow_defined:
        raise ApiError(error_codes.GALVANIZATION_ITEM_NOT_ELIGIBLE, "Item sem fluxo definido nao pode entrar em carga.", status_code=409)
    if not item.produced:
        raise ApiError(error_codes.GALVANIZATION_ITEM_NOT_ELIGIBLE, "Item ainda nao foi produzido.", status_code=409)
    if item.galvanized:
        raise ApiError(error_codes.GALVANIZATION_ITEM_NOT_ELIGIBLE, "Item ja retornou integralmente da galvanizacao.", status_code=409)


def _eligible_galvanization_items(proposal: Proposal) -> list[ProposalItem]:
    return [
        item for item in _active_items(proposal)
        if item.produced and item.requires_galvanization == "SIM" and item.flow_defined and not item.galvanized
    ]


async def _galvanization_available_quantity(session: AsyncSession, item: ProposalItem, *, exclude_load_id: int | None = None) -> Decimal:
    stmt = (
        select(func.coalesce(func.sum(GalvanizationLoadItem.sent_quantity), 0))
        .join(GalvanizationLoad, GalvanizationLoad.id == GalvanizationLoadItem.load_id)
        .where(GalvanizationLoadItem.proposal_item_id == item.id)
        .where(GalvanizationLoadItem.active.is_(True))
        .where(GalvanizationLoad.status != "CANCELADA")
    )
    if exclude_load_id is not None:
        stmt = stmt.where(GalvanizationLoadItem.load_id != exclude_load_id)
    sent = Decimal(str((await session.execute(stmt)).scalar_one() or "0"))
    return max(Decimal("0"), (item.quantity - sent)).quantize(Decimal("0.0001"))


async def _galvanization_pending_quantity(session: AsyncSession, item: ProposalItem) -> Decimal:
    """Quantidade ainda fora (enviada e nao retornada) em cargas ativas nao canceladas."""
    stmt = (
        select(func.coalesce(func.sum(GalvanizationLoadItem.sent_quantity - GalvanizationLoadItem.returned_quantity), 0))
        .join(GalvanizationLoad, GalvanizationLoad.id == GalvanizationLoadItem.load_id)
        .where(GalvanizationLoadItem.proposal_item_id == item.id)
        .where(GalvanizationLoadItem.active.is_(True))
        .where(GalvanizationLoad.status != "CANCELADA")
    )
    pending = Decimal(str((await session.execute(stmt)).scalar_one() or "0"))
    return max(Decimal("0"), pending).quantize(Decimal("0.0001"))


def _ensure_load_editable(load: GalvanizationLoad) -> None:
    if load.status not in GALVANIZATION_LOAD_EDITABLE_STATUSES:
        raise ApiError(error_codes.GALVANIZATION_LOAD_INVALID_STATE, "Apenas cargas aguardando liberacao podem ser editadas.", status_code=409)


def _ensure_load_capacity(load: GalvanizationLoad) -> None:
    if load.max_weight is not None and load.total_weight > load.max_weight:
        raise ApiError(error_codes.GALVANIZATION_LOAD_INVALID_STATE, "O peso total da carga ultrapassa a capacidade informada.", status_code=409)


def _ensure_load_version(load: GalvanizationLoad, expected: int) -> None:
    if load.version != expected:
        raise ApiError(error_codes.GALVANIZATION_LOAD_VERSION_CONFLICT, "A carga foi alterada por outro usuario. Recarregue os dados.", status_code=409)


def _selected_return_items(load: GalvanizationLoad, payload: GalvanizationReturnRequest) -> list[tuple[GalvanizationLoadItem, Decimal]]:
    by_load_item = {int(item.id): item for item in load.items if item.active}
    by_proposal_item = {int(item.proposal_item_id): item for item in load.items if item.active}
    selected: dict[int, tuple[GalvanizationLoadItem, Decimal]] = {}
    if payload.proposal_ids:
        proposal_ids = {int(value) for value in payload.proposal_ids}
        for item in load.items:
            if item.active and int(item.proposal_id) in proposal_ids and item.returned_quantity < item.sent_quantity:
                selected[int(item.id)] = (item, item.sent_quantity - item.returned_quantity)
    for item_payload in payload.items or []:
        item = None
        if item_payload.load_item_id is not None:
            item = by_load_item.get(int(item_payload.load_item_id))
        elif item_payload.proposal_item_id is not None:
            item = by_proposal_item.get(int(item_payload.proposal_item_id))
        if item is None:
            raise ApiError(error_codes.GALVANIZATION_RETURN_INVALID, "Item nao pertence a carga selecionada.", status_code=409)
        pending = item.sent_quantity - item.returned_quantity
        selected[int(item.id)] = (item, (item_payload.quantity_returned or pending).quantize(Decimal("0.0001")))
    return list(selected.values())


async def _recalculate_galvanization_proposal_state(session: AsyncSession, proposal: Proposal, actor: User, *, request_id: str | None, load_id: int, observation: str | None) -> None:
    galv_items = [item for item in _active_items(proposal) if item.requires_galvanization == "SIM"]
    returned = []
    partial = False
    for item in galv_items:
        total_returned = Decimal(str((await session.execute(
            select(func.coalesce(func.sum(GalvanizationLoadItem.returned_quantity), 0))
            .join(GalvanizationLoad, GalvanizationLoad.id == GalvanizationLoadItem.load_id)
            .where(GalvanizationLoadItem.proposal_item_id == item.id)
            .where(GalvanizationLoadItem.active.is_(True))
            .where(GalvanizationLoad.status != "CANCELADA")
        )).scalar_one() or "0"))
        if total_returned >= item.quantity:
            item.galvanized = True
            _touch(item, actor)
            returned.append(item)
        elif total_returned > Decimal("0"):
            partial = True
    all_returned = bool(galv_items) and len(returned) == len(galv_items)
    any_returned = bool(returned) or partial
    from_status = proposal.galvanization_status or proposal.current_status
    if all_returned:
        proposal.current_area = "EXPEDICAO"
        proposal.current_status = "EM_SEPARACAO"
        proposal.general_status = "EM_EXPEDICAO"
        proposal.galvanization_status = "RETORNOU_GALVANIZACAO"
        proposal.shipping_status = proposal.shipping_status or "EM_SEPARACAO"
    elif any_returned:
        proposal.current_area = "GALVANIZACAO"
        proposal.current_status = "RETORNOU_PARCIAL"
        proposal.general_status = "EM_GALVANIZACAO"
        proposal.galvanization_status = "RETORNOU_PARCIAL"
        proposal.shipping_status = proposal.shipping_status or "AGUARDANDO_SEPARACAO_PARCIAL"
    else:
        proposal.current_area = "GALVANIZACAO"
        proposal.current_status = "ENVIADO_GALVANIZACAO"
        proposal.general_status = "EM_GALVANIZACAO"
        proposal.galvanization_status = "ENVIADO_GALVANIZACAO"
    _touch(proposal, actor)
    await _record_event(session, proposal, "GALVANIZATION_PROPOSAL_RETURN_RECALCULATED", actor, request_id=request_id, from_area="GALVANIZACAO", from_status=from_status, to_area=proposal.current_area, to_status=proposal.current_status, metadata={"load_id": load_id, "observation": observation, "all_returned": all_returned})


def _recalculate_load_return_state(load: GalvanizationLoad, now: datetime) -> None:
    active = [item for item in load.items if item.active]
    if active and all(item.returned_quantity >= item.sent_quantity for item in active):
        load.status = "RETORNADA_GALVANIZACAO"
        load.returned_at = now
    elif any(item.returned_quantity > Decimal("0") for item in active):
        load.status = "RETORNO_PARCIAL"


def _is_galvanization_load_overdue(load: GalvanizationLoad) -> bool:
    return bool(load.expected_return_date and load.status in {"LIBERADA_PARA_ENVIO", "RETORNO_PARCIAL"} and load.expected_return_date < datetime.now(UTC).date())


def _galvanization_load_search_text(load: GalvanizationLoad) -> str:
    values = [load.code, load.driver_name, load.status, str(load.id)]
    for item in load.items:
        values.extend([item.proposal.proposal_number, item.proposal.customer_name, item.proposal_item.description])
    return " ".join(str(value or "") for value in values).lower()


async def get_item(session: AsyncSession, item_id: int) -> ProposalItemDetail:
    item = await _get_item_model(session, item_id)
    return ProposalItemDetail(**item_summary(item).model_dump(), proposal_id=item.proposal_id, legacy_current_process_id=item.legacy_current_process_id, delivered_at=item.delivered_at, legacy_updated_at=item.legacy_updated_at)


async def _get_item_model(session: AsyncSession, item_id: int) -> ProposalItem:
    item = await session.get(ProposalItem, item_id)
    if item is None:
        raise ApiError(error_codes.PROPOSAL_ITEM_NOT_FOUND, "Item da proposta nao encontrado.", status_code=404)
    return item


def _new_item(proposal_id: int, payload: ProposalItemCreate, actor: User) -> ProposalItem:
    produce = _flag_value(payload.produce_internally)
    galvanization = _flag_value(payload.requires_galvanization)
    return ProposalItem(
        proposal_id=proposal_id,
        item_number=payload.item_number,
        product_code=payload.product_code,
        description=payload.description,
        quantity=payload.quantity,
        unit=payload.unit,
        unit_weight=payload.unit_weight,
        total_weight=payload.total_weight,
        produce_internally=produce,
        non_production_reason=payload.non_production_reason,
        requires_galvanization=galvanization,
        flow_defined=produce != "INDEFINIDO" and galvanization != "INDEFINIDO",
        notes=payload.notes,
        created_by=actor.id,
        updated_by=actor.id,
        produced=produce == "NAO",
    )


def _flag_value(value: bool | None) -> str:
    if value is True:
        return "SIM"
    if value is False:
        return "NAO"
    return "INDEFINIDO"


def _ensure_version(current: int, expected: int) -> None:
    if current != expected:
        raise ApiError(error_codes.PROPOSAL_VERSION_CONFLICT, "A proposta ou item foi alterado por outro usuario. Recarregue os dados.", status_code=409)


def _ensure_production_area(proposal: Proposal) -> None:
    if proposal.is_cancelled:
        raise ApiError(error_codes.PROPOSAL_INVALID_STATE, "Proposta cancelada nao pode ser movimentada na Producao.", status_code=409)
    if proposal.current_area != "PRODUCAO":
        raise ApiError(error_codes.PRODUCTION_INVALID_STATE, "A proposta ainda nao esta na Producao oficial.", status_code=409)


def _production_status_value(status: str | None) -> str:
    value = (status or "").strip().upper()
    if value == "LIBERADO_PRODUCAO":
        return "NAO_INICIADO"
    return value or "NAO_INICIADO"


def _production_sort_key(proposal: Proposal) -> int:
    return PRODUCTION_SORT_STATUS.get(_production_status_value(proposal.production_status or proposal.current_status), 100)


def _active_items(proposal: Proposal) -> list[ProposalItem]:
    return [item for item in proposal.items if item.active]


def _internal_items(proposal: Proposal) -> list[ProposalItem]:
    return [item for item in _active_items(proposal) if item.produce_internally != "NAO"]


def _items_by_id(proposal: Proposal) -> dict[int, ProposalItem]:
    return {int(item.id): item for item in _active_items(proposal)}


def _undefined_flow_items(proposal: Proposal) -> list[ProposalItem]:
    return [
        item for item in _active_items(proposal)
        if item.produce_internally == "INDEFINIDO" or item.requires_galvanization == "INDEFINIDO"
    ]


def _production_progress(proposal: Proposal) -> ProductionProgress:
    items = _active_items(proposal)
    internal = _internal_items(proposal)
    produced_internal = [item for item in internal if item.produced]
    pending = [item for item in internal if not item.produced]
    undefined = _undefined_flow_items(proposal)
    missing_weight = [item for item in items if item.unit_weight == Decimal("0")]
    needs_galv = [item for item in items if item.requires_galvanization == "SIM"]
    no_galv = [item for item in items if item.requires_galvanization == "NAO"]
    total_weight = sum(((item.total_weight or Decimal("0")) for item in items), Decimal("0")).quantize(Decimal("0.0001"))
    produced_weight = sum(((item.total_weight or Decimal("0")) for item in items if item.produced), Decimal("0")).quantize(Decimal("0.0001"))
    pending_weight = sum(((item.total_weight or Decimal("0")) for item in pending), Decimal("0")).quantize(Decimal("0.0001"))
    status = _production_status_value(proposal.production_status or proposal.current_status)
    return ProductionProgress(
        total_items=len(items),
        internal_items=len(internal),
        produced_items=len(produced_internal),
        pending_items=len(pending),
        undefined_flow_items=len(undefined),
        missing_weight_items=len(missing_weight),
        needs_galvanization_items=len(needs_galv),
        no_galvanization_items=len(no_galv),
        total_weight=total_weight,
        produced_weight=produced_weight,
        pending_weight=pending_weight,
        next_destination=_next_destination(proposal),
        summary_status=status,
    )


def _proposal_has_partial_movement(proposal: Proposal) -> bool:
    statuses = {
        proposal.current_status,
        proposal.production_status,
        proposal.galvanization_status,
        proposal.shipping_status,
        proposal.warehouse_status,
        proposal.fiscal_record.status_fiscal if proposal.fiscal_record else None,
        proposal.flow_situation,
    }
    if any(status in PARTIAL_TRACKED_STATUSES for status in statuses if status):
        return True
    if proposal.has_production_pending or proposal.is_partial:
        return True
    active_items = _active_items(proposal)
    produced = [item for item in active_items if item.produced]
    if produced and len(produced) < len([item for item in active_items if item.produce_internally != "NAO"]):
        return True
    active_load_items = [item for item in proposal.galvanization_load_items if item.active]
    if any(item.returned_quantity > Decimal("0") and item.returned_quantity < item.sent_quantity for item in active_load_items):
        return True
    active_expedition_items = [item for item in proposal.expedition_items if item.active]
    if any(item.delivered_quantity > Decimal("0") and item.delivered_quantity + item.remanaged_quantity < item.available_quantity for item in active_expedition_items):
        return True
    if proposal.fiscal_record:
        active_fiscal_items = [item for item in proposal.fiscal_record.items if item.active]
        if any(item.billed_quantity > Decimal("0") and item.billed_quantity < item.total_quantity for item in active_fiscal_items):
            return True
        billed = [item for item in active_fiscal_items if item.billed_quantity > Decimal("0")]
        if billed and len(billed) < len(active_fiscal_items):
            return True
    return False


def _normalize_warehouse_status(value: str | None) -> str | None:
    status = str(value or "").strip().upper()
    if status in {"SIM", "AGUARDANDO_CONFIRMACAO", "NAO_DEFINIDO"}:
        return "AGUARDANDO_CONFIRMACAO" if status == "SIM" else (None if status == "NAO_DEFINIDO" else status)
    if status in {"NAO", "SEM_PARAFUSOS"}:
        return "SEM_PARAFUSOS"
    if status in WAREHOUSE_STATUSES:
        return status
    return None


def _warehouse_required_value(status: str | None) -> str:
    if status == "SEM_PARAFUSOS":
        return "NAO"
    if status in WAREHOUSE_STATUSES:
        return "SIM"
    return "NAO_DEFINIDO"


def _warehouse_sort_key(proposal: Proposal) -> int:
    order = {
        "AGUARDANDO_CONFIRMACAO": 0,
        "EM_SEPARACAO": 1,
        "SEPARADO": 2,
        "ALMOXARIFADO_ENTREGUE_PARCIAL": 3,
        "SEM_PARAFUSOS": 4,
        "ALMOXARIFADO_ENTREGUE": 5,
    }
    return order.get(proposal.warehouse_status or "", 99)


def _warehouse_proposal_summary(proposal: Proposal) -> WarehouseProposalSummary:
    active_items = _active_items(proposal)
    total_weight = sum((item.total_weight for item in active_items), Decimal("0")).quantize(Decimal("0.0001"))
    return WarehouseProposalSummary(
        id=proposal.id,
        proposal_number=proposal.proposal_number,
        customer_name=proposal.customer_name,
        project_name=proposal.project_name,
        lot=proposal.lot,
        current_area=proposal.current_area,
        current_status=proposal.current_status,
        warehouse_status=proposal.warehouse_status or "AGUARDANDO_CONFIRMACAO",
        warehouse_required=_warehouse_required_value(proposal.warehouse_status),
        general_status=proposal.general_status,
        shipping_status=proposal.shipping_status,
        total_items=len(active_items),
        total_weight=total_weight,
        updated_at=proposal.updated_at,
        version=proposal.version,
    )


def _partial_stage(proposal: Proposal) -> str:
    if proposal.production_status in {"FINALIZADO_PARCIAL", "ITEM_PENDENTE_FABRICACAO"} or proposal.has_production_pending:
        return "PRODUCAO"
    if proposal.galvanization_status in {"DISPONIVEL_PARCIAL", "RETORNOU_PARCIAL"}:
        return "GALVANIZACAO"
    if proposal.shipping_status in {"AGUARDANDO_SEPARACAO_PARCIAL", "ENTREGUE_PARCIAL"}:
        return "EXPEDICAO"
    if proposal.fiscal_record and proposal.fiscal_record.status_fiscal == "NOTA_FISCAL_PARCIAL":
        return "FISCAL"
    if proposal.warehouse_status == "ALMOXARIFADO_ENTREGUE_PARCIAL":
        return "ALMOXARIFADO"
    return proposal.current_area or "PARCIAIS"


def _partial_proposal_summary(proposal: Proposal) -> PartialProposalSummary:
    active_items = _active_items(proposal)
    internal_items = [item for item in active_items if item.produce_internally != "NAO"]
    produced_items = [item for item in active_items if item.produced]
    production_pending_items = [item for item in internal_items if not item.produced]
    galvanized_items = [item for item in active_items if item.galvanized]
    proposal_galvanization_pending_items = [
        item for item in active_items
        if item.requires_galvanization == "SIM" and item.produced and not item.galvanized
    ]
    active_load_items = [item for item in proposal.galvanization_load_items if item.active]
    load_galvanization_pending_items = [item for item in active_load_items if item.returned_quantity < item.sent_quantity]
    active_expedition_items = [item for item in proposal.expedition_items if item.active]
    delivered_items = [item for item in active_expedition_items if item.delivered_quantity > Decimal("0")]
    expedition_pending_items = [
        item for item in active_expedition_items
        if item.delivered_quantity + item.remanaged_quantity < item.available_quantity
    ]
    fiscal_status = proposal.fiscal_record.status_fiscal if proposal.fiscal_record else None
    fiscal_items = [
        item for item in (proposal.fiscal_record.items if proposal.fiscal_record else [])
        if item.active and fiscal_status in {"NOTA_FISCAL_PARCIAL", "NOTA_FISCAL_EMITIDA"}
    ]
    billed_items = [item for item in fiscal_items if item.billed_quantity > Decimal("0")]
    fiscal_pending_items = [item for item in fiscal_items if item.billed_quantity < item.total_quantity]
    total_weight = sum((item.total_weight for item in active_items), Decimal("0")).quantize(Decimal("0.0001"))
    produced_weight = sum((item.total_weight for item in produced_items), Decimal("0")).quantize(Decimal("0.0001"))
    production_pending_weight = sum((item.total_weight for item in production_pending_items), Decimal("0")).quantize(Decimal("0.0001"))
    galvanization_sent_weight = sum((item.sent_weight for item in active_load_items), Decimal("0")).quantize(Decimal("0.0001"))
    galvanization_returned_weight = sum((item.returned_weight for item in active_load_items), Decimal("0")).quantize(Decimal("0.0001"))
    load_galvanization_pending_weight = (galvanization_sent_weight - galvanization_returned_weight).quantize(Decimal("0.0001"))
    proposal_galvanization_pending_weight = sum((item.total_weight for item in proposal_galvanization_pending_items), Decimal("0")).quantize(Decimal("0.0001"))
    galvanization_pending_weight = max(load_galvanization_pending_weight, proposal_galvanization_pending_weight).quantize(Decimal("0.0001"))
    expedition_delivered_weight = sum((item.delivered_quantity * item.proposal_item.unit_weight for item in active_expedition_items), Decimal("0")).quantize(Decimal("0.0001"))
    expedition_pending_weight = sum(((item.available_quantity - item.delivered_quantity - item.remanaged_quantity) * item.proposal_item.unit_weight for item in expedition_pending_items), Decimal("0")).quantize(Decimal("0.0001"))
    fiscal_billed_weight = sum((item.billed_weight for item in fiscal_items), Decimal("0")).quantize(Decimal("0.0001"))
    fiscal_pending_weight = sum((item.total_weight - item.billed_weight for item in fiscal_pending_items), Decimal("0")).quantize(Decimal("0.0001"))
    return PartialProposalSummary(
        id=proposal.id,
        proposal_number=proposal.proposal_number,
        customer_name=proposal.customer_name,
        project_name=proposal.project_name,
        lot=proposal.lot,
        current_area=proposal.current_area,
        current_status=proposal.current_status,
        production_status=proposal.production_status,
        galvanization_status=proposal.galvanization_status,
        shipping_status=proposal.shipping_status,
        warehouse_status=proposal.warehouse_status,
        fiscal_status=proposal.fiscal_record.status_fiscal if proposal.fiscal_record else None,
        flow_situation=proposal.flow_situation,
        process_type=proposal.process_type,
        partial_number=proposal.partial_number,
        total_items=len(active_items),
        produced_items=len(produced_items),
        production_pending_items=len(production_pending_items),
        galvanized_items=len(galvanized_items),
        galvanization_pending_items=max(len(load_galvanization_pending_items), len(proposal_galvanization_pending_items)),
        delivered_items=len(delivered_items),
        expedition_pending_items=len(expedition_pending_items),
        billed_items=len(billed_items),
        fiscal_pending_items=len(fiscal_pending_items),
        total_weight=total_weight,
        produced_weight=produced_weight,
        production_pending_weight=production_pending_weight,
        galvanization_sent_weight=galvanization_sent_weight,
        galvanization_returned_weight=galvanization_returned_weight,
        galvanization_pending_weight=galvanization_pending_weight,
        expedition_delivered_weight=expedition_delivered_weight,
        expedition_pending_weight=expedition_pending_weight,
        fiscal_billed_weight=fiscal_billed_weight,
        fiscal_pending_weight=fiscal_pending_weight,
        partial_stage=_partial_stage(proposal),
        updated_at=proposal.updated_at,
        version=proposal.version,
    )


def _production_actions(proposal: Proposal):
    status = _production_status_value(proposal.production_status or proposal.current_status)
    progress = _production_progress(proposal)
    actions = []
    if status in PRODUCTION_STARTABLE_STATUSES:
        actions.append({"id": "START_PRODUCTION", "label": "Iniciar producao", "enabled": progress.internal_items > 0, "reason": None if progress.internal_items > 0 else "Sem itens de producao interna"})
    actions.append({"id": "DEFINE_ITEM_FLOW", "label": "Definir fluxo dos itens", "enabled": status != "FINALIZADO"})
    actions.append({"id": "UPDATE_ITEM_WEIGHTS", "label": "Informar pesos dos itens", "enabled": status != "FINALIZADO"})
    if status in PRODUCTION_COMPLETABLE_STATUSES:
        actions.append({"id": "COMPLETE_ITEMS", "label": "Registrar producao", "enabled": progress.undefined_flow_items == 0 and progress.pending_items > 0, "reason": "Fluxo de item pendente" if progress.undefined_flow_items else None})
    return actions


def _ensure_flow_ready(proposal: Proposal) -> None:
    undefined = _undefined_flow_items(proposal)
    if undefined:
        labels = [f"{item.item_number} - {item.description[:80]}" for item in undefined[:8]]
        suffix = f"; +{len(undefined) - 8} item(ns)" if len(undefined) > 8 else ""
        raise ApiError(error_codes.PRODUCTION_ITEM_FLOW_REQUIRED, "Existem itens sem definicao de fluxo: " + "; ".join(labels) + suffix, status_code=409)


def _recalculate_production_state(proposal: Proposal) -> None:
    status = _production_status_value(proposal.production_status or proposal.current_status)
    if status == "FINALIZADO":
        return
    internal = _internal_items(proposal)
    pending = [item for item in internal if not item.produced]
    produced = [item for item in internal if item.produced]
    if pending and produced:
        proposal.production_status = "FINALIZADO_PARCIAL"
        proposal.current_status = "FINALIZADO_PARCIAL"
        proposal.general_status = "EM_PRODUCAO"
        proposal.flow_situation = "PARCIAL_COM_PENDENCIA"
        proposal.has_production_pending = True
    elif not pending and internal:
        _finalize_production_destination(proposal)
    elif status in {"FINALIZADO_PARCIAL", "ITEM_PENDENTE_FABRICACAO"}:
        proposal.production_status = "INICIADO"
        proposal.current_status = "INICIADO"
        proposal.flow_situation = "NORMAL"
        proposal.has_production_pending = False


def _finalize_production_destination(proposal: Proposal) -> None:
    proposal.production_status = "FINALIZADO"
    proposal.has_production_pending = False
    proposal.flow_situation = "NORMAL"
    if any(item.requires_galvanization == "SIM" and item.produced for item in _active_items(proposal)):
        proposal.current_area = "GALVANIZACAO"
        proposal.current_status = "AGUARDANDO_ENVIO"
        proposal.general_status = "EM_GALVANIZACAO"
        proposal.galvanization_status = "AGUARDANDO_ENVIO"
        proposal.shipping_status = None
    else:
        proposal.current_area = "EXPEDICAO"
        proposal.current_status = "EM_SEPARACAO"
        proposal.general_status = "EM_EXPEDICAO"
        proposal.galvanization_status = None
        proposal.shipping_status = "EM_SEPARACAO"


def _next_destination(proposal: Proposal) -> str | None:
    if _production_status_value(proposal.production_status or proposal.current_status) != "FINALIZADO":
        return None
    if any(item.requires_galvanization == "SIM" and item.produced for item in _active_items(proposal)):
        return "GALVANIZACAO"
    return "EXPEDICAO"


def _touch(row, actor: User) -> None:
    row.version += 1
    row.updated_by = actor.id
    row.updated_at = datetime.now(UTC)


def _status_value(status: str | None) -> str:
    return str(status or "").strip().upper()


def _administrative_area_value(area: str | None) -> str:
    return str(area or "").strip().upper().replace(" ", "_")


def _administrative_current_location(proposal: Proposal) -> tuple[str | None, str | None]:
    if proposal.production_status in {"FINALIZADO_PARCIAL", "ITEM_PENDENTE_FABRICACAO"}:
        return "PRODUCAO", proposal.production_status
    for area, field in (
        ("EXPEDICAO", "shipping_status"),
        ("GALVANIZACAO", "galvanization_status"),
        ("PRODUCAO", "production_status"),
        ("CONTROLE_GERAL", "general_status"),
    ):
        status = _status_value(getattr(proposal, field))
        if not status:
            continue
        if area == "PRODUCAO" and status == "FINALIZADO":
            continue
        if area == "GALVANIZACAO" and status == "RETORNOU_GALVANIZACAO":
            continue
        if area == "EXPEDICAO" and status in {"ENTREGUE", "UNIFICADA_PRINCIPAL"}:
            continue
        return area, status
    return proposal.current_area, proposal.current_status


def _administrative_state_preview(proposal: Proposal) -> dict[str, str | None]:
    return {
        "general_status": proposal.general_status,
        "production_status": proposal.production_status,
        "galvanization_status": proposal.galvanization_status,
        "shipping_status": proposal.shipping_status,
        "warehouse_status": proposal.warehouse_status,
    }


def _administrative_general_status_for(area: str, status: str, process: dict[str, str | None]) -> str | None:
    if process.get("production_status") in {"FINALIZADO_PARCIAL", "ITEM_PENDENTE_FABRICACAO"}:
        return "EM_PRODUCAO"
    if area == "PRODUCAO" and status == "FINALIZADO":
        return "EM_GALVANIZACAO"
    if area == "PRODUCAO" and status in {"NAO_INICIADO", "ITEM_PENDENTE_FABRICACAO", "INICIADO", "PARADO", "FINALIZADO_PARCIAL"}:
        return "EM_PRODUCAO"
    if area == "GALVANIZACAO" and status == "RETORNOU_GALVANIZACAO":
        return "EM_EXPEDICAO"
    if area == "GALVANIZACAO" and status:
        return "EM_GALVANIZACAO"
    if area == "EXPEDICAO" and status in {"EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL", "SEPARACAO_INICIADA", "SEPARADO", "ENTREGUE_PARCIAL"}:
        return "EM_EXPEDICAO"
    if area == "EXPEDICAO" and status == "ENTREGUE":
        return "ENTREGUE"
    return None


def _apply_administrative_flow_state(proposal: Proposal, process: dict[str, str | None]) -> None:
    general_status = process.get("general_status") or ""
    production_status = process.get("production_status") or ""
    galvanization_status = process.get("galvanization_status") or ""
    shipping_status = process.get("shipping_status") or ""
    if general_status == "CANCELADA":
        proposal.flow_situation = "CANCELADA_FLUXO"
        proposal.has_production_pending = False
    elif shipping_status == "UNIFICADA_PRINCIPAL":
        proposal.flow_situation = "UNIFICADA_NA_PRINCIPAL"
        proposal.has_production_pending = False
    elif shipping_status == "ENTREGUE":
        proposal.flow_situation = "CONCLUIDA"
        proposal.has_production_pending = False
    elif production_status == "ITEM_PENDENTE_FABRICACAO":
        proposal.flow_situation = "PENDENTE_POR_REMANEJAMENTO"
        proposal.has_production_pending = True
    elif production_status == "FINALIZADO_PARCIAL":
        proposal.flow_situation = "PARCIAL_COM_PENDENCIA"
        proposal.has_production_pending = True
    elif galvanization_status in {"DISPONIVEL_PARCIAL", "RETORNOU_PARCIAL"} or shipping_status in {"AGUARDANDO_SEPARACAO_PARCIAL", "ENTREGUE_PARCIAL"}:
        proposal.flow_situation = "PARCIAL_EM_ANDAMENTO"
        proposal.has_production_pending = False
    else:
        proposal.flow_situation = "NORMAL"
        proposal.has_production_pending = False


async def _record_event(
    session: AsyncSession,
    proposal: Proposal,
    event_type: str,
    actor: User,
    *,
    item_id: int | None = None,
    request_id: str | None,
    from_area: str | None = None,
    from_status: str | None = None,
    to_area: str | None = None,
    to_status: str | None = None,
    metadata: dict | None = None,
) -> None:
    from api.app.modules.proposals.models import ProposalEvent

    session.add(
        ProposalEvent(
            proposal_id=proposal.id,
            item_id=item_id,
            event_type=event_type,
            from_area=from_area,
            from_status=from_status,
            to_area=to_area,
            to_status=to_status,
            actor_user_id=actor.id,
            request_id=request_id,
            metadata_=metadata or None,
        )
    )
    await auth_repository.create_security_event(session, event_type, actor_user_id=actor.id, request_id=request_id, details={"proposal_id": proposal.id, "item_id": item_id})


async def _record_load_event(
    session: AsyncSession,
    load: GalvanizationLoad,
    event_type: str,
    actor: User,
    *,
    load_item: GalvanizationLoadItem | None = None,
    request_id: str | None,
    from_status: str | None = None,
    to_status: str | None = None,
    metadata: dict | None = None,
) -> None:
    session.add(
        GalvanizationLoadEvent(
            load_id=load.id,
            load_item_id=load_item.id if load_item is not None else None,
            proposal_id=load_item.proposal_id if load_item is not None else None,
            proposal_item_id=load_item.proposal_item_id if load_item is not None else None,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            actor_user_id=actor.id,
            request_id=request_id,
            metadata_=metadata or None,
        )
    )
    await auth_repository.create_security_event(session, event_type, actor_user_id=actor.id, request_id=request_id, details={"load_id": load.id, "load_item_id": load_item.id if load_item is not None else None})


async def sync_batch(session: AsyncSession, batch: ProposalSyncBatch, actor: User, *, request_id: str | None) -> SyncSummary:
    errors = _validate_batch(batch)
    if errors:
        return SyncSummary(received=len(batch.proposals), rejected=len(errors), errors=errors, dry_run=batch.dry_run)
    if batch.dry_run:
        return await _simulate(session, batch)

    locked = bool((await session.execute(text("SELECT pg_try_advisory_xact_lock(:lock_id)").bindparams(lock_id=SYNC_LOCK_ID))).scalar_one())
    if not locked:
        raise ApiError(error_codes.SYNC_ALREADY_RUNNING, "Ja existe sincronizacao de propostas em andamento.", status_code=409)

    run = SyncRun(sync_type="proposals", status="RUNNING", source_identifier=batch.source_identifier, actor_user_id=actor.id, request_id=request_id)
    session.add(run)
    await session.flush()
    await auth_repository.create_security_event(session, "PROPOSAL_SYNC_STARTED", actor_user_id=actor.id, request_id=request_id, details={"sync_run_id": run.id, "received": len(batch.proposals)})

    summary = SyncSummary(received=len(batch.proposals), dry_run=False, sync_run_id=run.id)
    try:
        for payload in batch.proposals:
            await _upsert_proposal(session, payload, summary)
        run.status = "COMPLETED" if not summary.errors else "PARTIAL"
        run.finished_at = datetime.now(UTC)
        _copy_counts(run, summary)
        run.details = {"batch_number": batch.batch_number, "batch_total": batch.batch_total, "errors": summary.errors[:20]}
        event = "PROPOSAL_SYNC_COMPLETED" if run.status == "COMPLETED" else "PROPOSAL_SYNC_PARTIAL"
        await auth_repository.create_security_event(session, event, actor_user_id=actor.id, request_id=request_id, details={"sync_run_id": run.id, "received": summary.received, "created": summary.created, "updated": summary.updated, "unchanged": summary.unchanged, "rejected": summary.rejected})
        await session.commit()
        return summary
    except Exception as exc:
        await session.rollback()
        raise ApiError(error_codes.SYNC_BATCH_FAILED, "Nao foi possivel sincronizar o lote de propostas.", status_code=422) from exc


def _copy_counts(run: SyncRun, summary: SyncSummary) -> None:
    run.received_count = summary.received
    run.created_count = summary.created
    run.updated_count = summary.updated
    run.unchanged_count = summary.unchanged
    run.rejected_count = summary.rejected
    run.error_count = len(summary.errors)


def _validate_batch(batch: ProposalSyncBatch) -> list[str]:
    errors: list[str] = []
    legacy_ids: set[int] = set()
    for proposal in batch.proposals:
        if proposal.legacy_id in legacy_ids:
            errors.append(f"proposta legacy_id duplicado no lote: {proposal.legacy_id}")
        legacy_ids.add(proposal.legacy_id)
        item_numbers: set[str] = set()
        item_ids: set[int] = set()
        for item in proposal.items:
            if item.legacy_id in item_ids:
                errors.append(f"item legacy_id duplicado na proposta {proposal.legacy_id}: {item.legacy_id}")
            item_ids.add(item.legacy_id)
            if item.item_number in item_numbers:
                errors.append(f"numero_item duplicado na proposta {proposal.legacy_id}: {item.item_number}")
            item_numbers.add(item.item_number)
    return errors


async def _simulate(session: AsyncSession, batch: ProposalSyncBatch) -> SyncSummary:
    summary = SyncSummary(received=len(batch.proposals), dry_run=True)
    for payload in batch.proposals:
        existing = (await session.execute(select(Proposal).where(Proposal.legacy_id == payload.legacy_id))).scalars().first()
        if existing is None:
            summary.created += 1
        elif existing.source_hash != payload.source_hash:
            summary.updated += 1
        else:
            summary.unchanged += 1
    return summary


async def _upsert_proposal(session: AsyncSession, payload: ProposalSyncPayload, summary: SyncSummary) -> None:
    existing = (await session.execute(select(Proposal).options(selectinload(Proposal.items)).where(Proposal.legacy_id == payload.legacy_id))).scalars().first()
    if existing is None:
        proposal = Proposal()
        session.add(proposal)
        summary.created += 1
        existing_items: list[ProposalItem] = []
    else:
        proposal = existing
        existing_items = list(existing.items)
        if proposal.source_hash == payload.source_hash and _items_unchanged(proposal, payload):
            summary.unchanged += 1
            return
        summary.updated += 1
    _apply_proposal(proposal, payload)
    await session.flush()
    for item_payload in payload.items:
        item = next((candidate for candidate in existing_items if candidate.legacy_id == item_payload.legacy_id), None)
        if item is None:
            item = ProposalItem(proposal_id=proposal.id)
            session.add(item)
            summary.item_created += 1
        elif item.source_hash == item_payload.source_hash:
            summary.item_unchanged += 1
            continue
        else:
            summary.item_updated += 1
        _apply_item(item, item_payload)
        item.proposal_id = proposal.id


def _items_unchanged(proposal: Proposal, payload: ProposalSyncPayload) -> bool:
    by_legacy = {item.legacy_id: item.source_hash for item in proposal.items}
    return all(by_legacy.get(item.legacy_id) == item.source_hash for item in payload.items)


def _apply_proposal(proposal: Proposal, payload: ProposalSyncPayload) -> None:
    for field in (
        "legacy_id", "proposal_number", "customer_name", "project_name", "order_reference", "lot",
        "proposal_date", "deadline_date", "current_area", "current_status", "general_status",
        "production_status", "galvanization_status", "shipping_status", "warehouse_status",
        "flow_situation", "has_production_pending", "process_type", "parent_legacy_id",
        "partial_number", "is_partial", "is_cancelled", "is_completed", "source",
        "legacy_created_at", "legacy_updated_at", "source_hash",
    ):
        setattr(proposal, field, getattr(payload, field))
    proposal.synced_at = datetime.now(UTC)


def _apply_item(item: ProposalItem, payload) -> None:
    for field in (
        "legacy_id", "legacy_current_process_id", "item_number", "product_code", "description",
        "quantity", "unit", "unit_weight", "total_weight", "produce_internally",
        "requires_galvanization", "flow_defined", "produced", "galvanized", "delivered",
        "delivered_at", "legacy_created_at", "legacy_updated_at", "source_hash",
    ):
        value = getattr(payload, field)
        if isinstance(value, Decimal):
            value = value.quantize(Decimal("0.0001"))
        setattr(item, field, value)
    item.synced_at = datetime.now(UTC)
