from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import Select, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.app.core import error_codes
from api.app.core.exceptions import ApiError
from api.app.modules.auth import repository as auth_repository
from api.app.modules.auth.models import User
from api.app.modules.product_catalog import service as product_catalog_service
from api.app.modules.proposals.admin_correction import (
    STATE_FIELDS as ADMINISTRATIVE_STATE_FIELDS,
    VALID_TARGETS as ADMINISTRATIVE_VALID_TARGETS,
    allowed_corrections as administrative_allowed_corrections,
    collect_facts as collect_administrative_facts,
    normalize_area as normalize_administrative_area,
    normalize_status as normalize_administrative_status,
    option_payload as administrative_option_payload,
    preview as build_administrative_preview,
    snapshot as administrative_snapshot,
)
from api.app.modules.proposals.compensation import Allocation, CompensationError, CompensationPlan, ItemSnapshot, RequestedItem, build_compensation_plan
from api.app.modules.proposals.domain import ProductionStateMachine, ProposalStateMachine
from api.app.modules.proposals.models import ExpeditionEvent, ExpeditionItem, FiscalEvent, FiscalInvoice, FiscalInvoiceItem, FiscalRecord, FiscalItem, GalvanizationLoad, GalvanizationLoadEvent, GalvanizationLoadItem, ProductionAllocationTransfer, Proposal, ProposalEvent, ProposalItem, ProposalRemanagement, ProposalRemanagementItem, SyncRun
from api.app.modules.proposals.remanagement import calculate_item_balance, items_are_compatible, max_remanageable, quantity
from api.app.modules.proposals.weights import calculate_known_weight, calculate_weight_coverage, normalize_known_weight
from api.app.shared.formatting import format_quantity
from api.app.modules.proposals.schemas import (
    CompensationPlanError,
    CompensationProductPlan,
    CompensationTransfer,
    ExpeditionItemsRequest,
    ExpeditionItemSummary,
    ExpeditionProposalDetail,
    ExpeditionProposalSummary,
    ExpeditionRemanagementDeliveryRequest,
    ExpeditionRemanageRequest,
    ExpeditionVersionRequest,
    FiscalCancelInvoiceItemRequest,
    FiscalBatchRequest,
    FiscalBatchResponse,
    FiscalBatchProposalResult,
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
    FiscalSyncBatch,
    FutureMutationPlanOut,
    GalvanizationLoadCreate,
    GalvanizationLoadDetail,
    GalvanizationLoadSummary,
    GalvanizationLoadUpdate,
    GalvanizationLoadVersionRequest,
    GalvanizationReturnRequest,
    GalvanizationSyncBatch,
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
    ProposalAdministrativeCorrectionOptionsResponse,
    ProposalAdministrativeCorrectionPreviewRequest,
    ProposalAdministrativeCorrectionPreviewResponse,
    ProposalAdministrativeCorrectionRequest,
    ProposalCancelRequest,
    ProposalCreate,
    ProposalDetail,
    ProposalActivityItem,
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
    ProductionPauseRequest,
    ProductionProgress,
    ProductionProposalDetail,
    ProductionProposalListItem,
    ProductionResumeRequest,
    ProductionStartRequest,
    RemanagementAvailabilityRequest,
    RemanagementAvailabilityResponse,
    RemanagementCompatibleItem,
    RemanagementCompensationPlanResponse,
    RemanagementCompensationRequest,
    RemanagementConfirmRequest,
    RemanagementConfirmResult,
    RemanagementConfirmSourceSummary,
    RemanagementDestinationItem,
    RemanagementDestinationItemAvailability,
    RemanagementItemBalance,
    RemanagementPreview,
    RemanagementReviewItem,
    RemanagementReviewRequest,
    RemanagementReviewResult,
    RemanagementReviewSource,
    RemanagementReviewSummary,
    RemanagementSourceCandidate,
    RemanagementSummary,
    PaginatedRemanagementResponse,
    SyncSummary,
    ProposalItemUpdate,
    WarehouseProposalSummary,
    WarehouseStatusRequest,
)

logger = logging.getLogger(__name__)


def _proposal_is_cancelled(proposal: Proposal) -> bool:
    return bool(
        proposal.is_cancelled
        or _status_value(proposal.current_status) == "CANCELADA"
        or _status_value(proposal.general_status) == "CANCELADA"
    )


def _proposal_operational_clause():
    """Defesa para dados antigos que possam ter status CANCELADA sem a flag coerente."""
    return (
        Proposal.is_cancelled.is_(False)
        & (func.coalesce(Proposal.current_status, "") != "CANCELADA")
        & (func.coalesce(Proposal.general_status, "") != "CANCELADA")
    )


def _ensure_proposal_not_cancelled(proposal: Proposal) -> None:
    if _proposal_is_cancelled(proposal):
        raise ApiError(
            error_codes.PROPOSAL_CANCELLED_TERMINAL,
            "A proposta esta cancelada e nao pode mais receber movimentacoes.",
            status_code=409,
        )


def _proposal_is_completed(proposal: Proposal) -> bool:
    return bool(
        proposal.is_completed
        or _status_value(proposal.current_status) == "ENTREGUE"
        or _status_value(proposal.general_status) == "ENTREGUE"
        or _status_value(proposal.shipping_status) == "ENTREGUE"
        or _status_value(proposal.current_area) == "FINALIZADO"
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
PRODUCTION_STARTABLE_STATUSES = ProductionStateMachine.STARTABLE_STATUSES
PRODUCTION_COMPLETABLE_STATUSES = ProductionStateMachine.COMPLETABLE_STATUSES
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
EXPEDITION_ACTIVE_STATUSES = {"EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL", "SEPARACAO_INICIADA", "SEPARADO_COM_PENDENCIA", "SEPARADO", "ENTREGUE_PARCIAL"}
SYNC_LOCK_ID = 202607200003
GALVANIZATION_SYNC_LOCK_ID = 202607200004
FISCAL_SYNC_LOCK_ID = 202607200005
# Mantido apenas como contrato interno/compatibilidade de testes antigos. A API e o
# desktop nunca usam este catalogo como lista de escolha; as opcoes sao calculadas
# por proposta em get_allowed_administrative_corrections().
ADMINISTRATIVE_STATUS_OPTIONS = {area: set(statuses) for area, statuses in ADMINISTRATIVE_VALID_TARGETS.items()}


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
        "parent_proposal_id": row.parent_proposal_id,
        "is_cancelled": row.is_cancelled,
        "is_completed": row.is_completed,
        "legacy_updated_at": row.legacy_updated_at,
        "synced_at": row.synced_at,
        "version": row.version,
        "active": row.active,
    }


def _flow_lock_reason(item: ProposalItem) -> str | None:
    """Item-level movements that make the production flow (produce/galvanize) immutable
    through the normal item-flow endpoint. Order matters: the first match wins, from the
    most advanced (final) operational stage down to the earliest."""
    if not item.active:
        return "Item removido da proposta."
    if item.delivered:
        return "Item ja foi entregue ao cliente."
    if item.expedition_item is not None and item.expedition_item.active and item.expedition_item.separated_quantity > 0:
        return "Item ja foi separado para expedicao."
    if item.galvanized:
        return "Item ja retornou da galvanizacao."
    if any(load_item.active for load_item in item.galvanization_load_items):
        return "Item ja enviado para galvanizacao."
    if item.produced and item.produce_internally != "NAO":
        return "Item ja possui producao registrada."
    return None


def item_summary(row: ProposalItem) -> ProposalItemSummary:
    lock_reason = _flow_lock_reason(row)
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
        weight_source=row.weight_source,
        weight_status=row.weight_status,
        weight_synced_at=row.weight_synced_at,
        produce_internally=row.produce_internally,
        requires_galvanization=row.requires_galvanization,
        flow_defined=row.flow_defined,
        produced=row.produced,
        galvanized=row.galvanized,
        sent_to_galvanization=any(load_item.active for load_item in row.galvanization_load_items),
        delivered=row.delivered,
        synced_at=row.synced_at,
        source_hash=row.source_hash,
        version=row.version,
        active=row.active,
        notes=row.notes,
        flow_editable=lock_reason is None,
        flow_lock_reason=lock_reason,
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
    # O Controle Geral representa a proposta mae. Filhas continuam visiveis
    # apenas nas areas operacionais em que seus itens realmente estao.
    stmt = stmt.where(Proposal.parent_proposal_id.is_(None))
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
        .where(_proposal_operational_clause())
        .where(Proposal.active.is_(True))
    )
    if status:
        normalized_status = _production_status_value(status)
        stmt = stmt.where(or_(Proposal.production_status == normalized_status, Proposal.current_status == normalized_status))
    if search:
        value = f"%{search}%"
        stmt = stmt.where(or_(Proposal.proposal_number.ilike(value), Proposal.customer_name.ilike(value), Proposal.project_name.ilike(value), Proposal.lot.ilike(value)))
    rows = (await session.execute(stmt)).scalars().unique().all()
    active = [
        row for row in rows
        if any(_production_item_requires_attention(item) for item in _active_items(row))
        and _production_status_value(row.production_status or row.current_status) in PRODUCTION_ACTIVE_STATUSES
    ]
    active.sort(key=lambda row: (_production_sort_key(row), -(row.updated_at.timestamp() if row.updated_at else 0), row.id))
    paged = active[offset:offset + limit]
    return PaginatedProductionResponse(items=[_production_list_item(row) for row in paged], total=len(active), limit=limit, offset=offset)


async def list_production_items(session: AsyncSession, *, search: str | None, pending: bool | None, limit: int, offset: int) -> PaginatedProductionItemResponse:
    stmt = (
        select(Proposal)
        .options(selectinload(Proposal.items))
        .where(_proposal_operational_clause())
        .where(Proposal.active.is_(True))
    )
    if search:
        value = f"%{search}%"
        stmt = stmt.where(or_(Proposal.proposal_number.ilike(value), Proposal.customer_name.ilike(value), Proposal.project_name.ilike(value), Proposal.lot.ilike(value)))
    rows = (await session.execute(stmt)).scalars().unique().all()
    result: list[ProductionItemRow] = []
    for proposal in rows:
        if proposal.current_area != "PRODUCAO" and not any(
            _loaded_item_balance(item).production_reallocated_in_pending > 0 for item in _active_items(proposal)
        ):
            continue
        status_value = _production_status_value(proposal.production_status or proposal.current_status)
        if status_value not in PRODUCTION_ACTIVE_STATUSES:
            continue
        for item in _production_queue_items(proposal):
            item_pending = _production_item_requires_attention(item)
            if pending is True and not item_pending:
                continue
            if pending is False and item_pending:
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
            selectinload(Proposal.parent_proposal),
            selectinload(Proposal.expedition_items).selectinload(ExpeditionItem.proposal_item),
            selectinload(Proposal.fiscal_record).selectinload(FiscalRecord.items),
        )
        .where(Proposal.active.is_(True))
        .where(_proposal_operational_clause())
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
        .where(_proposal_operational_clause())
        .where(Proposal.parent_proposal_id.is_(None))
        .where(or_(Proposal.warehouse_status.in_(WAREHOUSE_STATUSES), Proposal.warehouse_status.is_(None)))
    )
    if status:
        normalized_status = status.strip().upper()
        if normalized_status == "NAO_DEFINIDO":
            stmt = stmt.where(Proposal.warehouse_status.is_(None))
        else:
            stmt = stmt.where(Proposal.warehouse_status == normalized_status)
    if search:
        value = f"%{search}%"
        stmt = stmt.where(or_(Proposal.proposal_number.ilike(value), Proposal.customer_name.ilike(value), Proposal.project_name.ilike(value), Proposal.lot.ilike(value)))
    rows = (await session.execute(stmt)).scalars().unique().all()
    rows.sort(key=lambda row: (_warehouse_sort_key(row), -(row.updated_at.timestamp() if row.updated_at else 0), row.id))
    paged = rows[offset:offset + limit]
    return PaginatedWarehouseProposalResponse(items=[_warehouse_proposal_summary(row) for row in paged], total=len(rows), limit=limit, offset=offset)


async def update_warehouse_status(session: AsyncSession, proposal_id: int, payload: WarehouseStatusRequest, actor: User, *, request_id: str | None) -> WarehouseProposalSummary:
    proposal = await get_proposal(session, proposal_id)
    _ensure_proposal_not_cancelled(proposal)
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


async def list_galvanization_candidates(session: AsyncSession, *, search: str | None, situation: str | None = None, include_unavailable: bool = False, limit: int, offset: int) -> PaginatedGalvanizationCandidateResponse:
    # Elegibilidade e por ITEM (_eligible_galvanization_items ja checa
    # produced/requires_galvanization/flow_defined/galvanized), nao por area
    # agregada da proposta: current_area so migra para GALVANIZACAO quando
    # TODOS os itens internos da proposta estao produzidos, entao um item
    # produzido individualmente (producao parcial) ficaria preso se
    # filtrassemos aqui por current_area/galvanization_status. A criacao de
    # carga (_ensure_item_eligible_for_galvanization) ja nunca dependeu desse
    # gate - so a listagem dependia, por isso o item sumia da fila mesmo
    # elegivel para montar carga.
    proposals = (
        (await session.execute(
            select(Proposal)
            .options(selectinload(Proposal.items))
            .where(Proposal.active.is_(True))
            .where(_proposal_operational_clause())
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
            # Item ja enviado para uma carga nao pode ser candidato novamente.
            # O saldo zero era exposto como diagnostico e o desktop o projetava
            # junto com a linha real da carga, duplicando a filha.
            if available <= 0 and not include_unavailable:
                continue
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


async def list_galvanization_loads(session: AsyncSession, *, status: str | None, search: str | None, proposal_id: int | None = None, limit: int, offset: int) -> PaginatedGalvanizationLoadResponse:
    stmt = select(GalvanizationLoad).options(selectinload(GalvanizationLoad.items).selectinload(GalvanizationLoadItem.proposal), selectinload(GalvanizationLoad.items).selectinload(GalvanizationLoadItem.proposal_item)).where(GalvanizationLoad.active.is_(True))
    if status:
        stmt = stmt.where(GalvanizationLoad.status == status)
    if proposal_id:
        stmt = stmt.where(GalvanizationLoad.id.in_(select(GalvanizationLoadItem.load_id).where(GalvanizationLoadItem.proposal_id == proposal_id)))
    rows = (await session.execute(stmt.order_by(GalvanizationLoad.created_at.desc(), GalvanizationLoad.id.desc()))).scalars().unique().all()
    if search:
        needle = search.lower()
        rows = [load for load in rows if needle in _galvanization_load_search_text(load)]
    return PaginatedGalvanizationLoadResponse(items=[_galvanization_load_summary(row) for row in rows[offset:offset + limit]], total=len(rows), limit=limit, offset=offset)


async def get_galvanization_load_detail(session: AsyncSession, load_id: int) -> GalvanizationLoadDetail:
    load = await _get_galvanization_load(session, load_id)
    actor_ids = {
        int(actor_id)
        for actor_id in (
            load.created_by,
            load.updated_by,
            *(event.actor_user_id for event in load.events),
        )
        if actor_id is not None
    }
    actor_names: dict[int, str] = {}
    if actor_ids:
        rows = (
            await session.execute(
                select(User.id, User.display_name, User.username).where(User.id.in_(actor_ids))
            )
        ).all()
        actor_names = {
            int(user_id): (display_name or username or f"Usuário #{user_id}")
            for user_id, display_name, username in rows
        }
    return _galvanization_load_detail(load, actor_names=actor_names)


async def create_galvanization_load(session: AsyncSession, payload: GalvanizationLoadCreate, actor: User, *, request_id: str | None) -> GalvanizationLoadDetail:
    try:
        load_weight = normalize_known_weight(payload.load_weight)
        load = GalvanizationLoad(
            driver_name=payload.driver_name,
            max_weight=payload.max_weight,
            load_weight=load_weight,
            load_weight_source=(payload.load_weight_source or "MANUAL") if load_weight is not None else None,
            load_weight_updated_at=datetime.now(UTC) if load_weight is not None else None,
            expected_return_date=payload.expected_return_date,
            notes=payload.notes,
            created_by=actor.id,
            updated_by=actor.id,
        )
        session.add(load)
        await session.flush()
        load.code = f"CG{int(load.id):05d}"
        composition = await _replace_galvanization_load_items(session, load, payload.items, actor, request_id=request_id)
        await _record_load_event(
            session,
            load,
            "GALVANIZATION_LOAD_CREATED",
            actor,
            request_id=request_id,
            metadata={"items": len(payload.items), **composition},
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return await get_galvanization_load_detail(session, int(load.id))


async def update_galvanization_load(session: AsyncSession, load_id: int, payload: GalvanizationLoadUpdate, actor: User, *, request_id: str | None) -> GalvanizationLoadDetail:
    try:
        load = await _get_galvanization_load(session, load_id, for_update=True)
        _ensure_load_version(load, payload.version)
        _ensure_load_editable(load)
        if payload.driver_name is not None:
            load.driver_name = payload.driver_name
        if payload.max_weight is not None:
            load.max_weight = payload.max_weight
        if "load_weight" in payload.model_fields_set:
            load.load_weight = normalize_known_weight(payload.load_weight)
            load.load_weight_source = (payload.load_weight_source or "MANUAL") if load.load_weight is not None else None
            load.load_weight_updated_at = datetime.now(UTC)
        elif payload.load_weight_source is not None and load.load_weight is not None:
            load.load_weight_source = payload.load_weight_source
            load.load_weight_updated_at = datetime.now(UTC)
        if "expected_return_date" in payload.model_fields_set:
            load.expected_return_date = payload.expected_return_date
        if payload.notes is not None:
            load.notes = payload.notes
        composition = None
        if payload.items is not None:
            composition = await _replace_galvanization_load_items(session, load, payload.items, actor, request_id=request_id)
        version_before = int(load.version)
        _touch(load, actor)
        metadata = {"version_before": version_before, "version_after": int(load.version)}
        if composition is not None:
            metadata.update(composition)
        await _record_load_event(session, load, "GALVANIZATION_LOAD_UPDATED", actor, request_id=request_id, metadata=metadata)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return await get_galvanization_load_detail(session, load_id)


async def release_galvanization_load(session: AsyncSession, load_id: int, payload: GalvanizationLoadVersionRequest, actor: User, *, request_id: str | None) -> GalvanizationLoadDetail:
    load = await _get_galvanization_load(session, load_id, for_update=True)
    _ensure_load_version(load, payload.version)
    if load.status != "AGUARDANDO_LIBERACAO":
        raise ApiError(error_codes.GALVANIZATION_LOAD_INVALID_STATE, "Somente cargas aguardando liberacao podem ser enviadas.", status_code=409)
    active_items = [item for item in load.items if item.active]
    if not active_items:
        raise ApiError(error_codes.GALVANIZATION_LOAD_EMPTY, "A carga nao possui itens.", status_code=409)
    for load_item in active_items:
        _ensure_proposal_not_cancelled(load_item.proposal)
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
    load = await _get_galvanization_load(session, load_id, for_update=True)
    if await _request_event_exists(session, request_id, event_type="GALVANIZATION_RETURN_REGISTERED", load_id=load.id):
        return await get_galvanization_load_detail(session, load_id)
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
        load_item.returned_weight = calculate_known_weight(load_item.returned_quantity, load_item.unit_weight)
        load_item.status = "RETORNADO" if load_item.returned_quantity >= load_item.sent_quantity else "RETORNO_PARCIAL"
        load_item.returned_at = now if load_item.status == "RETORNADO" else load_item.returned_at
        _touch(load_item, actor)
        affected_proposals.add(int(load_item.proposal_id))
        await _record_load_event(session, load, "GALVANIZATION_ITEM_RETURNED", actor, load_item=load_item, request_id=request_id, from_status=previous, to_status=load_item.status, metadata={"quantity": str(qty), "observation": payload.observation})
    # Os proposals afetados sao resolvidos uma unica vez aqui, antes de
    # qualquer fusao. _merge_equal_status_partial_children reatribui
    # GalvanizationLoadItem.proposal_id das filhas fundidas para a
    # sobrevivente, entao procurar de novo em load.items por proposal_id
    # depois da fusao pode nao encontrar mais nenhum item para a filha
    # fundida (StopIteration). Guardamos a referencia ao objeto Proposal
    # aqui para que a fusao subsequente nao invalide a consulta.
    proposal_by_id: dict[int, Proposal] = {
        proposal_id: next(item.proposal for item in load.items if int(item.proposal_id) == proposal_id)
        for proposal_id in affected_proposals
    }
    for proposal_id in affected_proposals:
        proposal = proposal_by_id[proposal_id]
        if _proposal_is_cancelled(proposal):
            await _record_event(session, proposal, "GALVANIZATION_RETURN_RECORDED_AFTER_CANCELLATION", actor, request_id=request_id, from_area=proposal.current_area, from_status=proposal.current_status, to_area=proposal.current_area, to_status=proposal.current_status, metadata={"load_id": load.id, "observation": payload.observation, "terminal_state_preserved": True})
        else:
            await _recalculate_galvanization_proposal_state(session, proposal, actor, request_id=request_id, load_id=load.id, observation=payload.observation)
    # O retorno pode ser o ultimo evento que coloca todas as filhas na
    # Expedicao. Nesse ponto a estrutura mae-filhas precisa ser recalculada
    # imediatamente; esperar uma nova acao na Expedicao deixava as filhas
    # separadas no backend e fazia a lista de itens consultar somente uma
    # delas. A uniao continua respeitando area, status e conjunto de cargas.
    parent_ids = {
        int(proposal.parent_proposal_id)
        for proposal in proposal_by_id.values()
        if proposal.parent_proposal_id is not None
    }
    for parent_id in parent_ids:
        await _merge_equal_status_partial_children(session, parent_id, actor, request_id=request_id)
    for proposal_id in affected_proposals:
        proposal = proposal_by_id[proposal_id]
        if proposal.parent_proposal_id is not None:
            await _reborn_parent_when_children_converge(session, proposal, actor, request_id=request_id)
    previous_load_status = load.status
    _recalculate_load_return_state(load, now)
    _touch(load, actor)
    await _record_load_event(session, load, "GALVANIZATION_RETURN_REGISTERED", actor, request_id=request_id, from_status=previous_load_status, to_status=load.status, metadata={"affected_proposals": sorted(affected_proposals), "observation": payload.observation})
    await session.commit()
    return await get_galvanization_load_detail(session, load_id)


async def close_galvanization_load(session: AsyncSession, load_id: int, payload: GalvanizationLoadVersionRequest, actor: User, *, request_id: str | None) -> GalvanizationLoadDetail:
    load = await _get_galvanization_load(session, load_id, for_update=True)
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
    if await _sync_expedition_from_available_items(session):
        await session.commit()
    stmt = (
        select(Proposal)
        .options(selectinload(Proposal.items), selectinload(Proposal.expedition_items).selectinload(ExpeditionItem.proposal_item))
        .where(Proposal.active.is_(True))
        .where(_proposal_operational_clause())
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
    if await _sync_expedition_from_available_items(session):
        await session.commit()
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
    reborn = await _reborn_parent_when_children_converge(session, proposal, actor, request_id=request_id)
    await session.commit()
    return await get_expedition_detail(session, reborn.id if reborn is not None else proposal_id)


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
    reborn = await _reborn_parent_when_children_converge(session, proposal, actor, request_id=request_id)
    await session.commit()
    return await get_expedition_detail(session, reborn.id if reborn is not None else proposal_id)


async def return_expedition_items_to_production(session: AsyncSession, proposal_id: int, payload: ExpeditionRemanageRequest, actor: User, *, request_id: str | None) -> ExpeditionProposalDetail:
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
        _touch(exp_item, actor)
        await _record_expedition_event(session, proposal, "EXPEDITION_ITEM_RETURNED_TO_PRODUCTION", actor, expedition_item=exp_item, request_id=request_id, from_status=previous, to_status=exp_item.status, metadata={"quantity": str(qty), "reason": payload.reason, "historical_produced_preserved": True, "historical_galvanized_preserved": True})
    proposal.current_area = "PRODUCAO"
    proposal.current_status = "ITEM_PENDENTE_FABRICACAO"
    proposal.general_status = "EM_PRODUCAO"
    proposal.production_status = "ITEM_PENDENTE_FABRICACAO"
    proposal.shipping_status = "ENTREGUE_PARCIAL" if any(item.delivered_quantity > 0 for item in _active_expedition_items(proposal)) else "EM_SEPARACAO"
    proposal.has_production_pending = True
    proposal.flow_situation = "PARCIAL_COM_PENDENCIA"
    _touch(proposal, actor)
    await _record_event(session, proposal, "EXPEDITION_RETURN_TO_PRODUCTION", actor, request_id=request_id, from_area="EXPEDICAO", to_area="PRODUCAO", to_status="ITEM_PENDENTE_FABRICACAO", metadata={"reason": payload.reason})
    await session.commit()
    return await get_expedition_detail(session, proposal_id)


async def _item_allocation_balance(session: AsyncSession, item: ProposalItem):
    expedition = item.expedition_item
    production_out = Decimal(str((await session.execute(
        select(func.coalesce(func.sum(ProductionAllocationTransfer.quantity), 0)).where(ProductionAllocationTransfer.from_item_id == item.id)
    )).scalar_one() or "0"))
    production_in_pending = Decimal(str((await session.execute(
        select(func.coalesce(func.sum(ProductionAllocationTransfer.quantity - ProductionAllocationTransfer.completed_quantity), 0))
        .where(ProductionAllocationTransfer.to_item_id == item.id)
        .where(ProductionAllocationTransfer.status != "COMPLETED")
    )).scalar_one() or "0"))
    production_in_completed = Decimal(str((await session.execute(
        select(func.coalesce(func.sum(ProductionAllocationTransfer.completed_quantity), 0)).where(ProductionAllocationTransfer.to_item_id == item.id)
    )).scalar_one() or "0"))
    return calculate_item_balance(
        requested=item.quantity,
        produced=item.produced,
        produce_internally=item.produce_internally,
        expedition_available=expedition.available_quantity if expedition else 0,
        delivered=expedition.delivered_quantity if expedition else 0,
        remanaged_out=expedition.remanaged_quantity if expedition else 0,
        production_reallocated_out=production_out,
        production_reallocated_in_pending=production_in_pending,
        production_reallocated_in_completed=production_in_completed,
    )


async def _locked_remanagement_proposals(session: AsyncSession, source_id: int, destination_id: int) -> tuple[Proposal, Proposal]:
    if source_id == destination_id:
        raise ApiError(error_codes.EXPEDITION_REMANAGEMENT_INVALID, "Origem e destino precisam ser propostas diferentes.", status_code=409)
    rows = (
        (await session.execute(
            select(Proposal)
            .options(selectinload(Proposal.items).selectinload(ProposalItem.expedition_item))
            .where(Proposal.id.in_([source_id, destination_id]))
            .order_by(Proposal.id)
            .with_for_update()
        ))
        .scalars()
        .unique()
        .all()
    )
    by_id = {int(row.id): row for row in rows}
    if source_id not in by_id or destination_id not in by_id:
        raise ApiError(error_codes.PROPOSAL_NOT_FOUND, "Proposta de origem ou destino nao encontrada.", status_code=404)
    return by_id[source_id], by_id[destination_id]


async def _locked_remanagement_participants(session: AsyncSession, proposal_ids: list[int]) -> dict[int, Proposal]:
    """Generaliza `_locked_remanagement_proposals` para N propostas (Fase 7:
    um destino + varias origens distintas). Mesmo formato de consulta (lock
    ordenado por id para evitar deadlock entre confirmacoes concorrentes que
    compartilhem alguma proposta)."""
    unique_ids = sorted(set(proposal_ids))
    rows = (
        (await session.execute(
            select(Proposal)
            .options(selectinload(Proposal.items).selectinload(ProposalItem.expedition_item))
            .where(Proposal.id.in_(unique_ids))
            .order_by(Proposal.id)
            .with_for_update()
        ))
        .scalars()
        .unique()
        .all()
    )
    by_id = {int(row.id): row for row in rows}
    missing = [proposal_id for proposal_id in unique_ids if proposal_id not in by_id]
    if missing:
        raise ApiError(error_codes.PROPOSAL_NOT_FOUND, "Proposta de origem ou destino nao encontrada.", status_code=404)
    return by_id


async def _evaluate_remanagement(session: AsyncSession, payload: ExpeditionRemanagementDeliveryRequest, source: Proposal, destination: Proposal):
    _ensure_proposal_not_cancelled(source)
    _ensure_proposal_not_cancelled(destination)
    if not source.active or not destination.active or _proposal_is_completed(destination):
        raise ApiError(error_codes.EXPEDITION_REMANAGEMENT_INVALID, "Origem e destino precisam estar ativos e o destino ainda deve possuir necessidade.", status_code=409)
    _ensure_version(source.version, payload.source_version)
    _ensure_version(destination.version, payload.destination_version)
    source_items = {int(item.id): item for item in _active_items(source)}
    destination_items = {int(item.id): item for item in _active_items(destination)}
    seen_source: set[int] = set()
    seen_destination: set[int] = set()
    evaluated = []
    for requested in payload.items:
        if requested.source_item_id in seen_source or requested.destination_item_id in seen_destination:
            raise ApiError(error_codes.EXPEDITION_REMANAGEMENT_INVALID, "Cada item pode aparecer uma unica vez por remanejamento.", status_code=409)
        seen_source.add(requested.source_item_id)
        seen_destination.add(requested.destination_item_id)
        source_item = source_items.get(requested.source_item_id)
        destination_item = destination_items.get(requested.destination_item_id)
        if source_item is None or destination_item is None:
            raise ApiError(error_codes.EXPEDITION_REMANAGEMENT_INVALID, "Item nao pertence a proposta de origem ou destino.", status_code=409)
        if requested.source_item_version is not None:
            _ensure_version(source_item.version, requested.source_item_version)
        if requested.destination_item_version is not None:
            _ensure_version(destination_item.version, requested.destination_item_version)
        compatible, reason = items_are_compatible(source_item, destination_item)
        if not compatible:
            raise ApiError(error_codes.EXPEDITION_REMANAGEMENT_INVALID, reason or "Itens incompativeis.", status_code=409)
        if source_item.requires_galvanization == "SIM":
            raise ApiError(
                error_codes.EXPEDITION_REMANAGEMENT_INVALID,
                "Itens com galvanizacao nao podem ser remanejados ate que a alocacao quantitativa dessa etapa esteja rastreavel.",
                status_code=409,
            )
        source_balance = await _item_allocation_balance(session, source_item)
        destination_balance = await _item_allocation_balance(session, destination_item)
        maximum = max_remanageable(source_balance, destination_balance)
        qty = quantity(requested.quantity)
        if qty > maximum:
            raise ApiError(
                error_codes.EXPEDITION_REMANAGEMENT_INVALID,
                f"Quantidade remanejada excede o maximo permitido de {format_quantity(maximum)} para o item {source_item.item_number}.",
                status_code=409,
            )
        evaluated.append((requested, source_item, destination_item, source_balance, destination_balance, maximum, qty))
    return evaluated


def _remanagement_balance_schema(source_item, destination_item, source_balance, destination_balance, maximum, qty) -> RemanagementItemBalance:
    return RemanagementItemBalance(
        source_item_id=source_item.id,
        destination_item_id=destination_item.id,
        product_code=source_item.product_code,
        unit=source_item.unit,
        quantity=qty,
        max_remanageable=maximum,
        source_ready_before=source_balance.ready_available,
        source_ready_after=source_balance.ready_available - qty,
        destination_ready_before=destination_balance.ready_available,
        destination_ready_after=destination_balance.ready_available + qty,
        destination_need_before=destination_balance.destination_need,
        destination_need_after=destination_balance.destination_need - qty,
        destination_reallocatable_production_before=destination_balance.reallocatable_production,
        destination_reallocatable_production_after=destination_balance.reallocatable_production - qty,
        production_reallocated_quantity=qty,
        weight_snapshot=source_item.unit_weight,
    )


async def simulate_remanagement(session: AsyncSession, payload: ExpeditionRemanagementDeliveryRequest) -> RemanagementPreview:
    source = await get_proposal(session, payload.source_proposal_id)
    destination = await get_proposal(session, payload.destination_proposal_id)
    evaluated = await _evaluate_remanagement(session, payload, source, destination)
    items = [_remanagement_balance_schema(*row[1:]) for row in evaluated]
    return RemanagementPreview(
        source_proposal_id=source.id,
        destination_proposal_id=destination.id,
        source_version=source.version,
        destination_version=destination.version,
        total_quantity=sum((item.quantity for item in items), Decimal("0")).quantize(Decimal("0.0001")),
        items=items,
    )


async def _get_remanagement_by_key(session: AsyncSession, idempotency_key: str) -> ProposalRemanagement | None:
    return (
        (await session.execute(
            select(ProposalRemanagement)
            .options(selectinload(ProposalRemanagement.items).selectinload(ProposalRemanagementItem.production_transfer))
            .where(ProposalRemanagement.idempotency_key == idempotency_key)
        ))
        .scalars()
        .unique()
        .first()
    )


def _remanagement_summary(row: ProposalRemanagement) -> RemanagementSummary:
    items = [
        RemanagementItemBalance(
            source_item_id=item.source_item_id,
            destination_item_id=item.destination_item_id,
            product_code=item.product_code_snapshot,
            unit=item.unit_snapshot,
            quantity=item.quantity,
            max_remanageable=item.quantity,
            source_ready_before=item.source_ready_before,
            source_ready_after=item.source_ready_after,
            destination_ready_before=item.destination_ready_before,
            destination_ready_after=item.destination_ready_after,
            destination_need_before=item.destination_need_before,
            destination_need_after=item.destination_need_after,
            destination_reallocatable_production_before=item.destination_reallocatable_before,
            destination_reallocatable_production_after=item.destination_reallocatable_after,
            production_reallocated_quantity=item.production_reallocated_quantity,
            weight_snapshot=item.weight_snapshot,
        )
        for item in row.items
    ]
    return RemanagementSummary(
        id=row.id,
        code=row.code or f"RM-{int(row.id):06d}",
        status=row.status,
        reason=row.reason,
        idempotency_key=row.idempotency_key,
        request_id=row.request_id,
        correlation_id=row.correlation_id,
        created_by=row.created_by,
        created_at=row.created_at,
        source_proposal_id=row.source_proposal_id,
        destination_proposal_id=row.destination_proposal_id,
        source_version=row.source_version_snapshot,
        destination_version=row.destination_version_snapshot,
        total_quantity=sum((item.quantity for item in items), Decimal("0")).quantize(Decimal("0.0001")),
        items=items,
    )


async def apply_remanagement(session: AsyncSession, payload: ExpeditionRemanagementDeliveryRequest, actor: User, *, request_id: str | None) -> RemanagementSummary:
    existing = await _get_remanagement_by_key(session, payload.idempotency_key)
    if existing is not None:
        return _remanagement_summary(existing)
    try:
        source, destination = await _locked_remanagement_proposals(session, payload.source_proposal_id, payload.destination_proposal_id)
        existing = await _get_remanagement_by_key(session, payload.idempotency_key)
        if existing is not None:
            return _remanagement_summary(existing)
        evaluated = await _evaluate_remanagement(session, payload, source, destination)
        source_before = {"area": source.current_area, "status": source.current_status, "production_status": source.production_status, "shipping_status": source.shipping_status}
        destination_before = {"area": destination.current_area, "status": destination.current_status, "production_status": destination.production_status, "shipping_status": destination.shipping_status}
        remanagement = ProposalRemanagement(
            source_proposal_id=source.id,
            destination_proposal_id=destination.id,
            reason=payload.reason,
            idempotency_key=payload.idempotency_key,
            request_id=request_id,
            correlation_id=payload.idempotency_key,
            source_version_snapshot=source.version,
            destination_version_snapshot=destination.version,
            created_by=actor.id,
        )
        session.add(remanagement)
        await session.flush()
        remanagement.code = f"RM-{int(remanagement.id):06d}"
        for _, source_item, destination_item, source_balance, destination_balance, maximum, qty in evaluated:
            balance = _remanagement_balance_schema(source_item, destination_item, source_balance, destination_balance, maximum, qty)
            line = ProposalRemanagementItem(
                remanagement_id=remanagement.id,
                source_item_id=source_item.id,
                destination_item_id=destination_item.id,
                quantity=qty,
                source_ready_before=balance.source_ready_before,
                source_ready_after=balance.source_ready_after,
                destination_need_before=balance.destination_need_before,
                destination_need_after=balance.destination_need_after,
                destination_ready_before=balance.destination_ready_before,
                destination_ready_after=balance.destination_ready_after,
                destination_reallocatable_before=balance.destination_reallocatable_production_before,
                destination_reallocatable_after=balance.destination_reallocatable_production_after,
                production_reallocated_quantity=qty,
                weight_snapshot=source_item.unit_weight,
                product_code_snapshot=source_item.product_code,
                unit_snapshot=source_item.unit,
            )
            session.add(line)
            await session.flush()
            session.add(ProductionAllocationTransfer(
                remanagement_item_id=line.id,
                from_item=destination_item,
                to_item=source_item,
                quantity=qty,
                created_by=actor.id,
            ))
            source_expedition = source_item.expedition_item
            if source_expedition is None:
                raise ApiError(error_codes.EXPEDITION_REMANAGEMENT_INVALID, "Item de origem nao possui disponibilidade oficial na Expedicao.", status_code=409)
            previous_source_status = source_expedition.status
            source_expedition.remanaged_quantity = quantity(source_expedition.remanaged_quantity + qty)
            source_expedition.separated_quantity = max(source_expedition.delivered_quantity, min(source_expedition.separated_quantity, source_expedition.available_quantity - source_expedition.remanaged_quantity))
            # "DISPONIVEL_PARCIAL" nao existe em ck_expedition_items_status (bug
            # pre-existente, nunca exercitado pelos testes legados porque so
            # cobriam remanejamento total da origem). Com saldo ainda restante o
            # item continua no MESMO status que ja tinha (ainda elegivel para a
            # propria separacao/entrega) - so vira REMANEJADO quando esgotado.
            source_expedition.status = "REMANEJADO" if balance.source_ready_after <= 0 else previous_source_status
            _touch(source_expedition, actor)
            destination_expedition = destination_item.expedition_item
            if destination_expedition is None:
                destination_expedition = ExpeditionItem(proposal_id=destination.id, proposal_item_id=destination_item.id, available_quantity=qty, origin="REMANEJAMENTO", status="EM_SEPARACAO", created_by=actor.id, updated_by=actor.id)
                destination_expedition.proposal = destination
                destination_expedition.proposal_item = destination_item
                session.add(destination_expedition)
                await session.flush()
            else:
                destination_expedition.available_quantity = quantity(destination_expedition.available_quantity + qty)
                destination_expedition.origin = "MISTO" if destination_expedition.origin != "REMANEJAMENTO" else destination_expedition.origin
                if destination_expedition.status not in {"SEPARACAO_INICIADA", "SEPARADO", "ENTREGUE_PARCIAL"}:
                    destination_expedition.status = "EM_SEPARACAO"
                _touch(destination_expedition, actor)
            event_metadata = {"remanagement_id": remanagement.id, "code": remanagement.code, "source_item_id": source_item.id, "destination_item_id": destination_item.id, "quantity": str(qty), "reason": payload.reason, "source_ready_before": str(balance.source_ready_before), "source_ready_after": str(balance.source_ready_after), "destination_need_before": str(balance.destination_need_before), "destination_need_after": str(balance.destination_need_after), "production_reallocated_quantity": str(qty)}
            await _record_expedition_event(session, source, "COMPENSATED_REMANAGEMENT_READY_SENT", actor, expedition_item=source_expedition, request_id=request_id, from_status=previous_source_status, to_status=source_expedition.status, metadata=event_metadata)
            await _record_expedition_event(session, destination, "COMPENSATED_REMANAGEMENT_READY_RECEIVED", actor, expedition_item=destination_expedition, request_id=request_id, to_status=destination_expedition.status, metadata=event_metadata)
        source.has_production_pending = True
        source.production_status = "ITEM_PENDENTE_FABRICACAO"
        source.flow_situation = "PENDENTE_POR_REMANEJAMENTO"
        mapped_destination_pending = {
            int(row[2].id): row[4].production_pending - row[6]
            for row in evaluated
        }
        destination_has_production_pending = any(
            mapped_destination_pending.get(int(item.id), _loaded_item_balance(item).production_pending) > 0
            for item in _internal_items(destination)
        )
        destination.shipping_status = "EM_SEPARACAO"
        if not destination_has_production_pending:
            destination.production_status = "FINALIZADO"
            destination.has_production_pending = False
            destination.current_area = "EXPEDICAO"
            destination.current_status = "EM_SEPARACAO"
            destination.general_status = "EM_EXPEDICAO"
            destination.flow_situation = "NORMAL"
        else:
            destination.has_production_pending = True
            destination.flow_situation = "PARCIAL_COM_PENDENCIA"
        _touch(source, actor)
        _touch(destination, actor)
        source_after = {"area": source.current_area, "status": source.current_status, "production_status": source.production_status, "shipping_status": source.shipping_status}
        destination_after = {"area": destination.current_area, "status": destination.current_status, "production_status": destination.production_status, "shipping_status": destination.shipping_status}
        await _record_event(session, source, "COMPENSATED_REMANAGEMENT_APPLIED", actor, request_id=request_id, from_area=source_before["area"], from_status=source_before["status"], to_area=source.current_area, to_status=source.current_status, metadata={"remanagement_id": remanagement.id, "code": remanagement.code, "destination_proposal_id": destination.id, "reason": payload.reason, "state_before": source_before, "state_after": source_after})
        await _record_event(session, destination, "COMPENSATED_REMANAGEMENT_RECEIVED", actor, request_id=request_id, from_area=destination_before["area"], from_status=destination_before["status"], to_area=destination.current_area, to_status=destination.current_status, metadata={"remanagement_id": remanagement.id, "code": remanagement.code, "source_proposal_id": source.id, "reason": payload.reason, "state_before": destination_before, "state_after": destination_after})
        await auth_repository.create_security_event(session, "COMPENSATED_REMANAGEMENT_APPLIED", actor_user_id=actor.id, request_id=request_id, details={"remanagement_id": remanagement.id, "source_proposal_id": source.id, "destination_proposal_id": destination.id, "idempotency_key": payload.idempotency_key})
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await _get_remanagement_by_key(session, payload.idempotency_key)
        if existing is not None:
            return _remanagement_summary(existing)
        raise
    except Exception:
        await session.rollback()
        raise
    return _remanagement_summary(await _get_remanagement_by_key(session, payload.idempotency_key))


async def _get_remanagement_batch_by_operation_id(session: AsyncSession, operation_id: str) -> list[ProposalRemanagement]:
    """Um `operation_id` (Fase 7) pode abranger varias linhas
    `ProposalRemanagement` (uma por origem distinta), todas compartilhando o
    mesmo `correlation_id`. Usado tanto para o replay idempotente quanto para
    montar a resposta apos o commit."""
    return (
        (await session.execute(
            select(ProposalRemanagement)
            .options(selectinload(ProposalRemanagement.items).selectinload(ProposalRemanagementItem.production_transfer))
            .where(ProposalRemanagement.correlation_id == operation_id)
            .order_by(ProposalRemanagement.id)
        ))
        .scalars()
        .unique()
        .all()
    )


def _confirm_result_from_rows(operation_id: str, rows: list[ProposalRemanagement]) -> RemanagementConfirmResult:
    destination_id = rows[0].destination_proposal_id
    source_ids = sorted({row.source_proposal_id for row in rows})
    destination_item_ids = {item.destination_item_id for row in rows for item in row.items}
    allocations = sum(len(row.items) for row in rows)
    confirmed_at = max((row.created_at for row in rows if row.created_at is not None), default=datetime.now(UTC))
    return RemanagementConfirmResult(
        operation_id=operation_id,
        status="CONFIRMED",
        destination_proposal_id=destination_id,
        source_proposals=source_ids,
        products=len(destination_item_ids),
        allocations=allocations,
        confirmed_at=confirmed_at,
        remanagements=[
            RemanagementConfirmSourceSummary(source_proposal_id=row.source_proposal_id, remanagement_id=row.id, code=row.code or f"RM-{int(row.id):06d}")
            for row in rows
        ],
    )


async def confirm_remanagement_batch(session: AsyncSession, payload: RemanagementConfirmRequest, actor: User, *, request_id: str | None) -> RemanagementConfirmResult:
    """Fase 7 do novo fluxo de Remanejamento: unico ponto que de fato grava no
    banco o plano montado nas Fases 1-6. Revalida tudo dentro da transacao
    (destino, cada origem, cada saldo) sem confiar em nenhuma fotografia das
    fases anteriores, trava destino e todas as origens distintas com
    `_locked_remanagement_participants` e persiste em um unico
    `session.commit()` no final - qualquer excecao no meio reverte tudo (tudo
    ou nada), exatamente como `apply_remanagement` (fluxo legado) ja faz para
    uma unica origem.

    Uma "operacao" do usuario (`operation_id`) pode abranger varias propostas
    de origem diferentes para o mesmo destino. O modelo existente
    `ProposalRemanagement` so suporta uma origem por linha, entao cada origem
    distinta vira uma linha propria, todas compartilhando o mesmo
    `correlation_id=operation_id` (campo ja existente, reaproveitado como
    chave de agrupamento do lote - nenhuma migracao nova) e cada uma com seu
    proprio `idempotency_key=f"{operation_id}:{source_proposal_id}"`, unico
    por (operacao, origem) - protege contra duplo clique/retry de rede tanto
    no nivel da operacao inteira quanto de cada linha individual."""
    existing_rows = await _get_remanagement_batch_by_operation_id(session, payload.operation_id)
    if existing_rows:
        return _confirm_result_from_rows(payload.operation_id, existing_rows)

    source_proposal_ids = sorted({allocation.source_proposal_id for allocation in payload.allocations})
    if payload.destination_proposal_id in source_proposal_ids:
        raise ApiError(error_codes.EXPEDITION_REMANAGEMENT_INVALID, "Origem e destino precisam ser propostas diferentes.", status_code=409)

    try:
        preloaded = await _locked_remanagement_participants(session, [payload.destination_proposal_id, *source_proposal_ids])
        existing_rows = await _get_remanagement_batch_by_operation_id(session, payload.operation_id)
        if existing_rows:
            return _confirm_result_from_rows(payload.operation_id, existing_rows)

        for source_id in source_proposal_ids:
            source_proposal = preloaded[source_id]
            _ensure_proposal_not_cancelled(source_proposal)
            if not source_proposal.active:
                raise ApiError(error_codes.EXPEDITION_REMANAGEMENT_INVALID, f"Proposta de origem {source_proposal.proposal_number} nao esta mais ativa para remanejamento.", status_code=409)

        compensation_payload = RemanagementCompensationRequest(destination_proposal_id=payload.destination_proposal_id, items=payload.items, allocations=payload.allocations)
        destination, requested_items, allocations, item_snapshots, items_by_id = await _load_compensation_snapshots(session, compensation_payload, preloaded_proposals=preloaded)
        plan = build_compensation_plan(destination_proposal_id=destination.id, requested_items=requested_items, allocations=allocations, item_snapshots=item_snapshots)
        if plan.errors:
            first_error = plan.errors[0]
            raise ApiError(
                error_codes.EXPEDITION_REMANAGEMENT_INVALID,
                first_error.message,
                status_code=409,
                details={"code": first_error.code, "destination_item_id": first_error.destination_item_id, "source_item_id": first_error.source_item_id},
            )
        if not plan.lines:
            raise ApiError(error_codes.EXPEDITION_REMANAGEMENT_INVALID, "Nenhuma linha de compensacao valida para confirmar.", status_code=409)

        fresh_balances = await _batch_item_allocation_balances(session, list(items_by_id.values()))

        lines_by_source: dict[int, list] = {}
        for line in plan.lines:
            lines_by_source.setdefault(line.source_proposal_id, []).append(line)

        destination_before = {"area": destination.current_area, "status": destination.current_status, "production_status": destination.production_status, "shipping_status": destination.shipping_status}
        sources_before = {
            source_id: {"area": preloaded[source_id].current_area, "status": preloaded[source_id].current_status, "production_status": preloaded[source_id].production_status, "shipping_status": preloaded[source_id].shipping_status}
            for source_id in source_proposal_ids
        }

        created_rows: list[ProposalRemanagement] = []
        transferred_by_destination_item: dict[int, Decimal] = {}

        for source_id in source_proposal_ids:
            source_lines = lines_by_source.get(source_id)
            if not source_lines:
                continue
            source_proposal = preloaded[source_id]
            remanagement = ProposalRemanagement(
                source_proposal_id=source_proposal.id,
                destination_proposal_id=destination.id,
                reason=payload.reason,
                idempotency_key=f"{payload.operation_id}:{source_proposal.id}",
                request_id=request_id,
                correlation_id=payload.operation_id,
                source_version_snapshot=source_proposal.version,
                destination_version_snapshot=destination.version,
                created_by=actor.id,
            )
            session.add(remanagement)
            await session.flush()
            remanagement.code = f"RM-{int(remanagement.id):06d}"
            created_rows.append(remanagement)

            for line in source_lines:
                source_item = items_by_id[line.source_item_id]
                destination_item = items_by_id[line.destination_item_id]
                qty = line.ready_quantity_to_destination
                source_balance = fresh_balances[source_item.id]
                destination_balance = fresh_balances[destination_item.id]
                source_ready_after = source_balance.ready_available - qty
                item_row = ProposalRemanagementItem(
                    remanagement_id=remanagement.id,
                    source_item_id=source_item.id,
                    destination_item_id=destination_item.id,
                    quantity=qty,
                    source_ready_before=source_balance.ready_available,
                    source_ready_after=source_ready_after,
                    destination_need_before=destination_balance.destination_need,
                    destination_need_after=destination_balance.destination_need - qty,
                    destination_ready_before=destination_balance.ready_available,
                    destination_ready_after=destination_balance.ready_available + qty,
                    destination_reallocatable_before=destination_balance.reallocatable_production,
                    destination_reallocatable_after=destination_balance.reallocatable_production - qty,
                    production_reallocated_quantity=qty,
                    weight_snapshot=source_item.unit_weight,
                    product_code_snapshot=source_item.product_code,
                    unit_snapshot=source_item.unit,
                )
                session.add(item_row)
                await session.flush()
                session.add(ProductionAllocationTransfer(remanagement_item_id=item_row.id, from_item=destination_item, to_item=source_item, quantity=qty, created_by=actor.id))

                source_expedition = source_item.expedition_item
                if source_expedition is None:
                    raise ApiError(error_codes.EXPEDITION_REMANAGEMENT_INVALID, "Item de origem nao possui disponibilidade oficial na Expedicao.", status_code=409)
                previous_source_status = source_expedition.status
                source_expedition.remanaged_quantity = quantity(source_expedition.remanaged_quantity + qty)
                source_expedition.separated_quantity = max(source_expedition.delivered_quantity, min(source_expedition.separated_quantity, source_expedition.available_quantity - source_expedition.remanaged_quantity))
                # Mesma correcao aplicada em apply_remanagement: "DISPONIVEL_PARCIAL"
                # nao existe em ck_expedition_items_status - com saldo restante o
                # item mantem o status atual, so vira REMANEJADO quando esgotado.
                source_expedition.status = "REMANEJADO" if source_ready_after <= 0 else previous_source_status
                _touch(source_expedition, actor)

                # Um item destino pode receber de mais de uma origem na mesma
                # operacao: a segunda origem processada precisa encontrar o
                # MESMO ExpeditionItem criado pela primeira, nunca duplicar.
                destination_expedition = destination_item.expedition_item
                if destination_expedition is None:
                    destination_expedition = ExpeditionItem(proposal_id=destination.id, proposal_item_id=destination_item.id, available_quantity=qty, origin="REMANEJAMENTO", status="EM_SEPARACAO", created_by=actor.id, updated_by=actor.id)
                    destination_expedition.proposal = destination
                    destination_expedition.proposal_item = destination_item
                    session.add(destination_expedition)
                    await session.flush()
                    destination_item.expedition_item = destination_expedition
                else:
                    destination_expedition.available_quantity = quantity(destination_expedition.available_quantity + qty)
                    destination_expedition.origin = "MISTO" if destination_expedition.origin != "REMANEJAMENTO" else destination_expedition.origin
                    if destination_expedition.status not in {"SEPARACAO_INICIADA", "SEPARADO", "ENTREGUE_PARCIAL"}:
                        destination_expedition.status = "EM_SEPARACAO"
                    _touch(destination_expedition, actor)

                transferred_by_destination_item[destination_item.id] = transferred_by_destination_item.get(destination_item.id, Decimal("0")) + qty

                event_metadata = {
                    "operation_id": payload.operation_id,
                    "remanagement_id": remanagement.id,
                    "code": remanagement.code,
                    "source_item_id": source_item.id,
                    "destination_item_id": destination_item.id,
                    "quantity": str(qty),
                    "reason": payload.reason,
                    "source_ready_before": str(source_balance.ready_available),
                    "source_ready_after": str(source_ready_after),
                    "destination_need_before": str(destination_balance.destination_need),
                    "destination_need_after": str(destination_balance.destination_need - qty),
                    "production_reallocated_quantity": str(qty),
                }
                await _record_expedition_event(session, source_proposal, "COMPENSATED_REMANAGEMENT_READY_SENT", actor, expedition_item=source_expedition, request_id=request_id, from_status=previous_source_status, to_status=source_expedition.status, metadata=event_metadata)
                await _record_expedition_event(session, destination, "COMPENSATED_REMANAGEMENT_READY_RECEIVED", actor, expedition_item=destination_expedition, request_id=request_id, to_status=destination_expedition.status, metadata=event_metadata)

            source_proposal.has_production_pending = True
            source_proposal.production_status = "ITEM_PENDENTE_FABRICACAO"
            source_proposal.flow_situation = "PENDENTE_POR_REMANEJAMENTO"
            _touch(source_proposal, actor)

        # Destino e recalculado UMA vez, com o total transferido somado de
        # TODAS as origens - nunca uma vez por origem (evitaria contar so a
        # ultima origem processada como se fosse o total).
        mapped_destination_pending = {
            item_id: max(fresh_balances[item_id].production_pending - transferred, Decimal("0"))
            for item_id, transferred in transferred_by_destination_item.items()
        }
        destination_has_production_pending = any(
            mapped_destination_pending.get(int(item.id), _loaded_item_balance(item).production_pending) > 0
            for item in _internal_items(destination)
        )
        destination.shipping_status = "EM_SEPARACAO"
        if not destination_has_production_pending:
            destination.production_status = "FINALIZADO"
            destination.has_production_pending = False
            destination.current_area = "EXPEDICAO"
            destination.current_status = "EM_SEPARACAO"
            destination.general_status = "EM_EXPEDICAO"
            destination.flow_situation = "NORMAL"
        else:
            destination.has_production_pending = True
            destination.flow_situation = "PARCIAL_COM_PENDENCIA"
        _touch(destination, actor)
        destination_after = {"area": destination.current_area, "status": destination.current_status, "production_status": destination.production_status, "shipping_status": destination.shipping_status}

        for remanagement in created_rows:
            source_proposal = preloaded[remanagement.source_proposal_id]
            source_after = {"area": source_proposal.current_area, "status": source_proposal.current_status, "production_status": source_proposal.production_status, "shipping_status": source_proposal.shipping_status}
            await _record_event(
                session, source_proposal, "COMPENSATED_REMANAGEMENT_APPLIED", actor, request_id=request_id,
                from_area=sources_before[source_proposal.id]["area"], from_status=sources_before[source_proposal.id]["status"],
                to_area=source_proposal.current_area, to_status=source_proposal.current_status,
                metadata={"operation_id": payload.operation_id, "remanagement_id": remanagement.id, "code": remanagement.code, "destination_proposal_id": destination.id, "reason": payload.reason, "state_before": sources_before[source_proposal.id], "state_after": source_after},
            )
            await _record_event(
                session, destination, "COMPENSATED_REMANAGEMENT_RECEIVED", actor, request_id=request_id,
                from_area=destination_before["area"], from_status=destination_before["status"],
                to_area=destination.current_area, to_status=destination.current_status,
                metadata={"operation_id": payload.operation_id, "remanagement_id": remanagement.id, "code": remanagement.code, "source_proposal_id": source_proposal.id, "reason": payload.reason, "state_before": destination_before, "state_after": destination_after},
            )

        await auth_repository.create_security_event(
            session, "COMPENSATED_REMANAGEMENT_APPLIED", actor_user_id=actor.id, request_id=request_id,
            details={"operation_id": payload.operation_id, "destination_proposal_id": destination.id, "source_proposal_ids": source_proposal_ids, "remanagement_ids": [row.id for row in created_rows]},
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing_rows = await _get_remanagement_batch_by_operation_id(session, payload.operation_id)
        if existing_rows:
            return _confirm_result_from_rows(payload.operation_id, existing_rows)
        raise
    except Exception:
        await session.rollback()
        raise

    final_rows = await _get_remanagement_batch_by_operation_id(session, payload.operation_id)
    return _confirm_result_from_rows(payload.operation_id, final_rows)


async def compatible_remanagement_items(session: AsyncSession, source_proposal_id: int, destination_proposal_id: int) -> list[RemanagementCompatibleItem]:
    if source_proposal_id == destination_proposal_id:
        return []
    source = await get_proposal(session, source_proposal_id)
    destination = await get_proposal(session, destination_proposal_id)
    _ensure_proposal_not_cancelled(source)
    _ensure_proposal_not_cancelled(destination)
    result = []
    for source_item in _active_items(source):
        source_balance = await _item_allocation_balance(session, source_item)
        if source_balance.ready_available <= 0:
            continue
        for destination_item in _active_items(destination):
            compatible, _ = items_are_compatible(source_item, destination_item)
            if not compatible or source_item.requires_galvanization == "SIM":
                continue
            destination_balance = await _item_allocation_balance(session, destination_item)
            maximum = max_remanageable(source_balance, destination_balance)
            if maximum <= 0:
                continue
            result.append(RemanagementCompatibleItem(source_item_id=source_item.id, destination_item_id=destination_item.id, source_item_number=source_item.item_number, destination_item_number=destination_item.item_number, product_code=source_item.product_code, description=source_item.description, unit=source_item.unit, source_item_version=source_item.version, destination_item_version=destination_item.version, source_ready_available=source_balance.ready_available, destination_need=destination_balance.destination_need, destination_reallocatable_production=destination_balance.reallocatable_production, max_remanageable=maximum, weight_snapshot=source_item.unit_weight))
    return result


async def remanagement_destination_items(session: AsyncSession, destination_proposal_id: int) -> list[RemanagementDestinationItem]:
    """Fase 2 do novo fluxo de Remanejamento: itens da proposta destino ja
    escolhida na Fase 1, com a mesma necessidade remanejavel usada por
    `compatible_remanagement_items`/`_evaluate_remanagement` - nenhuma formula
    nova, apenas `_item_allocation_balance` calculada sem exigir uma origem."""
    destination = await get_proposal(session, destination_proposal_id)
    _ensure_proposal_not_cancelled(destination)
    if not destination.active:
        raise ApiError(error_codes.EXPEDITION_REMANAGEMENT_INVALID, "A proposta destino nao esta mais ativa para remanejamento.", status_code=409)
    result = []
    for item in _active_items(destination):
        balance = await _item_allocation_balance(session, item)
        need = balance.destination_need
        code = (item.product_code or "").strip()
        block_reason = None
        if not code:
            block_reason = "Item sem codigo de produto para busca de remanejamento."
        elif need <= 0:
            block_reason = "Item sem necessidade pendente de remanejamento."
        result.append(RemanagementDestinationItem(
            item_id=item.id,
            item_version=item.version,
            item_number=item.item_number,
            product_code=item.product_code,
            description=item.description,
            unit=item.unit,
            total_quantity=item.quantity,
            already_attended=(balance.requested - need).quantize(Decimal("0.0001")),
            remanageable_need=need,
            selectable=block_reason is None,
            block_reason=block_reason,
        ))
    return result


def _normalized_product_code(value) -> str:
    return str(value or "").strip().upper()


async def _batch_item_allocation_balances(session: AsyncSession, items: list[ProposalItem]) -> dict[int, "ItemAllocationBalance"]:
    """Versao em lote de `_item_allocation_balance`: mesmas 3 agregacoes sobre
    `ProductionAllocationTransfer`, mas agrupadas por `item_id` em vez de uma
    consulta por item, para varrer muitos itens (Fase 3) sem N+1."""
    if not items:
        return {}
    item_ids = [item.id for item in items]
    production_out = {
        int(item_id): Decimal(str(total or "0"))
        for item_id, total in (await session.execute(
            select(ProductionAllocationTransfer.from_item_id, func.coalesce(func.sum(ProductionAllocationTransfer.quantity), 0))
            .where(ProductionAllocationTransfer.from_item_id.in_(item_ids))
            .group_by(ProductionAllocationTransfer.from_item_id)
        )).all()
    }
    production_in_pending = {
        int(item_id): Decimal(str(total or "0"))
        for item_id, total in (await session.execute(
            select(ProductionAllocationTransfer.to_item_id, func.coalesce(func.sum(ProductionAllocationTransfer.quantity - ProductionAllocationTransfer.completed_quantity), 0))
            .where(ProductionAllocationTransfer.to_item_id.in_(item_ids))
            .where(ProductionAllocationTransfer.status != "COMPLETED")
            .group_by(ProductionAllocationTransfer.to_item_id)
        )).all()
    }
    production_in_completed = {
        int(item_id): Decimal(str(total or "0"))
        for item_id, total in (await session.execute(
            select(ProductionAllocationTransfer.to_item_id, func.coalesce(func.sum(ProductionAllocationTransfer.completed_quantity), 0))
            .where(ProductionAllocationTransfer.to_item_id.in_(item_ids))
            .group_by(ProductionAllocationTransfer.to_item_id)
        )).all()
    }
    balances = {}
    for item in items:
        expedition = item.expedition_item
        balances[item.id] = calculate_item_balance(
            requested=item.quantity,
            produced=item.produced,
            produce_internally=item.produce_internally,
            expedition_available=expedition.available_quantity if expedition else 0,
            delivered=expedition.delivered_quantity if expedition else 0,
            remanaged_out=expedition.remanaged_quantity if expedition else 0,
            production_reallocated_out=production_out.get(item.id, 0),
            production_reallocated_in_pending=production_in_pending.get(item.id, 0),
            production_reallocated_in_completed=production_in_completed.get(item.id, 0),
        )
    return balances


async def find_remanagement_sources(session: AsyncSession, payload: RemanagementAvailabilityRequest) -> RemanagementAvailabilityResponse:
    """Fase 3 do novo fluxo de Remanejamento: para cada item que a Fase 2
    marcou como necessario no destino, descobre automaticamente quais outras
    propostas tem saldo pronto na Expedicao com o mesmo `product_code` -
    reutiliza `_item_allocation_balance`/`calculate_item_balance` (mesmo
    calculo de saldo do fluxo legado) e `items_are_compatible` (mesma regra
    de compatibilidade da gravacao real) em vez de inventar formula ou
    correspondencia por descricao. Somente leitura: nenhuma origem e
    escolhida, nenhum saldo e reservado."""
    destination = await get_proposal(session, payload.destination_proposal_id)
    _ensure_proposal_not_cancelled(destination)
    if not destination.active:
        raise ApiError(error_codes.EXPEDITION_REMANAGEMENT_INVALID, "A proposta destino nao esta mais ativa para remanejamento.", status_code=409)
    destination_items = {int(item.id): item for item in _active_items(destination)}

    requested_rows: list[tuple[ProposalItem, Decimal]] = []
    for requested in payload.items:
        destination_item = destination_items.get(requested.destination_item_id)
        if destination_item is None:
            raise ApiError(error_codes.EXPEDITION_REMANAGEMENT_INVALID, "Item nao pertence a proposta destino.", status_code=409)
        code = _normalized_product_code(destination_item.product_code)
        if not code:
            raise ApiError(error_codes.EXPEDITION_REMANAGEMENT_INVALID, f"Item {destination_item.item_number} nao possui codigo de produto para busca.", status_code=409)
        # Nunca confiar cegamente na quantidade que a Fase 2 enviou: revalida
        # contra a necessidade remanejavel atual (mesmo calculo da Fase 2).
        destination_balance = await _item_allocation_balance(session, destination_item)
        effective_quantity = min(quantity(requested.requested_quantity), destination_balance.destination_need)
        requested_rows.append((destination_item, effective_quantity))

    if await _sync_expedition_from_available_items(session):
        await session.commit()

    codes = sorted({_normalized_product_code(item.product_code) for item, _ in requested_rows})
    candidates_by_code: dict[str, list[ProposalItem]] = {code: [] for code in codes}
    balances: dict[int, "ItemAllocationBalance"] = {}
    candidate_stmt = (
        select(ProposalItem)
        .join(Proposal, ProposalItem.proposal_id == Proposal.id)
        .options(selectinload(ProposalItem.proposal))
        .where(func.upper(ProposalItem.product_code).in_(codes))
        .where(ProposalItem.proposal_id != payload.destination_proposal_id)
        .where(ProposalItem.active.is_(True))
        .where(Proposal.active.is_(True))
        .where(_proposal_operational_clause())
    )
    candidate_items = (await session.execute(candidate_stmt)).scalars().unique().all()
    balances = await _batch_item_allocation_balances(session, candidate_items)
    for item in candidate_items:
        # Mesma exclusao ja aplicada por `compatible_remanagement_items`: item
        # pendente de galvanizacao nao pode ser origem ate essa etapa ficar
        # rastreavel quantitativamente.
        if item.requires_galvanization == "SIM":
            continue
        balance = balances.get(item.id)
        if balance is None or balance.ready_available <= 0:
            continue
        candidates_by_code.setdefault(_normalized_product_code(item.product_code), []).append(item)

    result_items = []
    for destination_item, effective_quantity in requested_rows:
        code = _normalized_product_code(destination_item.product_code)
        matches = [
            candidate_item for candidate_item in candidates_by_code.get(code, [])
            if items_are_compatible(candidate_item, destination_item)[0]
        ]
        matches.sort(key=lambda candidate_item: balances[candidate_item.id].ready_available, reverse=True)
        candidates = [
            RemanagementSourceCandidate(
                source_proposal_id=candidate_item.proposal_id,
                source_proposal_number=candidate_item.proposal.proposal_number,
                source_item_id=candidate_item.id,
                source_item_version=candidate_item.version,
                client=candidate_item.proposal.customer_name,
                site=candidate_item.proposal.project_name,
                available_quantity=balances[candidate_item.id].ready_available,
                unit=candidate_item.unit,
                operational_status=candidate_item.proposal.shipping_status,
            )
            for candidate_item in matches
        ]
        total_available = sum((candidate.available_quantity for candidate in candidates), Decimal("0")).quantize(Decimal("0.0001"))
        if effective_quantity > 0 and total_available >= effective_quantity:
            coverage_status = "SUFICIENTE"
        elif total_available > 0:
            coverage_status = "PARCIAL"
        else:
            coverage_status = "SEM_DISPONIBILIDADE"
        result_items.append(RemanagementDestinationItemAvailability(
            destination_item_id=destination_item.id,
            product_code=destination_item.product_code,
            description=destination_item.description,
            unit=destination_item.unit,
            requested_quantity=effective_quantity,
            total_available=total_available,
            coverage_status=coverage_status,
            candidates=candidates,
        ))
    return RemanagementAvailabilityResponse(destination_proposal_id=destination.id, items=result_items)


def _compensation_plan_response(plan: CompensationPlan) -> RemanagementCompensationPlanResponse:
    return RemanagementCompensationPlanResponse(
        destination_proposal_id=plan.destination_proposal_id,
        products=[
            CompensationProductPlan(
                product_code=product.product_code,
                destination_item_id=product.destination_item_id,
                total_to_receive=product.total_to_receive,
                allocated_quantity=product.allocated_quantity,
                remaining_quantity=product.remaining_quantity,
                coverage=product.coverage,
                transfers=[
                    CompensationTransfer(
                        source_proposal_id=line.source_proposal_id,
                        source_item_id=line.source_item_id,
                        ready_quantity_to_destination=line.ready_quantity_to_destination,
                        obligation_quantity_to_source=line.obligation_quantity_to_source,
                    )
                    for line in product.transfers
                ],
            )
            for product in plan.products
        ],
        affected_proposals=plan.affected_proposals,
        total_ready_transferred=plan.total_ready_transferred,
        total_obligation_transferred=plan.total_obligation_transferred,
        future_mutations=FutureMutationPlanOut(
            expedition_ready_transfers=plan.future_mutations.expedition_ready_transfers,
            production_obligation_transfers=plan.future_mutations.production_obligation_transfers,
            status_recalculations=plan.future_mutations.status_recalculations,
            movement_records=plan.future_mutations.movement_records,
        ),
        warnings=plan.warnings,
        errors=[
            CompensationPlanError(code=error.code, message=error.message, destination_item_id=error.destination_item_id, source_item_id=error.source_item_id)
            for error in plan.errors
        ],
        valid=plan.valid,
    )


async def _load_compensation_snapshots(
    session: AsyncSession,
    payload: RemanagementCompensationRequest,
    *,
    preloaded_proposals: dict[int, Proposal] | None = None,
) -> tuple[Proposal, list[RequestedItem], list[Allocation], dict[int, ItemSnapshot], dict[int, ProposalItem]]:
    """Fonte unica de leitura do motor de compensacao (Fase 5), da revisao/
    simulacao (Fase 6) e da confirmacao transacional (Fase 7): carrega o
    destino, revalida cada item pedido contra a necessidade *atual* e cada
    origem alocada contra o saldo *atual* - `item_snapshots[...].available_for_transfer`
    e sempre um numero fresco lido agora, nunca uma fotografia antiga confiada
    as cegas. Fase 6 chama esta mesma funcao para "revalidar disponibilidades"
    (secao 16 do prompt da Fase 6) em vez de reimplementar a consulta.

    `preloaded_proposals`, usado pela Fase 7, permite passar propostas ja
    carregadas e travadas (`_locked_remanagement_participants`) para que a
    revalidacao dentro da transacao de confirmacao nunca faca uma leitura
    solta e destravada do destino/origens - destino e itens de origem vem
    exclusivamente do dicionario ja travado quando fornecido. O saldo
    (`_item_allocation_balance`/`_batch_item_allocation_balances`) continua
    sendo lido agora, na mesma sessao, pois nao faz parte do preload de
    propostas."""
    if preloaded_proposals is not None:
        destination = preloaded_proposals.get(payload.destination_proposal_id)
        if destination is None:
            raise ApiError(error_codes.PROPOSAL_NOT_FOUND, "Proposta destino nao encontrada.", status_code=404)
    else:
        destination = await get_proposal(session, payload.destination_proposal_id)
    _ensure_proposal_not_cancelled(destination)
    if not destination.active:
        raise ApiError(error_codes.EXPEDITION_REMANAGEMENT_INVALID, "A proposta destino nao esta mais ativa para remanejamento.", status_code=409)
    destination_items = {int(item.id): item for item in _active_items(destination)}

    requested_items: list[RequestedItem] = []
    item_snapshots: dict[int, ItemSnapshot] = {}
    items_by_id: dict[int, ProposalItem] = {}
    for requested in payload.items:
        destination_item = destination_items.get(requested.destination_item_id)
        if destination_item is None:
            raise ApiError(error_codes.EXPEDITION_REMANAGEMENT_INVALID, "Item nao pertence a proposta destino.", status_code=409)
        code = _normalized_product_code(destination_item.product_code)
        if not code:
            raise ApiError(error_codes.EXPEDITION_REMANAGEMENT_INVALID, f"Item {destination_item.item_number} nao possui codigo de produto para compensacao.", status_code=409)
        # Mesma revalidacao da Fase 3: nunca confiar cegamente na quantidade
        # que o cliente enviou, sempre clampar contra a necessidade atual.
        destination_balance = await _item_allocation_balance(session, destination_item)
        effective_quantity = min(quantity(requested.requested_quantity), destination_balance.destination_need)
        requested_items.append(RequestedItem(destination_item_id=destination_item.id, requested_quantity=effective_quantity))
        items_by_id[destination_item.id] = destination_item
        item_snapshots[destination_item.id] = ItemSnapshot(
            item_id=destination_item.id,
            proposal_id=destination.id,
            product_code=destination_item.product_code or "",
            unit=destination_item.unit,
            requires_galvanization=destination_item.requires_galvanization,
            produce_internally=destination_item.produce_internally,
            flow_defined=destination_item.flow_defined,
            available_for_transfer=destination_balance.destination_need,
        )

    source_item_ids = sorted({allocation.source_item_id for allocation in payload.allocations})
    if source_item_ids:
        if preloaded_proposals is not None:
            preloaded_items_by_id = {
                int(item.id): item
                for proposal in preloaded_proposals.values()
                for item in _active_items(proposal)
            }
            missing_ids = [item_id for item_id in source_item_ids if item_id not in preloaded_items_by_id]
            if missing_ids:
                raise ApiError(error_codes.EXPEDITION_REMANAGEMENT_INVALID, "Item de origem nao pertence a nenhuma proposta travada para esta confirmacao.", status_code=409)
            source_items = [preloaded_items_by_id[item_id] for item_id in source_item_ids]
        else:
            source_items = (
                (await session.execute(
                    select(ProposalItem)
                    .options(selectinload(ProposalItem.proposal))
                    .where(ProposalItem.id.in_(source_item_ids))
                    .where(ProposalItem.active.is_(True))
                ))
                .scalars()
                .unique()
                .all()
            )
        source_balances = await _batch_item_allocation_balances(session, source_items)
        for item in source_items:
            items_by_id[item.id] = item
            item_snapshots[item.id] = ItemSnapshot(
                item_id=item.id,
                proposal_id=item.proposal_id,
                product_code=item.product_code or "",
                unit=item.unit,
                requires_galvanization=item.requires_galvanization,
                produce_internally=item.produce_internally,
                flow_defined=item.flow_defined,
                available_for_transfer=source_balances[item.id].ready_available,
            )

    allocations = [
        Allocation(
            destination_item_id=allocation.destination_item_id,
            source_proposal_id=allocation.source_proposal_id,
            source_item_id=allocation.source_item_id,
            allocated_quantity=allocation.allocated_quantity,
        )
        for allocation in payload.allocations
    ]
    return destination, requested_items, allocations, item_snapshots, items_by_id


async def build_remanagement_compensation_plan(session: AsyncSession, payload: RemanagementCompensationRequest) -> RemanagementCompensationPlanResponse:
    """Fase 5 do novo fluxo de Remanejamento: recebe o plano de alocacao da
    Fase 4 (destination_item_id -> [source_proposal_id, source_item_id,
    allocated_quantity]) e devolve um plano de compensacao determinístico via
    o motor puro `build_compensation_plan` (`compensation.py`). So le dados
    (revalida destino/itens/saldos reais) - nao persiste nada."""
    destination, requested_items, allocations, item_snapshots, _items_by_id = await _load_compensation_snapshots(session, payload)
    plan = build_compensation_plan(
        destination_proposal_id=destination.id,
        requested_items=requested_items,
        allocations=allocations,
        item_snapshots=item_snapshots,
    )
    return _compensation_plan_response(plan)


async def simulate_remanagement_review(session: AsyncSession, payload: RemanagementReviewRequest) -> RemanagementReviewResult:
    """Fase 6 do novo fluxo de Remanejamento: revisao/simulacao final antes da
    confirmacao. Reusa a MESMA leitura de saldo da Fase 5
    (`_load_compensation_snapshots`, que ja consulta o saldo *atual* de cada
    origem/destino - isso e a revalidacao pedida na secao 16) e o MESMO motor
    de compensacao (`build_compensation_plan`); esta funcao apenas adiciona o
    comparativo antes/depois e a validacao do motivo. Nenhuma escrita."""
    destination, requested_items, allocations, item_snapshots, _items_by_id = await _load_compensation_snapshots(
        session,
        RemanagementCompensationRequest(destination_proposal_id=payload.destination_proposal_id, items=payload.items, allocations=payload.allocations),
    )
    plan = build_compensation_plan(
        destination_proposal_id=destination.id,
        requested_items=requested_items,
        allocations=allocations,
        item_snapshots=item_snapshots,
    )

    reason = (payload.reason or "").strip()
    errors = list(plan.errors)
    if not reason:
        errors.append(CompensationError(code="REASON_REQUIRED", message="Informe o motivo do remanejamento."))

    products_by_item = {product.destination_item_id: product for product in plan.products}
    review_items = []
    complete = partial = not_allocated = invalid = 0
    source_proposal_ids: set[int] = set()
    source_item_ids: set[int] = set()
    aggregate_units: dict[str, str] = {}  # chave normalizada (upper) -> grafia original para exibicao
    aggregate_total = Decimal("0")

    for requested in requested_items:
        product = products_by_item.get(requested.destination_item_id)
        allocated = product.allocated_quantity if product else Decimal("0")
        remaining = max(requested.requested_quantity - allocated, Decimal("0"))
        has_error = any(error.destination_item_id == requested.destination_item_id for error in plan.errors)
        if has_error:
            status = "INVALIDO"
            invalid += 1
        elif allocated <= 0:
            status = "NAO_ALOCADO"
            not_allocated += 1
        elif allocated >= requested.requested_quantity:
            status = "COMPLETO"
            complete += 1
        else:
            status = "PARCIAL"
            partial += 1

        sources = []
        for line in (product.transfers if product else []):
            source_proposal_ids.add(line.source_proposal_id)
            source_item_ids.add(line.source_item_id)
            source_snapshot = item_snapshots.get(line.source_item_id)
            before = source_snapshot.available_for_transfer if source_snapshot else Decimal("0")
            after = max(before - line.ready_quantity_to_destination, Decimal("0"))
            sources.append(RemanagementReviewSource(
                source_proposal_id=line.source_proposal_id,
                source_item_id=line.source_item_id,
                ready_transfer=line.ready_quantity_to_destination,
                production_compensation=line.obligation_quantity_to_source,
                source_before=before,
                source_after_simulated=after,
            ))

        destination_snapshot = item_snapshots.get(requested.destination_item_id)
        unit = ((destination_snapshot.unit if destination_snapshot else None) or "").strip()
        aggregate_units.setdefault(unit.upper(), unit)
        aggregate_total += allocated
        review_items.append(RemanagementReviewItem(
            destination_item_id=requested.destination_item_id,
            product_code=destination_snapshot.product_code if destination_snapshot else "",
            requested=requested.requested_quantity,
            allocated=allocated,
            remaining=remaining,
            status=status,
            sources=sources,
        ))

    total_quantity = aggregate_total.quantize(Decimal("0.0001")) if len(aggregate_units) == 1 else None
    total_unit = next(iter(aggregate_units.values())) if len(aggregate_units) == 1 else None
    summary = RemanagementReviewSummary(
        product_count=len(review_items),
        source_proposal_count=len(source_proposal_ids),
        source_item_count=len(source_item_ids),
        total_quantity=total_quantity,
        total_unit=total_unit,
        complete_items=complete,
        partial_items=partial,
        not_allocated_items=not_allocated,
        invalid_items=invalid,
    )
    valid = not errors and complete + partial > 0
    return RemanagementReviewResult(
        destination_proposal_id=destination.id,
        valid=valid,
        warnings=list(plan.warnings),
        errors=[CompensationPlanError(code=error.code, message=error.message, destination_item_id=error.destination_item_id, source_item_id=error.source_item_id) for error in errors],
        summary=summary,
        items=review_items,
    )


async def list_remanagements(session: AsyncSession, *, proposal_id: int | None, limit: int, offset: int) -> PaginatedRemanagementResponse:
    stmt = select(ProposalRemanagement).options(selectinload(ProposalRemanagement.items).selectinload(ProposalRemanagementItem.production_transfer))
    if proposal_id is not None:
        stmt = stmt.where(or_(ProposalRemanagement.source_proposal_id == proposal_id, ProposalRemanagement.destination_proposal_id == proposal_id))
    total = int((await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
    rows = (await session.execute(stmt.order_by(ProposalRemanagement.created_at.desc(), ProposalRemanagement.id.desc()).limit(limit).offset(offset))).scalars().unique().all()
    return PaginatedRemanagementResponse(items=[_remanagement_summary(row) for row in rows], total=total, limit=limit, offset=offset)


async def deliver_proposal_by_remanagement(session: AsyncSession, proposal_id: int, payload: ExpeditionRemanagementDeliveryRequest, actor: User, *, request_id: str | None) -> RemanagementSummary:
    if proposal_id != payload.destination_proposal_id:
        raise ApiError(error_codes.EXPEDITION_REMANAGEMENT_INVALID, "Destino da rota difere do destino informado.", status_code=409)
    return await apply_remanagement(session, payload, actor, request_id=request_id)


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
    batch = FiscalBatchRequest(proposals=[{
        "fiscal_record_id": fiscal_record_id,
        "version": payload.version,
        "selection_type": "TOTAL",
        "invoice_number": payload.invoice_number,
        "series": payload.series,
        "issued_at": payload.issued_at,
        "source": payload.source,
        "observation": payload.observation,
        "items": [item.model_dump() for item in payload.items] if payload.items is not None else None,
    }])
    await register_fiscal_batch(session, batch, actor, request_id=request_id)
    session.expire_all()
    return await get_fiscal_detail(session, fiscal_record_id)


async def register_fiscal_batch(session: AsyncSession, payload: FiscalBatchRequest, actor: User, *, request_id: str | None) -> FiscalBatchResponse:
    """Shared atomic motor used by individual and batch fiscal registration."""
    operation_id = (payload.operation_id or request_id or f"fiscal-{datetime.now(UTC).timestamp()}").strip()
    record_ids = [int(row.fiscal_record_id) for row in payload.proposals]
    if len(record_ids) != len(set(record_ids)):
        raise ApiError(error_codes.FISCAL_ITEM_INVALID, "A mesma proposta nao pode aparecer duas vezes no lote.", status_code=409)
    document_keys = [(str(row.invoice_number).strip(), (row.series or "").strip() or None) for row in payload.proposals]
    if len(document_keys) != len(set(document_keys)):
        raise ApiError(error_codes.FISCAL_INVOICE_DUPLICATED, "Existem NFs duplicadas dentro do mesmo lote.", status_code=409)
    try:
        previous_invoices = (await session.execute(
            select(FiscalInvoice).where(FiscalInvoice.operation_id == operation_id).where(FiscalInvoice.active.is_(True))
        )).scalars().all()
        if previous_invoices:
            if {int(invoice.fiscal_record_id) for invoice in previous_invoices} != set(record_ids):
                raise ApiError(error_codes.FISCAL_ITEM_INVALID, "O operation_id ja foi usado por outro lote.", status_code=409)
            replay_results = []
            for invoice in previous_invoices:
                record = await _get_fiscal_record(session, int(invoice.fiscal_record_id))
                replay_results.append(FiscalBatchProposalResult(fiscal_record_id=record.id, emission_id=invoice.id, invoice_number=invoice.invoice_number, series=invoice.series, final_status=record.status_fiscal))
            return FiscalBatchResponse(operation_id=operation_id, status="confirmed", proposals=replay_results)
        records = []
        for record_id in record_ids:
            record = await _get_fiscal_record(session, record_id, for_update=True)
            _ensure_proposal_not_cancelled(record.proposal)
            records.append(record)
        # All validations complete before creating any invoice. PostgreSQL row
        # locks protect the saldo/version check from a concurrent commit.
        selections = []
        for record, request in zip(records, payload.proposals):
            await _ensure_fiscal_items_for_record(session, record)
            _ensure_fiscal_version(record, request.version)
            if record.status_fiscal == "NOTA_FISCAL_EMITIDA":
                raise ApiError(error_codes.FISCAL_INVALID_STATE, f"A proposta fiscal {record.id} ja esta concluida.", status_code=409)
            duplicate = (await session.execute(
                select(FiscalInvoice)
                .where(FiscalInvoice.invoice_number == request.invoice_number)
                .where(FiscalInvoice.series.is_(None) if request.series is None else FiscalInvoice.series == request.series)
                .where(FiscalInvoice.active.is_(True))
                .where(FiscalInvoice.status != "CANCELADA")
            )).scalars().first()
            if duplicate is not None:
                raise ApiError(error_codes.FISCAL_INVOICE_DUPLICATED, f"A NF {request.invoice_number} ja existe para esta serie.", status_code=409)
            selected = _selected_fiscal_items(record, [FiscalEmissionItemInput(**item.model_dump()) for item in request.items] if request.items is not None else None)
            if not selected and record.items:
                raise ApiError(error_codes.FISCAL_ITEM_INVALID, "Selecione pelo menos um item fiscal.", status_code=409)
            selections.append(selected)

        results = []
        for record, request, selected in zip(records, payload.proposals, selections):
            now = datetime.now(UTC)
            previous = record.status_fiscal
            invoice = FiscalInvoice(
                fiscal_record_id=record.id,
                proposal_id=record.proposal_id,
                operation_id=operation_id,
                invoice_number=request.invoice_number,
                series=request.series or None,
                issued_at=request.issued_at or now,
                source=request.source,
                observation=request.observation,
                created_by=actor.id,
                updated_by=actor.id,
            )
            session.add(invoice)
            await session.flush()
            for item, qty, weight in selected:
                item.billed_quantity = (item.billed_quantity + qty).quantize(Decimal("0.0001"))
                if weight is not None:
                    item.billed_weight = (item.billed_weight + weight).quantize(Decimal("0.0001"))
                _recalculate_fiscal_item_status(item)
                _touch(item, actor)
                session.add(FiscalInvoiceItem(fiscal_invoice_id=invoice.id, fiscal_item_id=item.id, proposal_id=record.proposal_id, proposal_item_id=item.proposal_item_id, quantity=qty, weight=weight, created_by=actor.id))
            if not record.items:
                record.status_fiscal = "NOTA_FISCAL_EMITIDA"
                record.fiscal_situation = "NF_EMITIDA"
            else:
                _recalculate_fiscal_record(record)
            _assert_fiscal_record_invariants(record)
            invoice.emission_type = "TOTAL" if record.status_fiscal == "NOTA_FISCAL_EMITIDA" else "PARCIAL"
            record.last_emission_at = now
            record.observation = request.observation
            _touch(record, actor)
            _touch(invoice, actor)
            await _record_fiscal_event(session, record, "FISCAL_INVOICE_REGISTERED", actor, fiscal_invoice=invoice, request_id=request_id, from_status=previous, to_status=record.status_fiscal, metadata={"invoice_number": invoice.invoice_number, "operation_id": operation_id})
            results.append(FiscalBatchProposalResult(fiscal_record_id=record.id, emission_id=invoice.id, invoice_number=invoice.invoice_number, series=invoice.series, final_status=record.status_fiscal))
        result_ids = [int(result.emission_id) for result in results]
        for record in records:
            await _record_fiscal_event(
                session,
                record,
                "FISCAL_BATCH_CONFIRMED",
                actor,
                request_id=request_id,
                from_status=None,
                to_status=record.status_fiscal,
                metadata={"operation_id": operation_id, "emission_ids": result_ids, "proposal_ids": record_ids},
            )
        await session.commit()
        return FiscalBatchResponse(operation_id=operation_id, status="confirmed", proposals=results)
    except Exception:
        await session.rollback()
        raise


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
    _ensure_proposal_not_cancelled(record.proposal)
    _ensure_fiscal_version(record, payload.version)
    previous = record.status_fiscal
    item = next(row for row in record.items if row.id == invoice_item.fiscal_item_id)
    item.billed_quantity = max(Decimal("0"), (item.billed_quantity - invoice_item.quantity)).quantize(Decimal("0.0001"))
    if invoice_item.weight is not None:
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
    _ensure_proposal_not_cancelled(record.proposal)
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
            .join(FiscalRecord.proposal)
            .where(_proposal_operational_clause())
            .where(or_(Proposal.parent_proposal_id.is_(None), Proposal.current_area == "EXPEDICAO"))
        ))
        .scalars()
        .unique()
        .all()
    )


async def _get_fiscal_record(session: AsyncSession, fiscal_record_id: int, *, for_update: bool = False) -> FiscalRecord:
    statement = select(FiscalRecord)
    if for_update:
        statement = statement.with_for_update()
    record = (
        (await session.execute(
            statement
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
            .where(_proposal_operational_clause())
        ))
        .scalars()
        .unique()
        .all()
    )
    changed = False
    today = datetime.now(UTC).date()
    for proposal in proposals:
        # Filhas somente entram no Fiscal depois de chegarem a Expedicao. A
        # mae continua sendo a referencia fiscal principal.
        if proposal.parent_proposal_id is not None and proposal.current_area != "EXPEDICAO":
            continue
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


def _selected_fiscal_items(record: FiscalRecord, payload_items) -> list[tuple[FiscalItem, Decimal, Decimal | None]]:
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
        pending_weight = (
            (item.total_weight - item.billed_weight).quantize(Decimal("0.0001"))
            if item.total_weight is not None
            else None
        )
        if pending_qty <= Decimal("0"):
            raise ApiError(error_codes.FISCAL_ITEM_INVALID, "O item fiscal nao possui saldo pendente.", status_code=409)
        if row.quantity is not None and row.quantity <= Decimal("0"):
            raise ApiError(error_codes.FISCAL_ITEM_INVALID, "A quantidade fiscal deve ser maior que zero.", status_code=409)
        qty = (row.quantity or pending_qty).quantize(Decimal("0.0001"))
        weight = normalize_known_weight(row.weight if row.weight is not None else pending_weight)
        if qty <= Decimal("0"):
            raise ApiError(error_codes.FISCAL_ITEM_INVALID, "A quantidade fiscal deve ser maior que zero.", status_code=409)
        if qty > pending_qty:
            raise ApiError(error_codes.FISCAL_QUANTITY_EXCEEDED, "Quantidade fiscal excede o saldo pendente.", status_code=409)
        prepared.append((item, qty, weight))
    return prepared


def _ensure_fiscal_version(record: FiscalRecord, expected: int) -> None:
    if record.version != expected:
        raise ApiError(error_codes.FISCAL_VERSION_CONFLICT, "O controle fiscal foi alterado por outro usuario. Recarregue os dados.", status_code=409)


def _recalculate_fiscal_item_status(item: FiscalItem) -> None:
    qty_done = item.billed_quantity >= item.total_quantity
    if qty_done:
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


def _assert_fiscal_record_invariants(record: FiscalRecord) -> None:
    """Fail closed if a fiscal write would leave an impossible state."""
    active = [item for item in record.items if item.active]
    for item in active:
        if item.billed_quantity < Decimal("0") or item.billed_quantity > item.total_quantity:
            raise ApiError(error_codes.FISCAL_ITEM_INVALID, "O saldo fiscal calculado ficou inconsistente.", status_code=409)
        if item.billed_weight < Decimal("0"):
            raise ApiError(error_codes.FISCAL_ITEM_INVALID, "O peso fiscal calculado ficou inconsistente.", status_code=409)
        if item.status == "FATURADO" and item.billed_quantity < item.total_quantity:
            raise ApiError(error_codes.FISCAL_ITEM_INVALID, "O status fiscal do item ficou inconsistente.", status_code=409)
    has_emitted = any(item.billed_quantity > Decimal("0") for item in active)
    has_pending = any(item.billed_quantity < item.total_quantity for item in active)
    expected = "NOTA_FISCAL_EMITIDA" if active and not has_pending else "NOTA_FISCAL_PARCIAL" if has_emitted else "FALTA_EMITIR_NOTA_FISCAL"
    if active and record.status_fiscal != expected:
        raise ApiError(error_codes.FISCAL_ITEM_INVALID, "O status fiscal da proposta ficou inconsistente.", status_code=409)


def _fiscal_situation(record: FiscalRecord) -> str:
    if record.fiscal_situation == "NF_RETIRADA_CLIENTE":
        return "NF_RETIRADA_CLIENTE"
    if record.status_fiscal == "NOTA_FISCAL_EMITIDA":
        return "NF_EMITIDA"
    if record.status_fiscal == "NOTA_FISCAL_PARCIAL":
        return "NF_PARCIAL"
    if record.proposal.shipping_status == "ENTREGUE":
        return "PENDENCIA_FISCAL_CRITICA"
    if record.proposal.shipping_status in {"EM_SEPARACAO", "AGUARDANDO_SEPARACAO_PARCIAL", "SEPARACAO_INICIADA", "SEPARADO_COM_PENDENCIA", "SEPARADO", "ENTREGUE_PARCIAL"}:
        return "DISPONIVEL_PARA_EMISSAO"
    return "CP_EM_PROCESSAMENTO"


def _fiscal_sort_key(record: FiscalRecord) -> int:
    order = {"PENDENCIA_FISCAL_CRITICA": 0, "DISPONIVEL_PARA_EMISSAO": 1, "NF_PARCIAL": 2, "CP_EM_PROCESSAMENTO": 3, "NF_EMITIDA": 4, "NF_RETIRADA_CLIENTE": 5}
    return order.get(_fiscal_situation(record), 99)


def _fiscal_older_than_7_days(record: FiscalRecord) -> bool:
    return bool(record.status_fiscal != "NOTA_FISCAL_EMITIDA" and record.last_emission_at is None and (datetime.now(UTC).date() - record.entry_date).days > 7)


def _fiscal_pending_weight(record: FiscalRecord) -> Decimal:
    return sum(
        ((item.total_weight - item.billed_weight) for item in record.items if item.active and item.total_weight is not None),
        Decimal("0"),
    ).quantize(Decimal("0.0001"))


def _fiscal_record_summary(record: FiscalRecord) -> FiscalRecordSummary:
    active_items = [item for item in record.items if item.active]
    pending = [item for item in active_items if item.status != "FATURADO"]
    billed = [item for item in active_items if item.status == "FATURADO"]
    coverage = calculate_weight_coverage(item.total_weight for item in active_items)
    total_weight = coverage.known_weight
    billed_weight = sum((item.billed_weight for item in active_items), Decimal("0")).quantize(Decimal("0.0001"))
    pending_weight = (total_weight - billed_weight).quantize(Decimal("0.0001"))
    situation = _fiscal_situation(record)
    return FiscalRecordSummary(
        id=record.id,
        proposal_id=record.proposal_id,
        parent_proposal_id=record.proposal.parent_proposal_id,
        partial_number=record.proposal.partial_number,
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
        weight_known_items=coverage.known_items,
        weight_total_items=coverage.total_items,
        weight_complete=coverage.complete,
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
        pending_weight=(item.total_weight - item.billed_weight).quantize(Decimal("0.0001")) if item.total_weight is not None else None,
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
        weight=sum(((item.weight or Decimal("0")) for item in active_items), Decimal("0")).quantize(Decimal("0.0001")),
        items=items,
    )


def _fiscal_actions(record: FiscalRecord):
    actions = []
    if _proposal_is_cancelled(record.proposal):
        return [{"id": "VIEW_FISCAL_DETAIL", "label": "Ver detalhes", "enabled": True}]
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
    _ensure_proposal_not_cancelled(proposal)
    return proposal


async def _merge_equal_status_partial_children(
    session: AsyncSession,
    parent_id: int,
    actor: User,
    *,
    request_id: str | None,
) -> None:
    """Une filhas equivalentes e registra a união sem apagar rastreabilidade.

    O grupo é separado por área, status e conjunto de cargas. Assim, filhas
    com o mesmo status, mas em cargas diferentes, continuam independentes.
    """
    children = (
        await session.execute(
            select(Proposal)
            .options(
                selectinload(Proposal.items),
                selectinload(Proposal.galvanization_load_items),
                selectinload(Proposal.parent_proposal),
            )
            .where(Proposal.parent_proposal_id == parent_id)
            .where(Proposal.active.is_(True))
            .where(Proposal.is_cancelled.is_(False))
            .order_by(Proposal.partial_number, Proposal.id)
        )
    ).scalars().unique().all()
    groups: dict[tuple, list[Proposal]] = {}
    for child in children:
        load_ids = tuple(sorted({int(row.load_id) for row in child.galvanization_load_items if row.active}))
        key = (child.current_area, child.current_status, load_ids)
        groups.setdefault(key, []).append(child)
    for key, members in groups.items():
        if len(members) < 2:
            continue
        survivor = members[0]
        merged_ids: list[int] = []
        for merged in members[1:]:
            for item in list(merged.items):
                item.proposal = survivor
                item.proposal_id = survivor.id
                for load_item in item.galvanization_load_items:
                    load_item.proposal = survivor
                    load_item.proposal_id = survivor.id
                if item.expedition_item is not None:
                    item.expedition_item.proposal = survivor
                    item.expedition_item.proposal_id = survivor.id
            merged.active = False
            merged_ids.append(int(merged.id))
            _touch(merged, actor)
            await _record_event(
                session,
                merged,
                "PROPOSAL_PARTIAL_CHILD_MERGED",
                actor,
                request_id=request_id,
                from_area=merged.current_area,
                from_status=merged.current_status,
                to_area=survivor.current_area,
                to_status=survivor.current_status,
                metadata={"survivor_proposal_id": survivor.id, "survivor_proposal_number": survivor.proposal_number},
            )
        _touch(survivor, actor)
        await _record_event(
            session,
            survivor,
            "PROPOSAL_PARTIAL_CHILD_GROUPED",
            actor,
            request_id=request_id,
            from_area=survivor.current_area,
            from_status=survivor.current_status,
            to_area=survivor.current_area,
            to_status=survivor.current_status,
            metadata={"merged_child_ids": merged_ids, "group_key": [key[0], key[1], list(key[2])]},
        )
        await _record_event(
            session,
            survivor.parent_proposal,
            "PROPOSAL_PARTIAL_CHILD_GROUPED",
            actor,
            request_id=request_id,
            metadata={"survivor_proposal_id": survivor.id, "merged_child_ids": merged_ids},
        )


async def _reborn_parent_when_children_converge(
    session: AsyncSession,
    child: Proposal,
    actor: User,
    *,
    request_id: str | None,
) -> Proposal | None:
    """Restaura a mãe quando todo o conjunto filho converge na expedição."""
    if child.parent_proposal_id is None:
        return None
    parent = (
        await session.execute(
            select(Proposal)
            .options(
                selectinload(Proposal.items),
                selectinload(Proposal.partial_children).selectinload(Proposal.items),
                selectinload(Proposal.partial_children).selectinload(Proposal.expedition_items),
            )
            .where(Proposal.id == child.parent_proposal_id)
        )
    ).scalars().unique().first()
    if parent is None:
        return None
    active_children = [row for row in parent.partial_children if row.active and not row.is_cancelled]
    if not active_children or any(row.current_area != "EXPEDICAO" for row in active_children):
        return None
    statuses = {row.current_status for row in active_children}
    if len(statuses) != 1:
        return None
    for row in active_children:
        for item in list(row.items):
            item.proposal = parent
            item.proposal_id = parent.id
            if item.expedition_item is not None:
                item.expedition_item.proposal = parent
                item.expedition_item.proposal_id = parent.id
        row.active = False
        _touch(row, actor)
        await _record_event(
            session,
            row,
            "PARENT_PROPOSAL_REBORN",
            actor,
            request_id=request_id,
            from_area=row.current_area,
            from_status=row.current_status,
            to_area="EXPEDICAO",
            to_status=next(iter(statuses)),
            metadata={"parent_proposal_id": parent.id, "parent_proposal_number": parent.proposal_number},
        )
    parent.is_partial = False
    parent.current_area = "EXPEDICAO"
    parent.current_status = next(iter(statuses))
    parent.general_status = "EM_EXPEDICAO"
    parent.shipping_status = next(iter(statuses))
    parent.flow_situation = "NORMAL"
    parent.has_production_pending = False
    _touch(parent, actor)
    await _record_event(
        session,
        parent,
        "PARENT_PROPOSAL_REBORN",
        actor,
        request_id=request_id,
        from_area="CONTROLE_GERAL",
        from_status="EM_PRODUCAO",
        to_area=parent.current_area,
        to_status=parent.current_status,
        metadata={"child_ids": [int(row.id) for row in active_children]},
    )
    return parent


async def _sync_expedition_from_available_items(session: AsyncSession) -> bool:
    proposals = (
        (await session.execute(
            select(Proposal)
            .options(
                selectinload(Proposal.items),
                selectinload(Proposal.expedition_items).selectinload(ExpeditionItem.proposal_item),
            )
            .where(Proposal.active.is_(True))
            .where(_proposal_operational_clause())
        ))
        .scalars()
        .unique()
        .all()
    )
    changed = False
    changed_proposals: list[Proposal] = []
    for proposal in proposals:
        proposal_changed = await _ensure_expedition_items_for_proposal(session, proposal)
        changed = proposal_changed or changed
        if proposal_changed:
            changed_proposals.append(proposal)
    for proposal in changed_proposals:
        _recalculate_expedition_proposal_state(proposal, proposal.updated_by)
    await session.flush()
    return changed


async def _ensure_expedition_items_for_proposal(session: AsyncSession, proposal: Proposal) -> bool:
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
    return changed


async def _expedition_available_source(session: AsyncSession, item: ProposalItem) -> tuple[Decimal, str]:
    if not item.active or item.delivered or not item.flow_defined:
        return Decimal("0"), "PRODUCAO"
    production_out = Decimal(str((await session.execute(
        select(func.coalesce(func.sum(ProductionAllocationTransfer.quantity), 0))
        .where(ProductionAllocationTransfer.from_item_id == item.id)
    )).scalar_one() or "0"))
    production_in_completed = Decimal(str((await session.execute(
        select(func.coalesce(func.sum(ProductionAllocationTransfer.completed_quantity), 0))
        .where(ProductionAllocationTransfer.to_item_id == item.id)
    )).scalar_one() or "0"))
    ready_received_by_remanagement = Decimal(str((await session.execute(
        select(func.coalesce(func.sum(ProposalRemanagementItem.quantity), 0))
        .where(ProposalRemanagementItem.destination_item_id == item.id)
    )).scalar_one() or "0"))
    if not item.produced and production_in_completed <= 0 and ready_received_by_remanagement <= 0:
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
        native_available = max(Decimal("0"), item.quantity - production_out) if item.produced else Decimal("0")
        available = (native_available + production_in_completed + ready_received_by_remanagement).quantize(Decimal("0.0001"))
        has_reallocation = production_in_completed > 0 or ready_received_by_remanagement > 0
        origin = "REMANEJAMENTO" if native_available <= 0 and has_reallocation else ("MISTO" if has_reallocation else "PRODUCAO")
        return available, origin
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
        "SEPARADO_COM_PENDENCIA": 2,
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
        parent_proposal_id=proposal.parent_proposal_id,
        partial_number=proposal.partial_number,
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
        unit_weight=normalize_known_weight(item.proposal_item.unit_weight),
        total_weight=calculate_known_weight(item.available_quantity, item.proposal_item.unit_weight),
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
    logger.debug(
        "Itens disponiveis na Expedicao para proposal_id=%r: expedition_item_id=%r proposal_item_id=%r",
        proposal.id, sorted(by_exp), sorted(by_proposal_item),
    )
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
        logger.debug(
            "Validando item da entrega: proposal_id=%r expedition_item_id=%r proposal_item_id=%r encontrado=%s status=%r saldo_separado=%r",
            proposal.id, row.expedition_item_id, row.proposal_item_id, item is not None,
            getattr(item, "status", None), (item.separated_quantity - item.delivered_quantity) if item is not None else None,
        )
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


def _recalculate_expedition_proposal_state(proposal: Proposal, actor: User | int | None) -> None:
    _ensure_proposal_not_cancelled(proposal)
    items = _all_expedition_items(proposal)
    relevant = [item for item in items if item.available_quantity > Decimal("0")]
    if not relevant:
        return
    remaining = [item for item in relevant if item.delivered_quantity + item.remanaged_quantity < item.available_quantity]
    separated_open = [item for item in remaining if item.separated_quantity > item.delivered_quantity]
    any_delivered = any(item.delivered_quantity > Decimal("0") for item in relevant)
    any_separated = any(item.separated_quantity > Decimal("0") for item in relevant)
    all_proposal_items_delivered = all(item.delivered for item in _active_items(proposal))
    # Uma proposta mista (itens de producao real "SIM" pendentes + itens
    # "NAO" de pronta entrega ja liberados para Expedicao) nao pode ter sua
    # current_area arrancada da Producao so porque a sincronizacao passiva
    # de Expedicao criou/atualizou ExpeditionItem para os itens "NAO". A
    # producao interna ainda pendente continua vivendo na mesma proposal_id.
    keep_in_production = proposal.current_area == "PRODUCAO" and any(
        not item.produced for item in _internal_items(proposal)
    )
    if not remaining and all_proposal_items_delivered and not proposal.has_production_pending:
        if not keep_in_production:
            proposal.current_area = "FINALIZADO"
        proposal.current_status = "ENTREGUE"
        proposal.general_status = "ENTREGUE"
        proposal.shipping_status = "ENTREGUE"
        proposal.is_completed = True
        proposal.flow_situation = "NORMAL"
    elif any_delivered:
        if not keep_in_production:
            proposal.current_area = "EXPEDICAO"
        proposal.current_status = "ENTREGUE_PARCIAL"
        proposal.general_status = "EM_EXPEDICAO"
        proposal.shipping_status = "ENTREGUE_PARCIAL"
        proposal.is_completed = False
        proposal.flow_situation = "PARCIAL_COM_PENDENCIA"
    elif remaining and len(separated_open) == len(remaining):
        if not keep_in_production:
            proposal.current_area = "EXPEDICAO"
        proposal.current_status = "SEPARADO"
        proposal.general_status = "EM_EXPEDICAO"
        proposal.shipping_status = "SEPARADO"
        proposal.is_completed = False
    elif proposal.shipping_status == "AGUARDANDO_SEPARACAO_PARCIAL" and any_separated:
        if not keep_in_production:
            proposal.current_area = "EXPEDICAO"
        proposal.current_status = "SEPARADO_COM_PENDENCIA"
        proposal.general_status = "EM_EXPEDICAO"
        proposal.shipping_status = "SEPARADO_COM_PENDENCIA"
        proposal.is_completed = False
    elif any_separated:
        if not keep_in_production:
            proposal.current_area = "EXPEDICAO"
        proposal.current_status = "SEPARACAO_INICIADA"
        proposal.general_status = "EM_EXPEDICAO"
        proposal.shipping_status = "SEPARACAO_INICIADA"
        proposal.is_completed = False
    else:
        if not keep_in_production:
            proposal.current_area = "EXPEDICAO"
        proposal.current_status = "EM_SEPARACAO"
        proposal.general_status = "EM_EXPEDICAO"
        proposal.shipping_status = "EM_SEPARACAO"
        proposal.is_completed = False
    if actor is not None and hasattr(actor, "id"):
        _touch(proposal, actor)
    else:
        proposal.updated_at = datetime.now(UTC)


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
    proposal = (
        await session.execute(
            select(Proposal)
            .options(
                selectinload(Proposal.items),
                selectinload(Proposal.partial_children).selectinload(Proposal.items),
            )
            .where(Proposal.id == proposal_id)
        )
    ).scalars().unique().first()
    if proposal is None:
        raise ApiError(error_codes.PROPOSAL_NOT_FOUND, "Proposta nao encontrada.", status_code=404)
    return proposal


async def _get_administrative_proposal(
    session: AsyncSession,
    proposal_id: int,
    *,
    for_update: bool = False,
) -> Proposal:
    """Carrega todos os fatos usados pela correcao e, ao aplicar, bloqueia a proposta."""

    stmt = (
        select(Proposal)
        .options(
            selectinload(Proposal.events),
            selectinload(Proposal.items).selectinload(ProposalItem.expedition_item),
            selectinload(Proposal.items).selectinload(ProposalItem.production_allocations_sent),
            selectinload(Proposal.items).selectinload(ProposalItem.production_allocations_received),
            selectinload(Proposal.galvanization_load_items).selectinload(GalvanizationLoadItem.load),
            selectinload(Proposal.expedition_items),
            selectinload(Proposal.fiscal_record).selectinload(FiscalRecord.items),
            selectinload(Proposal.fiscal_record).selectinload(FiscalRecord.invoices),
            selectinload(Proposal.partial_children).selectinload(Proposal.events),
            selectinload(Proposal.partial_children).selectinload(Proposal.items).selectinload(ProposalItem.expedition_item),
            selectinload(Proposal.partial_children).selectinload(Proposal.items).selectinload(ProposalItem.production_allocations_sent),
            selectinload(Proposal.partial_children).selectinload(Proposal.items).selectinload(ProposalItem.production_allocations_received),
            selectinload(Proposal.partial_children).selectinload(Proposal.galvanization_load_items).selectinload(GalvanizationLoadItem.load),
            selectinload(Proposal.partial_children).selectinload(Proposal.expedition_items),
            selectinload(Proposal.partial_children).selectinload(Proposal.fiscal_record).selectinload(FiscalRecord.items),
            selectinload(Proposal.partial_children).selectinload(Proposal.fiscal_record).selectinload(FiscalRecord.invoices),
        )
        .where(Proposal.id == proposal_id)
        .execution_options(populate_existing=True)
    )
    if for_update:
        stmt = stmt.with_for_update()
    proposal = (await session.execute(stmt)).scalars().unique().first()
    if proposal is None:
        raise ApiError(error_codes.PROPOSAL_NOT_FOUND, "Proposta nao encontrada.", status_code=404)
    return proposal


async def _get_production_proposal_for_update(session: AsyncSession, proposal_id: int) -> Proposal:
    """Carrega e bloqueia a proposta para uma transicao produtiva atomica."""

    proposal = (
        await session.execute(
            select(Proposal)
            .options(selectinload(Proposal.items))
            .where(Proposal.id == proposal_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalars().unique().first()
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
    history_proposal_ids: set[int] | None = None
    if proposal_id is not None:
        await get_proposal(session, proposal_id)
        child_ids = (await session.execute(
            select(Proposal.id).where(Proposal.parent_proposal_id == proposal_id)
        )).scalars().all()
        history_proposal_ids = {int(proposal_id), *(int(value) for value in child_ids)}

    proposal_events = (
        await session.execute(
            select(ProposalEvent).where(
                ProposalEvent.proposal_id.in_(history_proposal_ids)
                if history_proposal_ids is not None else True
            )
        )
    ).scalars().all()
    expedition_events = (
        await session.execute(
            select(ExpeditionEvent).where(
                ExpeditionEvent.proposal_id.in_(history_proposal_ids)
                if history_proposal_ids is not None else True
            )
        )
    ).scalars().all()
    galvanization_events = (
        await session.execute(
            select(GalvanizationLoadEvent).where(
                GalvanizationLoadEvent.proposal_id.in_(history_proposal_ids)
                if history_proposal_ids is not None else GalvanizationLoadEvent.proposal_id.is_not(None)
            )
        )
    ).scalars().all()
    fiscal_stmt = select(FiscalEvent).join(FiscalRecord, FiscalRecord.id == FiscalEvent.fiscal_record_id)
    if history_proposal_ids is not None:
        fiscal_stmt = fiscal_stmt.where(FiscalRecord.proposal_id.in_(history_proposal_ids))
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


def _actor_label(actor_name: str | None) -> str:
    return actor_name or "Alguem"


def _reason_suffix(metadata: dict) -> str:
    reason = metadata.get("reason")
    return f" ({reason})" if reason else ""


ACTIVITY_TEMPLATES = {
    "PROPOSAL_CREATED": lambda who, md: f"{who} criou a proposta.",
    "PROPOSAL_UPDATED": lambda who, md: f"{who} editou os dados da proposta.",
    "PROPOSAL_CANCELLED": lambda who, md: f"{who} cancelou a proposta{_reason_suffix(md)}.",
    "PROPOSAL_STATUS_CHANGED": lambda who, md: f"{who} atualizou o status da proposta.",
    "PROPOSAL_REACTIVATED": lambda who, md: f"{who} reativou a proposta.",
    "PROPOSAL_DEACTIVATED": lambda who, md: f"{who} desativou a proposta.",
    "PROPOSAL_ITEM_UPDATED": lambda who, md: f"{who} editou um item da proposta.",
    "PROPOSAL_ADMINISTRATIVE_CORRECTION": lambda who, md: f"{who} registrou uma correcao administrativa.",
    "WAREHOUSE_STATUS_CHANGED": lambda who, md: f"{who} atualizou o status no almoxarifado.",
    "PRODUCTION_STARTED": lambda who, md: f"{who} iniciou a producao.",
    "PRODUCTION_PAUSED": lambda who, md: f"{who} pausou a producao{_reason_suffix(md)}.",
    "PRODUCTION_RESUMED": lambda who, md: f"{who} retomou a producao.",
    "PRODUCTION_ITEM_FLOW_UPDATED": lambda who, md: f"{who} definiu o fluxo de producao do item.",
    "PRODUCTION_ITEM_FLOW_BATCH_UPDATED": lambda who, md: f"{who} atualizou o fluxo de {md.get('changed', 'alguns')} item(ns).",
    "PRODUCTION_ITEM_WEIGHT_UPDATED": lambda who, md: (
        f"{who} atualizou o peso do item de {format_quantity(md.get('from'))} kg para {format_quantity(md.get('to'))} kg."
    ),
    "PRODUCTION_WEIGHTS_UPDATED": lambda who, md: f"{who} atualizou o peso de {md.get('changed', 'alguns')} item(ns).",
    "PRODUCTION_COMPLETED": lambda who, md: f"{who} concluiu a producao.",
    "PRODUCTION_PARTIALLY_COMPLETED": lambda who, md: f"{who} concluiu parcialmente a producao.",
    "PROPOSAL_PARTIAL_CHILD_CREATED": lambda who, md: f"{who} criou a parcial {md.get('child_proposal_number', '')} a partir da proposta mae.",
    "PROPOSAL_PARTIAL_CHILD_MERGED": lambda who, md: f"{who} uniu uma parcial ao grupo operacional equivalente.",
    "PROPOSAL_PARTIAL_CHILD_GROUPED": lambda who, md: f"{who} consolidou parciais com o mesmo status operacional.",
    "PARENT_PROPOSAL_REBORN": lambda who, md: f"{who} reativou a proposta mae apos a convergencia das parciais.",
    "PRODUCTION_ITEM_COMPLETED": lambda who, md: (
        f"{who} concluiu a producao do item {md['item_number']}." if md.get("item_number") else f"{who} concluiu a producao de um item."
    ),
    "GALVANIZATION_LOAD_CREATED": lambda who, md: f"{who} criou uma carga de galvanizacao com {md.get('items', 0)} item(ns).",
    "GALVANIZATION_LOAD_UPDATED": lambda who, md: f"{who} atualizou a carga de galvanizacao.",
    "GALVANIZATION_LOAD_RELEASED": lambda who, md: f"{who} liberou a carga de galvanizacao para envio.",
    "GALVANIZATION_ITEM_SENT": lambda who, md: f"{who} enviou {format_quantity(md.get('sent_quantity'))} unidade(s) para galvanizacao.",
    "GALVANIZATION_ITEM_RETURNED": lambda who, md: f"{who} registrou o retorno de {format_quantity(md.get('quantity'))} unidade(s) da galvanizacao.",
    "GALVANIZATION_RETURN_REGISTERED": lambda who, md: f"{who} registrou o retorno da carga de galvanizacao.",
    "GALVANIZATION_LOAD_CLOSED": lambda who, md: f"{who} encerrou a carga de galvanizacao.",
    "EXPEDITION_SEPARATION_STARTED": lambda who, md: f"{who} iniciou a separacao para entrega.",
    "EXPEDITION_ITEM_SEPARATED": lambda who, md: f"{who} separou {format_quantity(md.get('quantity'))} unidade(s) para entrega.",
    "EXPEDITION_SEPARATION_RECALCULATED": lambda who, md: f"{who} atualizou a separacao da expedicao.",
    "EXPEDITION_ITEM_DELIVERED": lambda who, md: f"{who} registrou a entrega de {format_quantity(md.get('quantity'))} unidade(s).",
    "EXPEDITION_DELIVERY_RECALCULATED": lambda who, md: f"{who} atualizou o status de entrega.",
    "EXPEDITION_ITEM_REMANAGED": lambda who, md: (
        f"{who} remanejou {format_quantity(md.get('quantity'))} unidade(s) de volta para a producao{_reason_suffix(md)}."
    ),
    "EXPEDITION_REMANAGEMENT_TO_PRODUCTION": lambda who, md: f"{who} remanejou itens da expedicao de volta para a producao.",
    "EXPEDITION_ITEM_REMANAGED_TO_EARLY_DELIVERY": lambda who, md: (
        f"{who} remanejou {format_quantity(md.get('quantity'))} unidade(s) para entrega antecipada."
    ),
    "EXPEDITION_EARLY_DELIVERY_BY_REMANAGEMENT": lambda who, md: f"{who} registrou entrega antecipada por remanejamento.",
    "FISCAL_INVOICE_REGISTERED": lambda who, md: (
        f"{who} registrou a emissao fiscal NF {md['invoice_number']}."
        if md.get("invoice_number") and not str(md["invoice_number"]).startswith("REGISTRO-")
        else f"{who} registrou a emissao fiscal."
    ),
    "FISCAL_BATCH_CONFIRMED": lambda who, md: f"{who} confirmou o lote de emissoes fiscais.",
    "FISCAL_INVOICE_ITEM_CANCELLED": lambda who, md: f"{who} cancelou um item da nota fiscal{_reason_suffix(md)}.",
    "FISCAL_INVOICE_WITHDRAWN": lambda who, md: f"{who} registrou a retirada da nota fiscal.",
}


def _activity_headline(event_type: str, actor_name: str | None, metadata: dict, from_status: str | None, to_status: str | None) -> str:
    """Traduz um evento tecnico em uma frase legivel, sem nunca concatenar o
    dict de metadata cru — cada tipo conhecido tem um texto proprio; tipos
    desconhecidos caem num rotulo neutro que usa apenas colunas estruturadas
    (from_status/to_status), nunca as chaves brutas da metadata."""
    who = _actor_label(actor_name)
    template = ACTIVITY_TEMPLATES.get(event_type)
    if template is not None:
        try:
            return template(who, metadata or {})
        except (KeyError, TypeError, ValueError):
            pass
    label = event_type.replace("_", " ").strip().lower().capitalize()
    if from_status and to_status and from_status != to_status:
        return f"{who} atualizou o status ({label}: {from_status} para {to_status})."
    return f"{who} registrou uma atualizacao ({label})."


async def list_proposal_activities(
    session: AsyncSession,
    proposal_id: int,
    *,
    area: str | None = None,
    before: datetime | None = None,
    limit: int = 50,
) -> list[ProposalActivityItem]:
    """Feed operacional legivel de uma proposta — le as mesmas 4 tabelas de
    evento que list_proposal_history, mas nunca reusa _history_observation:
    cada evento vira uma frase pronta via _activity_headline, sem vazar
    metadata bruta (version/item_version/from/to/payload) para a interface."""
    await get_proposal(session, proposal_id)

    proposal_events = (
        await session.execute(select(ProposalEvent).where(ProposalEvent.proposal_id == proposal_id))
    ).scalars().all()
    expedition_events = (
        await session.execute(select(ExpeditionEvent).where(ExpeditionEvent.proposal_id == proposal_id))
    ).scalars().all()
    galvanization_events = (
        await session.execute(select(GalvanizationLoadEvent).where(GalvanizationLoadEvent.proposal_id == proposal_id))
    ).scalars().all()
    fiscal_events = (
        await session.execute(
            select(FiscalEvent).join(FiscalRecord, FiscalRecord.id == FiscalEvent.fiscal_record_id).where(FiscalRecord.proposal_id == proposal_id)
        )
    ).scalars().all()

    raw_rows: list[tuple] = (
        [(event, "proposal", event.to_area or event.from_area) for event in proposal_events]
        + [(event, "expedition", "EXPEDICAO") for event in expedition_events]
        + [(event, "galvanization", "GALVANIZACAO") for event in galvanization_events]
        + [(event, "fiscal", "FISCAL") for event in fiscal_events]
    )

    actor_ids = {event.actor_user_id for event, _source, _area in raw_rows if event.actor_user_id}
    users_by_id: dict[int, User] = {}
    if actor_ids:
        rows = (await session.execute(select(User).where(User.id.in_(actor_ids)))).scalars().all()
        users_by_id = {row.id: row for row in rows}

    items: list[ProposalActivityItem] = []
    for event, source, event_area in raw_rows:
        # correcao administrativa e um "motivo" de filtro proprio (pedido
        # explicitamente pela interface), nao a area operacional corrigida.
        bucket_area = "CORRECAO_ADMINISTRATIVA" if event.event_type == "PROPOSAL_ADMINISTRATIVE_CORRECTION" else event_area
        if area and bucket_area != area:
            continue
        if before is not None and event.created_at >= before:
            continue
        try:
            metadata = event.metadata_ if isinstance(event.metadata_, dict) else {}
            actor = users_by_id.get(event.actor_user_id) if event.actor_user_id else None
            items.append(
                ProposalActivityItem(
                    id=int(event.id),
                    proposal_id=proposal_id,
                    event_type=event.event_type,
                    area=bucket_area,
                    actor_name=actor.display_name if actor else None,
                    headline=_activity_headline(
                        event.event_type,
                        actor.display_name if actor else None,
                        metadata,
                        getattr(event, "from_status", None),
                        getattr(event, "to_status", None),
                    ),
                    item_code=metadata.get("item_number") if isinstance(metadata.get("item_number"), str) else None,
                    correlation_id=event.request_id,
                    occurred_at=event.created_at,
                )
            )
        except Exception:
            logger.exception("Evento de atividade invalido: source=%r event_id=%r", source, getattr(event, "id", None))

    items.sort(key=lambda item: (item.occurred_at, item.id), reverse=True)
    return items[:limit]


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
        cancelled_at=row.cancelled_at,
        cancelled_by=row.cancelled_by,
        cancellation_reason=row.cancellation_reason,
        created_at=row.created_at,
        updated_at=row.updated_at,
        items=[item_summary(item) for item in sorted(_consolidated_active_items(row), key=lambda item: (item.item_number, item.id))],
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
            session.add(await _new_item(session, proposal.id, proposal.proposal_number, item_payload, actor))
        await session.flush()
        event_metadata = {
            "items": len(payload.items),
            "source": payload.source,
        }
        if payload.import_metadata:
            event_metadata["import_metadata"] = payload.import_metadata
        await _record_event(session, proposal, "PROPOSAL_CREATED", actor, request_id=request_id, metadata=event_metadata)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError(error_codes.PROPOSAL_NUMBER_ALREADY_EXISTS, "Ja existe proposta com este numero.", status_code=409) from exc
    return proposal_detail(await get_proposal(session, proposal.id))


async def update_proposal(session: AsyncSession, proposal_id: int, payload: ProposalUpdate, actor: User, *, request_id: str | None) -> ProposalDetail:
    proposal = await get_proposal(session, proposal_id)
    _ensure_proposal_not_cancelled(proposal)
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
    try:
        proposal = await get_proposal(session, proposal_id)
        _ensure_version(proposal.version, payload.version)
        if _proposal_is_cancelled(proposal):
            raise ApiError(error_codes.PROPOSAL_CANNOT_BE_CANCELLED, "A proposta ja esta cancelada.", status_code=409)
        ProposalStateMachine.ensure_can_cancel(proposal.current_status)
        if _proposal_is_completed(proposal):
            raise ApiError(error_codes.PROPOSAL_CANNOT_BE_CANCELLED, "Proposta totalmente concluida nao pode ser cancelada sem fluxo de devolucao ou estorno.", status_code=409)
        from_area, from_status = proposal.current_area, proposal.current_status
        previous_state = {
            "current_area": proposal.current_area,
            "current_status": proposal.current_status,
            "general_status": proposal.general_status,
            "production_status": proposal.production_status,
            "galvanization_status": proposal.galvanization_status,
            "shipping_status": proposal.shipping_status,
            "warehouse_status": proposal.warehouse_status,
            "is_completed": proposal.is_completed,
        }
        to_area, to_status = ProposalStateMachine.cancel_state()
        proposal.current_area = to_area
        proposal.current_status = to_status
        proposal.general_status = to_status
        proposal.is_cancelled = True
        proposal.cancelled_at = datetime.now(UTC)
        proposal.cancelled_by = actor.id
        proposal.cancellation_reason = payload.reason
        _touch(proposal, actor)
        await _record_event(session, proposal, "PROPOSAL_CANCELLED", actor, request_id=request_id, from_area=from_area, from_status=from_status, to_area=to_area, to_status=to_status, metadata={"reason": payload.reason, "cancelled_at": proposal.cancelled_at.isoformat(), "previous_state": previous_state, "version": proposal.version})
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return proposal_detail(await get_proposal(session, proposal.id))


async def change_proposal_status(session: AsyncSession, proposal_id: int, payload: ProposalStatusChangeRequest, actor: User, *, request_id: str | None) -> ProposalDetail:
    proposal = await get_proposal(session, proposal_id)
    _ensure_proposal_not_cancelled(proposal)
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
        _recalculate_production_state(proposal)
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
    if payload.to_area == "PRODUCAO" and proposal.current_area != "PRODUCAO":
        await _record_event(
            session,
            proposal,
            "PRODUCTION_FLOW_AUTO_ROUTED",
            actor,
            request_id=request_id,
            from_area="PRODUCAO",
            from_status=payload.to_status,
            to_area=proposal.current_area,
            to_status=proposal.current_status,
            metadata={
                "reason": "Fluxo ja definido sem producao interna pendente.",
                "version": proposal.version,
            },
        )
    await session.commit()
    return proposal_detail(await get_proposal(session, proposal.id))


async def get_allowed_administrative_corrections(
    session: AsyncSession,
    proposal_id: int,
) -> ProposalAdministrativeCorrectionOptionsResponse:
    proposal = await _get_administrative_proposal(session, proposal_id)
    facts = collect_administrative_facts(proposal)
    options = administrative_allowed_corrections(proposal, facts)
    warnings = ["Somente correcoes de estado sustentadas pelos fatos operacionais sao exibidas."]
    if _proposal_is_cancelled(proposal):
        warnings.append("A proposta esta cancelada; a correcao administrativa generica nao pode reativa-la.")
    elif not options:
        warnings.append("A projecao atual ja corresponde aos fatos ou exige uma operacao administrativa especifica.")
    return ProposalAdministrativeCorrectionOptionsResponse(
        proposal_id=proposal.id,
        proposal_number=proposal.proposal_number,
        version=proposal.version,
        current_state=administrative_snapshot(proposal, facts),
        facts=facts.summary(),
        options=[administrative_option_payload(option, proposal) for option in options],
        warnings=warnings,
    )


async def preview_administrative_correction(
    session: AsyncSession,
    proposal_id: int,
    payload: ProposalAdministrativeCorrectionPreviewRequest,
) -> ProposalAdministrativeCorrectionPreviewResponse:
    proposal = await _get_administrative_proposal(session, proposal_id)
    _ensure_version(proposal.version, payload.expected_version)
    facts = collect_administrative_facts(proposal)
    result = build_administrative_preview(proposal, payload.to_area, payload.to_status, facts)
    return ProposalAdministrativeCorrectionPreviewResponse(**result)


async def administrative_correction(
    session: AsyncSession,
    proposal_id: int,
    payload: ProposalAdministrativeCorrectionRequest,
    actor: User,
    *,
    request_id: str | None,
) -> ProposalDetail:
    to_area = normalize_administrative_area(payload.to_area)
    to_status = normalize_administrative_status(payload.to_status)
    reason = payload.reason.strip()

    try:
        proposal = await _get_administrative_proposal(session, proposal_id, for_update=True)

        previous_event = next(
            (
                event
                for event in proposal.events
                if event.event_type == "PROPOSAL_ADMINISTRATIVE_CORRECTION"
                and (event.metadata_ or {}).get("idempotency_key") == payload.idempotency_key
            ),
            None,
        )
        if previous_event is not None:
            metadata = previous_event.metadata_ or {}
            if (
                metadata.get("to_area") != to_area
                or metadata.get("to_status") != to_status
                or metadata.get("reason") != reason
            ):
                raise ApiError(
                    error_codes.ADMIN_CORRECTION_IDEMPOTENCY_CONFLICT,
                    "A chave de idempotencia ja foi usada por outra correcao nesta proposta.",
                    status_code=409,
                )
            await session.rollback()
            return proposal_detail(await get_proposal(session, proposal_id))

        _ensure_version(proposal.version, payload.expected_version)
        facts = collect_administrative_facts(proposal)
        correction_preview = build_administrative_preview(proposal, to_area, to_status, facts)
        if not correction_preview["allowed"]:
            blocker_codes = {row["code"] for row in correction_preview["blockers"]}
            error_code = (
                error_codes.PROPOSAL_CANCELLED_TERMINAL
                if "PROPOSAL_CANCELLED_TERMINAL" in blocker_codes
                else error_codes.ADMIN_CORRECTION_BLOCKED
            )
            raise ApiError(
                error_code,
                "A correcao solicitada contradiz os fatos operacionais da proposta.",
                status_code=409,
                details={"blockers": correction_preview["blockers"]},
            )

        candidate = next(
            option
            for option in administrative_allowed_corrections(proposal, facts)
            if (option.target_area, option.target_status) == (to_area, to_status)
        )
        before_snapshot = administrative_snapshot(proposal, facts)
        from_area = proposal.current_area
        from_status = proposal.current_status
        for field, value in candidate.updates.items():
            setattr(proposal, field, value)
        _touch(proposal, actor)
        after_snapshot = administrative_snapshot(proposal, collect_administrative_facts(proposal))
        changed_fields = [
            field
            for field in ADMINISTRATIVE_STATE_FIELDS
            if before_snapshot.get(field) != after_snapshot.get(field)
        ]

        history_note = (
            "CORRECAO ADMINISTRATIVA DE ESTADO\n"
            f"Area anterior: {from_area or '-'}\n"
            f"Status anterior: {from_status or '-'}\n"
            f"Area solicitada: {to_area}\n"
            f"Status solicitado: {to_status}\n"
            f"Motivo: {reason}"
        )
        metadata = {
            "proposal_id": proposal.id,
            "proposal_number": proposal.proposal_number,
            "correction_type": payload.correction_type,
            "from_area": from_area,
            "from_status": from_status,
            "to_area": to_area,
            "to_status": to_status,
            "reason": reason,
            "idempotency_key": payload.idempotency_key,
            "expected_version": payload.expected_version,
            "resulting_version": proposal.version,
            "changed_fields": changed_fields,
            "before_snapshot": before_snapshot,
            "after_snapshot": after_snapshot,
            "observation": history_note,
        }
        await _record_event(
            session,
            proposal,
            "PROPOSAL_ADMINISTRATIVE_CORRECTION",
            actor,
            request_id=request_id,
            from_area=from_area,
            from_status=from_status,
            to_area=to_area,
            to_status=to_status,
            metadata=metadata,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return proposal_detail(await get_proposal(session, proposal_id))


async def start_production(session: AsyncSession, proposal_id: int, payload: ProductionStartRequest, actor: User, *, request_id: str | None) -> ProductionProposalDetail:
    proposal = await _get_production_proposal_for_update(session, proposal_id)
    _ensure_version(proposal.version, payload.version)
    _ensure_production_area(proposal)
    current = _production_status_value(proposal.production_status or proposal.current_status)
    ProductionStateMachine.ensure_can_start(current)
    if not _active_items(proposal):
        raise ApiError(error_codes.PROPOSAL_REQUIRES_ITEMS, "A proposta precisa possuir itens ativos.", status_code=422)
    if not _internal_items(proposal):
        raise ApiError(error_codes.PRODUCTION_NO_INTERNAL_ITEMS, "Nao existem itens para producao interna.", status_code=409)
    from_status = current
    previous_area = proposal.current_area
    proposal.production_status = "INICIADO"
    if previous_area == "PRODUCAO":
        proposal.current_status = "INICIADO"
        proposal.general_status = "EM_PRODUCAO"
    _touch(proposal, actor)
    await _record_event(
        session,
        proposal,
        "PRODUCTION_STARTED",
        actor,
        request_id=request_id,
        from_area="PRODUCAO",
        from_status=from_status,
        to_area="PRODUCAO",
        to_status=proposal.production_status,
        metadata={
            "observation": payload.observation,
            "version": proposal.version,
            "current_area": previous_area,
            "reallocated": previous_area != "PRODUCAO",
        },
    )
    await session.commit()
    return _production_detail(await get_proposal(session, proposal.id))


async def pause_production(session: AsyncSession, proposal_id: int, payload: ProductionPauseRequest, actor: User, *, request_id: str | None) -> ProductionProposalDetail:
    proposal = await _get_production_proposal_for_update(session, proposal_id)
    _ensure_version(proposal.version, payload.version)
    _ensure_production_area(proposal)
    current = _production_status_value(proposal.production_status or proposal.current_status)
    ProductionStateMachine.ensure_can_pause(current)

    current_area = proposal.current_area
    proposal.production_status = ProductionStateMachine.PAUSED
    if current_area == "PRODUCAO":
        proposal.current_status = ProductionStateMachine.PAUSED
    _touch(proposal, actor)
    await _record_event(
        session,
        proposal,
        "PRODUCTION_PAUSED",
        actor,
        request_id=request_id,
        from_area="PRODUCAO",
        from_status=current,
        to_area="PRODUCAO",
        to_status=ProductionStateMachine.PAUSED,
        metadata={"reason": payload.reason, "version": proposal.version, "current_area": current_area},
    )
    await session.commit()
    return _production_detail(await get_proposal(session, proposal.id))


async def resume_production(session: AsyncSession, proposal_id: int, payload: ProductionResumeRequest, actor: User, *, request_id: str | None) -> ProductionProposalDetail:
    proposal = await _get_production_proposal_for_update(session, proposal_id)
    _ensure_version(proposal.version, payload.version)
    _ensure_production_area(proposal)
    current = _production_status_value(proposal.production_status or proposal.current_status)
    ProductionStateMachine.ensure_can_resume(current)

    current_area = proposal.current_area
    proposal.production_status = ProductionStateMachine.STARTED
    if current_area == "PRODUCAO":
        proposal.current_status = ProductionStateMachine.STARTED
    _touch(proposal, actor)
    await _record_event(
        session,
        proposal,
        "PRODUCTION_RESUMED",
        actor,
        request_id=request_id,
        from_area="PRODUCAO",
        from_status=current,
        to_area="PRODUCAO",
        to_status=ProductionStateMachine.STARTED,
        metadata={"observation": payload.observation, "version": proposal.version, "current_area": current_area},
    )
    await session.commit()
    return _production_detail(await get_proposal(session, proposal.id))


async def update_production_item_flow(session: AsyncSession, proposal_id: int, payload: ProductionItemFlowRequest, actor: User, *, request_id: str | None) -> ProductionProposalDetail:
    proposal = await get_proposal(session, proposal_id)
    _ensure_version(proposal.version, payload.version)
    _ensure_production_area(proposal)
    from_area = proposal.current_area
    from_status = proposal.current_status
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
            "flow_defined": item.flow_defined,
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
        flow_defined = produce != "INDEFINIDO" and galvanize != "INDEFINIDO"
        if (item.produce_internally, item.requires_galvanization, item.non_production_reason or "", item.notes or "", item.produced, item.flow_defined) == (produce, galvanize, reason, notes or "", produced, flow_defined):
            continue
        lock_reason = _flow_lock_reason(item)
        if lock_reason is not None:
            raise ApiError(error_codes.PRODUCTION_ITEM_FLOW_LOCKED, f"Item bloqueado para alteracao de fluxo: {lock_reason}", status_code=409)
        item.produce_internally = produce
        item.requires_galvanization = galvanize
        item.non_production_reason = reason
        item.notes = notes
        item.produced = produced
        item.flow_defined = flow_defined
        _touch(item, actor)
        changed += 1
        await _record_event(session, proposal, "PRODUCTION_ITEM_FLOW_UPDATED", actor, item_id=item.id, request_id=request_id, metadata={"origin": payload.origin, "previous": previous, "current": {"produce_internally": produce, "requires_galvanization": galvanize, "non_production_reason": reason, "notes": notes or "", "produced": produced, "flow_defined": flow_defined}, "item_version": item.version})
    if changed:
        _recalculate_production_state(proposal)
        _touch(proposal, actor)
        auto_routed = from_area == "PRODUCAO" and proposal.current_area != "PRODUCAO"
        await _record_event(
            session,
            proposal,
            "PRODUCTION_ITEM_FLOW_BATCH_UPDATED",
            actor,
            request_id=request_id,
            from_area=from_area,
            from_status=from_status,
            to_area=proposal.current_area,
            to_status=proposal.current_status,
            metadata={"changed": changed, "version": proposal.version, "auto_routed": auto_routed},
        )
        if auto_routed:
            await _record_event(
                session,
                proposal,
                "PRODUCTION_FLOW_AUTO_ROUTED",
                actor,
                request_id=request_id,
                from_area=from_area,
                from_status=from_status,
                to_area=proposal.current_area,
                to_status=proposal.current_status,
                metadata={
                    "reason": "Definicao de fluxo concluida sem producao interna pendente.",
                    "version": proposal.version,
                },
            )
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
        weight = normalize_known_weight(update.unit_weight)
        if item.unit_weight == weight:
            continue
        previous = item.unit_weight
        item.unit_weight = weight
        item.total_weight = calculate_known_weight(item.quantity, weight)
        item.weight_source = "MANUAL" if weight is not None else "NONE"
        item.weight_status = "MANUAL" if weight is not None else "PENDING"
        item.nomus_product_id = None
        item.weight_synced_at = None
        _touch(item, actor)
        changed += 1
        await _record_event(session, proposal, "PRODUCTION_ITEM_WEIGHT_UPDATED", actor, item_id=item.id, request_id=request_id, metadata={"from": str(previous), "to": str(weight), "item_version": item.version})
    if changed:
        _touch(proposal, actor)
        await _record_event(session, proposal, "PRODUCTION_WEIGHTS_UPDATED", actor, request_id=request_id, metadata={"changed": changed, "version": proposal.version})
    await session.commit()
    return _production_detail(await get_proposal(session, proposal.id))


async def complete_production_items(session: AsyncSession, proposal_id: int, payload: ProductionCompleteItemsRequest, actor: User, *, request_id: str | None) -> ProductionProposalDetail:
    proposal = await _get_production_proposal_for_update(session, proposal_id)
    if await _request_event_exists(session, request_id, proposal_id=proposal.id, event_type="PRODUCTION_PARTIALLY_COMPLETED") or await _request_event_exists(session, request_id, proposal_id=proposal.id, event_type="PRODUCTION_COMPLETED"):
        return _production_detail(await get_proposal(session, proposal.id))
    _ensure_version(proposal.version, payload.version)
    _ensure_production_area(proposal)
    current = _production_status_value(proposal.production_status or proposal.current_status)
    ProductionStateMachine.ensure_can_complete(current)
    _ensure_flow_ready(proposal)
    pending = {item.id: item for item in _internal_items(proposal) if _loaded_item_balance(item).production_pending > 0}
    if not pending:
        _finalize_production_destination(proposal)
        _touch(proposal, actor)
        await _record_event(
            session,
            proposal,
            "PRODUCTION_COMPLETED",
            actor,
            request_id=request_id,
            from_area="PRODUCAO",
            from_status=current,
            to_area="PRODUCAO",
            to_status=proposal.production_status,
            metadata={"observation": payload.observation, "version": proposal.version, "current_area": proposal.current_area},
        )
        await session.commit()
        return _production_detail(await get_proposal(session, proposal.id))
    selected_ids = [int(item_id) for item_id in (payload.item_ids or list(pending))]
    selected = [pending[item_id] for item_id in selected_ids if item_id in pending]
    if not selected:
        raise ApiError(error_codes.PRODUCTION_ITEM_NOT_AVAILABLE, "Selecione pelo menos um item pendente de producao.", status_code=409)
    for item in selected:
        native_pending = _loaded_item_balance(item).reallocatable_production
        if native_pending > 0 and not item.produced:
            item.produced = True
            _touch(item, actor)
            await _record_event(session, proposal, "PRODUCTION_ITEM_COMPLETED", actor, item_id=item.id, request_id=request_id, metadata={"item_number": item.item_number, "quantity": str(native_pending), "item_version": item.version})
        for transfer in item.production_allocations_received:
            transfer_pending = quantity(transfer.quantity - transfer.completed_quantity)
            if transfer.status == "COMPLETED" or transfer_pending <= 0:
                continue
            transfer.completed_quantity = transfer.quantity
            transfer.status = "COMPLETED"
            transfer.completed_by = actor.id
            transfer.completed_at = datetime.now(UTC)
            transfer.version += 1
            exp_item = item.expedition_item
            if exp_item is None:
                exp_item = ExpeditionItem(
                    proposal_id=proposal.id,
                    proposal_item_id=item.id,
                    available_quantity=transfer_pending,
                    origin="PRODUCAO_REALOCADA",
                    status="EM_SEPARACAO",
                    created_by=actor.id,
                    updated_by=actor.id,
                )
                exp_item.proposal = proposal
                exp_item.proposal_item = item
                session.add(exp_item)
            else:
                exp_item.available_quantity = quantity(exp_item.available_quantity + transfer_pending)
                exp_item.origin = "MISTO"
                _touch(exp_item, actor)
            await _record_event(session, proposal, "REALLOCATED_PRODUCTION_COMPLETED", actor, item_id=item.id, request_id=request_id, metadata={"transfer_id": transfer.id, "quantity": str(transfer_pending), "from_item_id": transfer.from_item_id, "to_item_id": transfer.to_item_id})
    # A partir do segundo lote, os itens produzidos deixam de pertencer
    # operacionalmente a mae e passam a uma proposta filha. A primeira
    # conclusao total continua sendo a propria mae, sem criar uma filha.
    existing_children = int((await session.execute(
        select(func.count(Proposal.id)).where(Proposal.parent_proposal_id == proposal.id)
    )).scalar_one() or 0)
    remaining_before_split = [
        item for item in _internal_items(proposal)
        if _loaded_item_balance(item).production_pending > 0 and item not in selected
    ]
    partial_child = None
    partial_children: list[Proposal] = []
    destination_groups: dict[str, list[ProposalItem]] = {}
    for item in selected:
        destination = "GALVANIZACAO" if item.requires_galvanization == "SIM" else "EXPEDICAO"
        destination_groups.setdefault(destination, []).append(item)
    # Destinos mistos (galvanizacao + expedicao) na MESMA conclusao nao
    # justificam sozinhos uma filha: _finalize_production_destination ja
    # resolve a area unica da mae por prioridade (galvanizacao primeiro) e a
    # elegibilidade de cada item continua sendo por item, nao pela area
    # agregada (Secao acima). Uma filha so nasce quando ha de fato uma
    # segunda leva (algo ficou pendente) ou quando ja existe uma anterior.
    if selected and (remaining_before_split or existing_children > 0):
        next_partial = int((await session.execute(
            select(func.coalesce(func.max(Proposal.partial_number), 0))
            .where(Proposal.parent_proposal_id == proposal.id)
        )).scalar_one() or 0) + 1
        for destination, child_items in destination_groups.items():
            # O numero parcial e derivado da mae, mas a unicidade e global.
            # O loop tambem cobre importacoes antigas e concorrencia logica
            # dentro do mesmo request.
            while await session.scalar(
                select(Proposal.id).where(Proposal.proposal_number == f"{proposal.proposal_number}-{next_partial}")
            ) is not None:
                next_partial += 1
            child = Proposal(
                legacy_id=None,
                proposal_number=f"{proposal.proposal_number}-{next_partial}",
                customer_name=proposal.customer_name,
                project_name=proposal.project_name,
                order_reference=proposal.order_reference,
                lot=proposal.lot,
                proposal_date=proposal.proposal_date,
                deadline_date=proposal.deadline_date,
                current_area="PRODUCAO",
                current_status="FINALIZADO",
                general_status="EM_PRODUCAO",
                production_status="FINALIZADO",
                warehouse_status=proposal.warehouse_status,
                flow_situation="PARCIAL_COM_PENDENCIA",
                has_production_pending=False,
                process_type=proposal.process_type,
                parent_proposal_id=proposal.id,
                parent_legacy_id=proposal.legacy_id,
                partial_number=next_partial,
                is_partial=True,
                is_cancelled=False,
                is_completed=False,
                source="PARTIAL_PRODUCTION",
                notes=proposal.notes,
                created_by=actor.id,
                updated_by=actor.id,
            )
            session.add(child)
            await session.flush()
            for item in child_items:
                item.proposal = child
                if item.expedition_item is not None:
                    item.expedition_item.proposal = child
                for load_item in item.galvanization_load_items:
                    load_item.proposal = child
                _touch(item, actor)
            await session.flush()
            _finalize_production_destination(child, items=child_items)
            _touch(child, actor)
            partial_children.append(child)
            await _record_event(
                session,
                proposal,
                "PROPOSAL_PARTIAL_CHILD_CREATED",
                actor,
                request_id=request_id,
                from_area="PRODUCAO",
                from_status=current,
                to_area=child.current_area,
                to_status=child.current_status,
                metadata={
                    "child_proposal_id": child.id,
                    "child_proposal_number": child.proposal_number,
                    "partial_number": next_partial,
                    "destination": destination,
                    "item_ids": [int(item.id) for item in child_items],
                },
            )
            await _record_event(
                session,
                child,
                "PROPOSAL_PARTIAL_CHILD_CREATED",
                actor,
                request_id=request_id,
                from_area="PRODUCAO",
                from_status=current,
                to_area=child.current_area,
                to_status=child.current_status,
                metadata={"parent_proposal_id": proposal.id, "destination": destination, "item_ids": [int(item.id) for item in child_items]},
            )
            next_partial += 1
        partial_child = partial_children[0] if partial_children else None
    remaining = [item for item in _internal_items(proposal) if _loaded_item_balance(item).production_pending > 0]
    from_status = current
    if remaining:
        proposal.production_status = "FINALIZADO_PARCIAL"
        if proposal.current_area == "PRODUCAO":
            proposal.current_status = "FINALIZADO_PARCIAL"
            proposal.general_status = "EM_PRODUCAO"
        proposal.flow_situation = "PARCIAL_COM_PENDENCIA"
        proposal.has_production_pending = True
        event = "PRODUCTION_PARTIALLY_COMPLETED"
    else:
        if partial_child is not None:
            # A mae sem itens pendentes continua existindo como referencia
            # consolidada no Controle Geral.
            proposal.current_area = "CONTROLE_GERAL"
            proposal.current_status = "EM_PRODUCAO"
            proposal.general_status = "EM_PRODUCAO"
            proposal.production_status = "FINALIZADO"
            proposal.has_production_pending = False
            proposal.flow_situation = "PARCIAL_COM_PENDENCIA"
            await _record_event(
                session,
                proposal,
                "PARENT_PROPOSAL_OPERATIONAL_DEATH",
                actor,
                request_id=request_id,
                from_area="PRODUCAO",
                from_status=from_status,
                to_area="CONTROLE_GERAL",
                to_status="EM_PRODUCAO",
                metadata={"child_proposal_id": partial_child.id, "child_proposal_number": partial_child.proposal_number},
            )
        elif proposal.current_area == "PRODUCAO":
            _finalize_production_destination(proposal)
        else:
            proposal.production_status = "FINALIZADO"
            proposal.has_production_pending = False
            proposal.flow_situation = "NORMAL"
        event = "PRODUCTION_COMPLETED"
    _touch(proposal, actor)
    await _record_event(
        session,
        proposal,
        event,
        actor,
        request_id=request_id,
        from_area="PRODUCAO",
        from_status=from_status,
        to_area="PRODUCAO",
        to_status=proposal.production_status,
        metadata={
            "item_ids": selected_ids,
            "remaining": len(remaining),
            "observation": payload.observation,
            "version": proposal.version,
            "current_area": proposal.current_area,
            "current_status": proposal.current_status,
        },
    )
    if partial_child is not None:
        await _merge_equal_status_partial_children(session, proposal.id, actor, request_id=request_id)
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
    _ensure_proposal_not_cancelled(proposal)
    ProposalStateMachine.ensure_editable(proposal.current_area, proposal.current_status)
    item = await _new_item(session, proposal.id, proposal.proposal_number, payload, actor)
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
    _ensure_proposal_not_cancelled(proposal)
    ProposalStateMachine.ensure_editable(proposal.current_area, proposal.current_status)
    _ensure_version(item.version, payload.version)
    changed: list[str] = []
    data = payload.model_dump(exclude_unset=True)
    data.pop("version", None)
    field_map = {"produce_internally": "produce_internally", "requires_galvanization": "requires_galvanization"}
    explicit_weight_change = "unit_weight" in data
    code_changed = "product_code" in data and data["product_code"] != item.product_code
    data.pop("total_weight", None)  # peso total sempre recalculado deterministicamente, nunca aceito direto do cliente
    weight_field = data.pop("unit_weight", None) if explicit_weight_change else None

    for key, value in list(data.items()):
        if key in field_map:
            value = _flag_value(value)
        if getattr(item, key) != value:
            setattr(item, key, value)
            changed.append(key)

    quantity = data.get("quantity", item.quantity)
    if explicit_weight_change:
        normalized_weight = normalize_known_weight(weight_field)
        item.unit_weight = normalized_weight
        item.total_weight = calculate_known_weight(quantity, normalized_weight)
        item.weight_source = "MANUAL" if normalized_weight is not None else "NONE"
        item.weight_status = "MANUAL" if normalized_weight is not None else "PENDING"
        item.nomus_product_id = None
        item.weight_synced_at = None
        changed.append("unit_weight")
    elif code_changed:
        weight = await _resolve_item_weight(
            session,
            proposal_number=proposal.proposal_number,
            product_code=data.get("product_code"),
            quantity=quantity,
            explicit_unit_weight=None,
        )
        item.unit_weight = weight["unit_weight"]
        item.total_weight = weight["total_weight"]
        item.weight_source = weight["weight_source"]
        item.weight_status = weight["weight_status"]
        item.nomus_product_id = weight["nomus_product_id"]
        item.weight_synced_at = weight["weight_synced_at"]
        changed.append("unit_weight")
    elif "quantity" in data:
        new_total = calculate_known_weight(quantity, item.unit_weight)
        if new_total != item.total_weight:
            item.total_weight = new_total
            changed.append("total_weight")

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
    _ensure_proposal_not_cancelled(proposal)
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
    balance = _loaded_item_balance(item)
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
        production_pending_quantity=balance.production_pending,
        reallocated_production_pending=balance.production_reallocated_in_pending,
        notes=item.notes,
        version=item.version,
    )


def _galvanization_candidate_item(proposal: Proposal, item: ProposalItem, available: Decimal, situation: str, pending_away: Decimal) -> dict:
    unit_weight = normalize_known_weight(item.unit_weight)
    sent = pending_away.quantize(Decimal("0.0001"))
    return {
        "proposal_id": proposal.id,
        "parent_proposal_id": proposal.parent_proposal_id,
        "partial_number": proposal.partial_number,
        "proposal_number": proposal.proposal_number,
        "customer_name": proposal.customer_name,
        "project_name": proposal.project_name,
        "lot": proposal.lot,
        "current_status": proposal.current_status,
        "item_id": item.id,
        "item_number": item.item_number,
        "product_code": item.product_code,
        "description": item.description,
        "quantity": item.quantity,
        "available_quantity": available.quantize(Decimal("0.0001")),
        "unit_weight": unit_weight,
        "available_weight": calculate_known_weight(available, unit_weight),
        "sent_quantity": sent,
        "sent_weight": calculate_known_weight(sent, unit_weight),
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
    coverage = calculate_weight_coverage(item.sent_weight for item in active)
    pending_weight = sum(
        ((item.sent_weight - (item.returned_weight or Decimal("0"))) for item in pending if item.sent_weight is not None),
        Decimal("0"),
    ).quantize(Decimal("0.0001"))
    proposal_ids = {int(item.proposal_id) for item in active}
    return GalvanizationLoadSummary(
        id=load.id,
        code=load.code,
        driver_name=load.driver_name,
        max_weight=load.max_weight,
        load_weight=load.load_weight,
        load_weight_source=load.load_weight_source,
        load_weight_updated_at=load.load_weight_updated_at,
        total_weight=(load.total_weight or Decimal("0")).quantize(Decimal("0.0001")),
        known_items_weight=coverage.known_weight,
        weight_known_items=coverage.known_items,
        weight_total_items=coverage.total_items,
        weight_complete=coverage.complete,
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


def _galvanization_load_detail(
    load: GalvanizationLoad,
    *,
    actor_names: dict[int, str] | None = None,
) -> GalvanizationLoadDetail:
    actor_names = actor_names or {}
    summary = _galvanization_load_summary(load).model_dump()
    items = [_galvanization_load_item_summary(item) for item in sorted([item for item in load.items if item.active], key=lambda row: (row.proposal.proposal_number, row.proposal_item.item_number, row.id))]
    proposals = []
    for proposal_id in sorted({item.proposal_id for item in load.items if item.active}):
        proposal_items = [item for item in load.items if item.active and item.proposal_id == proposal_id]
        proposal = proposal_items[0].proposal
        coverage = calculate_weight_coverage(item.sent_weight for item in proposal_items)
        sent_weight = coverage.known_weight
        returned_weight = sum(((item.returned_weight or Decimal("0")) for item in proposal_items), Decimal("0")).quantize(Decimal("0.0001"))
        pending_weight = (sent_weight - returned_weight).quantize(Decimal("0.0001"))
        pending_count = sum(1 for item in proposal_items if item.returned_quantity < item.sent_quantity)
        proposals.append(
            {
                "proposal_id": proposal.id,
                "parent_proposal_id": proposal.parent_proposal_id,
                "partial_number": proposal.partial_number,
                "proposal_number": proposal.proposal_number,
                "customer_name": proposal.customer_name,
                "project_name": proposal.project_name,
                "sent_weight": sent_weight,
                "returned_weight": returned_weight,
                "pending_weight": pending_weight,
                "item_count": len(proposal_items),
                "pending_item_count": pending_count,
                "status": "RETORNADO" if pending_count == 0 else ("RETORNO_PARCIAL" if any(item.returned_quantity > 0 for item in proposal_items) else "AGUARDANDO_RETORNO"),
                "weight_known_items": coverage.known_items,
                "weight_total_items": coverage.total_items,
            }
        )
    history = [
        {
            "id": event.id,
            "event_type": event.event_type,
            "load_item_id": event.load_item_id,
            "proposal_id": event.proposal_id,
            "proposal_item_id": event.proposal_item_id,
            "actor_user_id": event.actor_user_id,
            "actor_name": actor_names.get(int(event.actor_user_id)) if event.actor_user_id is not None else None,
            "request_id": event.request_id,
            "from_status": event.from_status,
            "to_status": event.to_status,
            "metadata": event.metadata_ if isinstance(event.metadata_, dict) else {},
            "created_at": event.created_at,
        }
        for event in sorted(load.events, key=lambda row: (row.created_at, row.id), reverse=True)
    ]
    return GalvanizationLoadDetail(
        **summary,
        created_by_user_id=load.created_by,
        created_by_name=actor_names.get(int(load.created_by)) if load.created_by is not None else None,
        updated_by_user_id=load.updated_by,
        updated_by_name=actor_names.get(int(load.updated_by)) if load.updated_by is not None else None,
        items=items,
        proposals=proposals,
        returns=_galvanization_load_returns(load, actor_names=actor_names),
        history=history,
    )


def _galvanization_load_returns(
    load: GalvanizationLoad,
    *,
    actor_names: dict[int, str],
) -> list[dict]:
    """Reconstitui cada retorno a partir dos eventos oficiais da carga.

    Os eventos de item e o fechamento do lote de retorno são gravados na mesma
    transação e compartilham ``request_id``. O consumo da lista pendente também
    mantém compatibilidade com eventos legados sem identificador de requisição.
    """

    load_items = {int(item.id): item for item in load.items}
    proposal_items = {int(item.proposal_item_id): item for item in load.items}
    pending_item_events: list[GalvanizationLoadEvent] = []
    returns: list[dict] = []

    for event in sorted(load.events, key=lambda row: (row.created_at, row.id)):
        if event.event_type == "GALVANIZATION_ITEM_RETURNED":
            pending_item_events.append(event)
            continue
        if event.event_type != "GALVANIZATION_RETURN_REGISTERED":
            continue

        if event.request_id:
            grouped = [row for row in pending_item_events if row.request_id == event.request_id]
        else:
            grouped = list(pending_item_events)
        if grouped:
            grouped_ids = {id(row) for row in grouped}
            pending_item_events = [row for row in pending_item_events if id(row) not in grouped_ids]

        return_items: list[dict] = []
        returned_weights: list[Decimal | None] = []
        for item_event in grouped:
            load_item = None
            if item_event.load_item_id is not None:
                load_item = load_items.get(int(item_event.load_item_id))
            if load_item is None and item_event.proposal_item_id is not None:
                load_item = proposal_items.get(int(item_event.proposal_item_id))
            metadata = item_event.metadata_ if isinstance(item_event.metadata_, dict) else {}
            quantity = _galvanization_event_quantity(metadata.get("quantity"))
            unit_weight = load_item.unit_weight if load_item is not None else None
            returned_weight = calculate_known_weight(quantity, unit_weight)
            returned_weights.append(returned_weight)
            return_items.append(
                {
                    "event_id": item_event.id,
                    "load_item_id": item_event.load_item_id,
                    "proposal_id": item_event.proposal_id,
                    "proposal_number": load_item.proposal.proposal_number if load_item is not None else None,
                    "proposal_item_id": item_event.proposal_item_id,
                    "item_number": load_item.proposal_item.item_number if load_item is not None else None,
                    "product_code": load_item.proposal_item.product_code if load_item is not None else None,
                    "description": load_item.proposal_item.description if load_item is not None else None,
                    "returned_quantity": quantity,
                    "unit_weight": unit_weight,
                    "returned_weight": returned_weight,
                }
            )

        coverage = calculate_weight_coverage(returned_weights)
        metadata = event.metadata_ if isinstance(event.metadata_, dict) else {}
        returns.append(
            {
                "id": event.id,
                "request_id": event.request_id,
                "occurred_at": event.created_at,
                "actor_user_id": event.actor_user_id,
                "actor_name": actor_names.get(int(event.actor_user_id)) if event.actor_user_id is not None else None,
                "from_status": event.from_status,
                "to_status": event.to_status,
                "observation": metadata.get("observation"),
                "return_type": "TOTAL" if event.to_status == "RETORNADA_GALVANIZACAO" else "PARCIAL",
                "returned_weight": coverage.known_weight if coverage.known_items else None,
                "weight_known_items": coverage.known_items,
                "weight_total_items": coverage.total_items,
                "items": return_items,
            }
        )
    return returns


def _galvanization_event_quantity(value) -> Decimal:
    try:
        quantity = Decimal(str(value if value is not None else "0"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")
    return max(quantity, Decimal("0")).quantize(Decimal("0.0001"))


def _galvanization_load_item_summary(item: GalvanizationLoadItem):
    pending_qty = (item.sent_quantity - item.returned_quantity).quantize(Decimal("0.0001"))
    pending_weight = (
        (item.sent_weight - (item.returned_weight or Decimal("0"))).quantize(Decimal("0.0001"))
        if item.sent_weight is not None
        else None
    )
    return {
        "id": item.id,
        "load_id": item.load_id,
        "proposal_id": item.proposal_id,
        "parent_proposal_id": item.proposal.parent_proposal_id,
        "partial_number": item.proposal.partial_number,
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


async def _get_galvanization_load(
    session: AsyncSession,
    load_id: int,
    *,
    for_update: bool = False,
) -> GalvanizationLoad:
    stmt = (
        select(GalvanizationLoad)
        .options(
            selectinload(GalvanizationLoad.items).selectinload(GalvanizationLoadItem.proposal),
            selectinload(GalvanizationLoad.items).selectinload(GalvanizationLoadItem.proposal_item),
            selectinload(GalvanizationLoad.events),
        )
        .where(GalvanizationLoad.id == load_id)
        .execution_options(populate_existing=True)
    )
    if for_update:
        stmt = stmt.with_for_update()
    load = (
        (await session.execute(stmt))
        .scalars()
        .unique()
        .first()
    )
    if load is None:
        raise ApiError(error_codes.GALVANIZATION_LOAD_NOT_FOUND, "Carga de galvanizacao nao encontrada.", status_code=404)
    return load


async def _replace_galvanization_load_items(
    session: AsyncSession,
    load: GalvanizationLoad,
    items_payload,
    actor: User,
    *,
    request_id: str | None,
) -> dict:
    """Aplica somente o delta da composicao e recalcula todas as propostas afetadas."""

    payload_by_item_id = {}
    for payload in items_payload:
        item_id = int(payload.proposal_item_id)
        if item_id in payload_by_item_id:
            raise ApiError(error_codes.GALVANIZATION_ITEM_DUPLICATED, "Item duplicado na carga.", status_code=409)
        payload_by_item_id[item_id] = payload

    existing_items = (
        await session.execute(
            select(GalvanizationLoadItem)
            .where(GalvanizationLoadItem.load_id == load.id)
            .order_by(GalvanizationLoadItem.proposal_item_id)
        )
    ).scalars().all()
    existing_by_item_id = {int(item.proposal_item_id): item for item in existing_items}
    items_before = [_galvanization_load_item_audit_snapshot(item) for item in existing_items]
    old_item_ids = set(existing_by_item_id)
    new_item_ids = set(payload_by_item_id)
    removed_item_ids = old_item_ids - new_item_ids
    added_item_ids = new_item_ids - old_item_ids
    unchanged_item_ids = old_item_ids & new_item_ids

    # A mesma linha de ProposalItem e a unidade de saldo. O bloqueio ordenado faz
    # duas cargas concorrentes serializarem a revalidacao da disponibilidade.
    involved_item_ids = sorted(old_item_ids | new_item_ids)
    locked_items = []
    if involved_item_ids:
        locked_items = (
            await session.execute(
                select(ProposalItem)
                .where(ProposalItem.id.in_(involved_item_ids))
                .order_by(ProposalItem.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalars().all()
    item_by_id = {int(item.id): item for item in locked_items}
    missing_item_ids = new_item_ids - set(item_by_id)
    if missing_item_ids:
        raise ApiError(error_codes.PROPOSAL_ITEM_NOT_FOUND, "Item da proposta nao encontrado.", status_code=404)

    affected_proposal_ids = {
        int(item.proposal_id) for item in existing_items
    } | {
        int(item_by_id[item_id].proposal_id) for item_id in new_item_ids
    }
    proposals = []
    if affected_proposal_ids:
        proposals = (
            await session.execute(
                select(Proposal)
                .options(selectinload(Proposal.items))
                .where(Proposal.id.in_(sorted(affected_proposal_ids)))
                .order_by(Proposal.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalars().unique().all()
    proposal_by_id = {int(proposal.id): proposal for proposal in proposals}
    proposal_states_before = {
        str(proposal_id): _galvanization_proposal_state_snapshot(proposal_by_id[proposal_id])
        for proposal_id in sorted(affected_proposal_ids)
    }

    normalized = {}
    for item_id in sorted(new_item_ids):
        payload = payload_by_item_id[item_id]
        item = item_by_id[item_id]
        proposal = proposal_by_id[int(item.proposal_id)]
        if payload.version is not None:
            _ensure_version(item.version, payload.version)
        _ensure_item_eligible_for_galvanization(proposal, item)
        available = await _galvanization_available_quantity(session, item, exclude_load_id=load.id)
        sent_qty = (payload.sent_quantity if payload.sent_quantity is not None else available).quantize(Decimal("0.0001"))
        if sent_qty <= Decimal("0") or sent_qty > available:
            raise ApiError(error_codes.GALVANIZATION_ITEM_NOT_ELIGIBLE, "Quantidade enviada excede o saldo disponivel para galvanizacao.", status_code=409)
        normalized[item_id] = (proposal, item, sent_qty, payload.notes)

    for item_id in sorted(removed_item_ids):
        await session.delete(existing_by_item_id[item_id])

    changed_item_ids: set[int] = set()
    resulting_items: list[GalvanizationLoadItem] = []
    for item_id in sorted(new_item_ids):
        proposal, item, sent_qty, notes = normalized[item_id]
        unit_weight = normalize_known_weight(item.unit_weight)
        sent_weight = calculate_known_weight(sent_qty, unit_weight)
        if item_id in existing_by_item_id:
            load_item = existing_by_item_id[item_id]
            changed = any(
                (
                    load_item.sent_quantity != sent_qty,
                    load_item.unit_weight != unit_weight,
                    load_item.sent_weight != sent_weight,
                    load_item.returned_quantity != Decimal("0"),
                    load_item.returned_weight != (None if sent_weight is None else Decimal("0")),
                    load_item.status != "AGUARDANDO_RETORNO",
                    load_item.returned_at is not None,
                    load_item.notes != notes,
                    not load_item.active,
                )
            )
            load_item.sent_quantity = sent_qty
            load_item.unit_weight = unit_weight
            load_item.sent_weight = sent_weight
            load_item.returned_quantity = Decimal("0")
            load_item.returned_weight = None if sent_weight is None else Decimal("0")
            load_item.status = "AGUARDANDO_RETORNO"
            load_item.returned_at = None
            load_item.notes = notes
            load_item.active = True
            if changed:
                changed_item_ids.add(item_id)
                _touch(load_item, actor)
        else:
            load_item = GalvanizationLoadItem(
                load_id=load.id,
                proposal_id=proposal.id,
                proposal_item_id=item.id,
                sent_quantity=sent_qty,
                unit_weight=unit_weight,
                sent_weight=sent_weight,
                returned_weight=None if sent_weight is None else Decimal("0"),
                notes=notes,
                created_by=actor.id,
                updated_by=actor.id,
            )
            session.add(load_item)
        resulting_items.append(load_item)

    load.total_weight = calculate_weight_coverage(item.sent_weight for item in resulting_items).known_weight
    await session.flush()

    proposal_states_after = {}
    for proposal_id in sorted(affected_proposal_ids):
        proposal = proposal_by_id[proposal_id]
        proposal_item_ids = {int(item.id) for item in proposal.items}
        proposal_delta = {
            "items_added": sorted(added_item_ids & proposal_item_ids),
            "items_removed": sorted(removed_item_ids & proposal_item_ids),
            "items_unchanged": sorted(unchanged_item_ids & proposal_item_ids),
            "items_updated": sorted(changed_item_ids & proposal_item_ids),
        }
        after_state = await _recalculate_proposal_after_load_change(
            session,
            proposal,
            actor,
            request_id=request_id,
            load_id=int(load.id),
            state_before=proposal_states_before[str(proposal_id)],
            delta=proposal_delta,
        )
        proposal_states_after[str(proposal_id)] = after_state

    items_after = [_galvanization_load_item_audit_snapshot(item) for item in resulting_items]
    return {
        "items_before": items_before,
        "items_after": items_after,
        "items_added": sorted(added_item_ids),
        "items_removed": sorted(removed_item_ids),
        "items_unchanged": sorted(unchanged_item_ids),
        "items_updated": sorted(changed_item_ids),
        "proposals_affected": sorted(affected_proposal_ids),
        "proposal_states_before": proposal_states_before,
        "proposal_states_after": proposal_states_after,
    }


def _galvanization_load_item_audit_snapshot(item: GalvanizationLoadItem) -> dict:
    return {
        "load_item_id": int(item.id) if item.id is not None else None,
        "proposal_id": int(item.proposal_id),
        "proposal_item_id": int(item.proposal_item_id),
        "sent_quantity": str(item.sent_quantity),
        "returned_quantity": str(item.returned_quantity),
        "status": item.status,
        "active": bool(item.active),
    }


def _galvanization_proposal_state_snapshot(proposal: Proposal) -> dict:
    return {
        "current_area": proposal.current_area,
        "current_status": proposal.current_status,
        "general_status": proposal.general_status,
        "production_status": proposal.production_status,
        "galvanization_status": proposal.galvanization_status,
        "shipping_status": proposal.shipping_status,
        "is_cancelled": bool(proposal.is_cancelled),
        "version": int(proposal.version),
    }


async def _recalculate_proposal_after_load_change(
    session: AsyncSession,
    proposal: Proposal,
    actor: User,
    *,
    request_id: str | None,
    load_id: int,
    state_before: dict,
    delta: dict,
) -> dict:
    """Projeta o estado da proposta a partir dos vinculos reais em todas as cargas."""

    if _proposal_is_cancelled(proposal):
        return _galvanization_proposal_state_snapshot(proposal)

    links = (
        await session.execute(
            select(
                GalvanizationLoad.status,
                GalvanizationLoadItem.sent_quantity,
                GalvanizationLoadItem.returned_quantity,
            )
            .join(GalvanizationLoad, GalvanizationLoad.id == GalvanizationLoadItem.load_id)
            .where(GalvanizationLoadItem.proposal_id == proposal.id)
            .where(GalvanizationLoadItem.active.is_(True))
            .where(GalvanizationLoad.active.is_(True))
            .where(GalvanizationLoadItem.sent_quantity > Decimal("0"))
            .where(GalvanizationLoad.status != "CANCELADA")
        )
    ).all()
    has_draft_link = any(status == "AGUARDANDO_LIBERACAO" for status, _sent, _returned in links)
    away_links = [
        (status, sent, returned)
        for status, sent, returned in links
        if status in GALVANIZATION_LOAD_RETURNABLE_STATUSES and sent > returned
    ]
    has_returned_quantity = any(returned > Decimal("0") for _status, _sent, returned in links)
    eligible_items = _eligible_galvanization_items(proposal)
    galvanization_items = [item for item in _active_items(proposal) if item.requires_galvanization == "SIM"]
    # Proposta mista: parte dos itens ja tem vinculo/elegibilidade de
    # galvanizacao, mas outro item interno (produce_internally=SIM) ainda
    # esta pendente de producao. A proposta so pode "sair" de PRODUCAO
    # quando TODOS os itens internos estiverem produzidos - mesma guarda que
    # complete_production_items ja aplica ao fechar producao parcial
    # (`if remaining: ...`) - senao _ensure_production_area passa a rejeitar
    # start/pause/resume/complete-items para essa proposta, travando o
    # restante da fabricacao so porque um item ja avancou para galvanizacao.
    # galvanization_status ainda reflete a realidade do(s) item(ns) ja
    # vinculados, so current_area/current_status/general_status ficam presos
    # em PRODUCAO ate o restante ser produzido.
    can_leave_production = not any(
        _loaded_item_balance(item).production_pending > 0 for item in _internal_items(proposal)
    )

    if has_draft_link:
        if can_leave_production:
            proposal.current_area = "GALVANIZACAO"
            proposal.current_status = "EM_CARGA"
            proposal.general_status = "EM_GALVANIZACAO"
        proposal.galvanization_status = "EM_CARGA"
    elif away_links:
        status = "RETORNOU_PARCIAL" if has_returned_quantity else "ENVIADO_GALVANIZACAO"
        if can_leave_production:
            proposal.current_area = "GALVANIZACAO"
            proposal.current_status = status
            proposal.general_status = "EM_GALVANIZACAO"
            if status == "RETORNOU_PARCIAL":
                proposal.shipping_status = proposal.shipping_status or "AGUARDANDO_SEPARACAO_PARCIAL"
        proposal.galvanization_status = status
    elif eligible_items:
        if can_leave_production:
            proposal.current_area = "GALVANIZACAO"
            proposal.current_status = "AGUARDANDO_ENVIO"
            proposal.general_status = "EM_GALVANIZACAO"
        proposal.galvanization_status = "AGUARDANDO_ENVIO"
    elif galvanization_items and all(item.galvanized for item in galvanization_items):
        if can_leave_production:
            proposal.current_area = "EXPEDICAO"
            proposal.current_status = "EM_SEPARACAO"
            proposal.general_status = "EM_EXPEDICAO"
            proposal.shipping_status = "EM_SEPARACAO"
        proposal.galvanization_status = "RETORNOU_GALVANIZACAO"

    state_after_without_version = _galvanization_proposal_state_snapshot(proposal)
    state_changed = any(
        state_before.get(field) != state_after_without_version.get(field)
        for field in ("current_area", "current_status", "general_status", "galvanization_status", "shipping_status")
    )
    if state_changed:
        _touch(proposal, actor)
    state_after = _galvanization_proposal_state_snapshot(proposal)
    await _record_event(
        session,
        proposal,
        "GALVANIZATION_PROPOSAL_LOAD_RECALCULATED",
        actor,
        request_id=request_id,
        from_area=state_before.get("current_area"),
        from_status=state_before.get("current_status"),
        to_area=proposal.current_area,
        to_status=proposal.current_status,
        metadata={
            "load_id": load_id,
            "delta": delta,
            "state_before": state_before,
            "state_after": state_after,
            "has_draft_link": has_draft_link,
            "has_released_pending_link": bool(away_links),
            "eligible_item_ids": [int(item.id) for item in eligible_items],
            "can_leave_production": can_leave_production,
            "cancelled_terminal_state_preserved": False,
        },
    )
    return state_after


def _ensure_item_eligible_for_galvanization(proposal: Proposal, item: ProposalItem) -> None:
    _ensure_proposal_not_cancelled(proposal)
    if not proposal.active or not item.active:
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
    _ensure_proposal_not_cancelled(proposal)
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
        proposal.shipping_status = "EM_SEPARACAO"
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
    item = (
        await session.execute(
            select(ProposalItem)
            .options(selectinload(ProposalItem.fiscal_item), selectinload(ProposalItem.expedition_item), selectinload(ProposalItem.galvanization_load_items))
            .where(ProposalItem.id == item_id)
        )
    ).scalars().first()
    if item is None:
        raise ApiError(error_codes.PROPOSAL_ITEM_NOT_FOUND, "Item da proposta nao encontrado.", status_code=404)
    return item


_WEIGHT_QUANTIZE = Decimal("0.0001")


async def _resolve_item_weight(
    session: AsyncSession,
    *,
    proposal_number: str | None,
    product_code: str | None,
    quantity: Decimal,
    explicit_unit_weight: Decimal | None,
) -> dict:
    """Camada unica de resolucao de peso: cadastro manual, PDF e API convergem aqui.

    Peso digitado explicitamente e sempre respeitado (fonte MANUAL) e nunca
    sobrescrito silenciosamente por uma resolucao Nomus posterior. Sem peso
    manual e sem resolucao possivel, o item fica PENDING - nunca 0 kg.
    """
    explicit_unit_weight = normalize_known_weight(explicit_unit_weight)
    if explicit_unit_weight is not None:
        return {
            "unit_weight": explicit_unit_weight,
            "total_weight": calculate_known_weight(quantity, explicit_unit_weight),
            "weight_source": "MANUAL",
            "weight_status": "MANUAL",
            "nomus_product_id": None,
            "weight_synced_at": None,
        }

    code = product_catalog_service.normalize_product_code(product_code)
    if not code:
        return {
            "unit_weight": None,
            "total_weight": None,
            "weight_source": "NONE",
            "weight_status": "PENDING",
            "nomus_product_id": None,
            "weight_synced_at": None,
        }

    resolved = await product_catalog_service.resolve_weights(session, proposal_number=proposal_number, codes=[code])
    result = resolved.get(code)
    if result is None or result.net_unit_weight is None:
        status = result.status if result is not None else product_catalog_service.STATUS_PENDING
        return {
            "unit_weight": None,
            "total_weight": None,
            "weight_source": "NONE",
            "weight_status": status,
            "nomus_product_id": None,
            "weight_synced_at": None,
        }
    return {
        "unit_weight": result.net_unit_weight,
        "total_weight": calculate_known_weight(quantity, result.net_unit_weight),
        "weight_source": "CATALOGO" if result.source == product_catalog_service.SOURCE_CACHE else "NOMUS",
        "weight_status": product_catalog_service.STATUS_SYNCED,
        "nomus_product_id": None,
        "weight_synced_at": datetime.now(UTC),
    }


async def _new_item(session: AsyncSession, proposal_id: int, proposal_number: str | None, payload: ProposalItemCreate, actor: User) -> ProposalItem:
    produce = _flag_value(payload.produce_internally)
    galvanization = _flag_value(payload.requires_galvanization)
    weight = await _resolve_item_weight(
        session,
        proposal_number=proposal_number,
        product_code=payload.product_code,
        quantity=payload.quantity,
        explicit_unit_weight=payload.unit_weight,
    )
    return ProposalItem(
        proposal_id=proposal_id,
        item_number=payload.item_number,
        product_code=payload.product_code,
        description=payload.description,
        quantity=payload.quantity,
        unit=payload.unit,
        unit_weight=weight["unit_weight"],
        total_weight=weight["total_weight"],
        weight_source=weight["weight_source"],
        weight_status=weight["weight_status"],
        nomus_product_id=weight["nomus_product_id"],
        weight_synced_at=weight["weight_synced_at"],
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
    logger.debug("Validando versao: recebida=%r atual=%r", expected, current)
    if current != expected:
        raise ApiError(error_codes.PROPOSAL_VERSION_CONFLICT, "A proposta ou item foi alterado por outro usuario. Recarregue os dados.", status_code=409)


def _ensure_production_area(proposal: Proposal) -> None:
    _ensure_proposal_not_cancelled(proposal)
    has_reallocated_pending = any(
        _loaded_item_balance(item).production_reallocated_in_pending > 0
        for item in _active_items(proposal)
    )
    if proposal.current_area != "PRODUCAO" and not has_reallocated_pending:
        raise ApiError(error_codes.PRODUCTION_INVALID_STATE, "A proposta ainda nao esta na Producao oficial.", status_code=409)


def _production_status_value(status: str | None) -> str:
    return ProductionStateMachine.normalize(status)


def _production_sort_key(proposal: Proposal) -> int:
    return PRODUCTION_SORT_STATUS.get(_production_status_value(proposal.production_status or proposal.current_status), 100)


def _active_items(proposal: Proposal) -> list[ProposalItem]:
    return [item for item in proposal.items if item.active]


def _consolidated_active_items(proposal: Proposal) -> list[ProposalItem]:
    """Itens da unidade operacional exibida.

    Para a mãe, os itens próprios e os itens das filhas formam uma única
    visão de resumo. Para uma filha, a lista permanece isolada para que uma
    ação nunca alcance itens de outra unidade.
    """
    items = _active_items(proposal)
    if proposal.parent_proposal_id is not None:
        return items
    children = proposal.__dict__.get("partial_children") or []
    return items + [item for child in children if child.active and not child.is_cancelled for item in _active_items(child)]


def _loaded_item_balance(item: ProposalItem):
    sent = sum((quantity(row.quantity) for row in item.production_allocations_sent), Decimal("0"))
    received_pending = sum(
        (quantity(row.quantity - row.completed_quantity) for row in item.production_allocations_received if row.status != "COMPLETED"),
        Decimal("0"),
    )
    received_completed = sum(
        (quantity(row.completed_quantity) for row in item.production_allocations_received),
        Decimal("0"),
    )
    expedition = item.expedition_item
    return calculate_item_balance(
        requested=item.quantity,
        produced=item.produced,
        produce_internally=item.produce_internally,
        expedition_available=expedition.available_quantity if expedition else 0,
        delivered=expedition.delivered_quantity if expedition else 0,
        remanaged_out=expedition.remanaged_quantity if expedition else 0,
        production_reallocated_out=sent,
        production_reallocated_in_pending=received_pending,
        production_reallocated_in_completed=received_completed,
    )


def _internal_items(proposal: Proposal) -> list[ProposalItem]:
    return [item for item in _active_items(proposal) if item.produce_internally == "SIM"]


def _items_by_id(proposal: Proposal) -> dict[int, ProposalItem]:
    return {int(item.id): item for item in _active_items(proposal)}


def _undefined_flow_items(proposal: Proposal) -> list[ProposalItem]:
    return [
        item for item in _active_items(proposal)
        if not item.flow_defined
        or item.produce_internally == "INDEFINIDO"
        or item.requires_galvanization == "INDEFINIDO"
    ]


def _production_item_requires_attention(item: ProposalItem) -> bool:
    return (
        not item.flow_defined
        or item.produce_internally == "INDEFINIDO"
        or item.requires_galvanization == "INDEFINIDO"
        or _loaded_item_balance(item).production_pending > 0
    )


def _production_queue_items(proposal: Proposal) -> list[ProposalItem]:
    return [
        item for item in _active_items(proposal)
        if item.produce_internally == "SIM"
        or not item.flow_defined
        or item.produce_internally == "INDEFINIDO"
        or item.requires_galvanization == "INDEFINIDO"
    ]


def _production_progress(proposal: Proposal) -> ProductionProgress:
    items = _consolidated_active_items(proposal)
    internal = _internal_items(proposal)
    produced_internal = [item for item in internal if item.produced]
    balances = {item.id: _loaded_item_balance(item) for item in internal}
    pending = [item for item in internal if balances[item.id].production_pending > 0]
    undefined = _undefined_flow_items(proposal)
    missing_weight = [item for item in items if normalize_known_weight(item.unit_weight) is None]
    needs_galv = [item for item in items if item.requires_galvanization == "SIM"]
    no_galv = [item for item in items if item.requires_galvanization == "NAO"]
    coverage = calculate_weight_coverage(item.total_weight for item in items)
    total_weight = coverage.known_weight
    produced_weight = calculate_weight_coverage(item.total_weight for item in items if item.produced).known_weight
    pending_weight = calculate_weight_coverage(item.total_weight for item in pending).known_weight
    reallocated_pending = sum((balance.production_reallocated_in_pending for balance in balances.values()), Decimal("0")).quantize(Decimal("0.0001"))
    reallocated_completed = sum((balance.production_reallocated_in_completed for balance in balances.values()), Decimal("0")).quantize(Decimal("0.0001"))
    status = _production_status_value(proposal.production_status or proposal.current_status)
    if pending:
        status = "FINALIZADO_PARCIAL"
    elif internal and len(produced_internal) == len(internal):
        status = "FINALIZADO"
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
        reallocated_production_pending=reallocated_pending,
        reallocated_production_completed=reallocated_completed,
        weight_known_items=coverage.known_items,
        weight_total_items=coverage.total_items,
        weight_complete=coverage.complete,
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
        "NAO_DEFINIDO": 0,
        "AGUARDANDO_CONFIRMACAO": 1,
        "EM_SEPARACAO": 2,
        "SEPARADO": 3,
        "ALMOXARIFADO_ENTREGUE_PARCIAL": 4,
        "SEM_PARAFUSOS": 5,
        "ALMOXARIFADO_ENTREGUE": 6,
    }
    return order.get(proposal.warehouse_status or "NAO_DEFINIDO", 99)


def _warehouse_proposal_summary(proposal: Proposal) -> WarehouseProposalSummary:
    active_items = _active_items(proposal)
    coverage = calculate_weight_coverage(item.total_weight for item in active_items)
    return WarehouseProposalSummary(
        id=proposal.id,
        proposal_number=proposal.proposal_number,
        customer_name=proposal.customer_name,
        project_name=proposal.project_name,
        lot=proposal.lot,
        current_area=proposal.current_area,
        current_status=proposal.current_status,
        warehouse_status=proposal.warehouse_status or "NAO_DEFINIDO",
        warehouse_required=_warehouse_required_value(proposal.warehouse_status),
        general_status=proposal.general_status,
        shipping_status=proposal.shipping_status,
        total_items=len(active_items),
        total_weight=coverage.known_weight,
        weight_known_items=coverage.known_items,
        weight_total_items=coverage.total_items,
        weight_complete=coverage.complete,
        updated_at=proposal.updated_at,
        version=proposal.version,
    )


def _partial_stage(proposal: Proposal) -> str:
    if proposal.production_status in {"FINALIZADO_PARCIAL", "ITEM_PENDENTE_FABRICACAO"} or proposal.has_production_pending:
        return "PRODUCAO"
    if proposal.galvanization_status in {"DISPONIVEL_PARCIAL", "RETORNOU_PARCIAL"}:
        return "GALVANIZACAO"
    if proposal.shipping_status in {"AGUARDANDO_SEPARACAO_PARCIAL", "SEPARADO_COM_PENDENCIA", "ENTREGUE_PARCIAL"}:
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
    coverage = calculate_weight_coverage(item.total_weight for item in active_items)
    total_weight = coverage.known_weight
    produced_weight = calculate_weight_coverage(item.total_weight for item in produced_items).known_weight
    production_pending_weight = calculate_weight_coverage(item.total_weight for item in production_pending_items).known_weight
    galvanization_sent_weight = calculate_weight_coverage(item.sent_weight for item in active_load_items).known_weight
    galvanization_returned_weight = calculate_weight_coverage(item.returned_weight for item in active_load_items).known_weight
    load_galvanization_pending_weight = (galvanization_sent_weight - galvanization_returned_weight).quantize(Decimal("0.0001"))
    proposal_galvanization_pending_weight = calculate_weight_coverage(item.total_weight for item in proposal_galvanization_pending_items).known_weight
    galvanization_pending_weight = max(load_galvanization_pending_weight, proposal_galvanization_pending_weight).quantize(Decimal("0.0001"))
    expedition_delivered_weight = calculate_weight_coverage(
        calculate_known_weight(item.delivered_quantity, item.proposal_item.unit_weight) for item in active_expedition_items
    ).known_weight
    expedition_pending_weight = calculate_weight_coverage(
        calculate_known_weight(item.available_quantity - item.delivered_quantity - item.remanaged_quantity, item.proposal_item.unit_weight)
        for item in expedition_pending_items
    ).known_weight
    fiscal_billed_weight = sum((item.billed_weight for item in fiscal_items), Decimal("0")).quantize(Decimal("0.0001"))
    fiscal_pending_weight = sum(
        ((item.total_weight - item.billed_weight) for item in fiscal_pending_items if item.total_weight is not None),
        Decimal("0"),
    ).quantize(Decimal("0.0001"))
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
        weight_known_items=coverage.known_items,
        weight_total_items=coverage.total_items,
        weight_complete=coverage.complete,
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
    elif status == ProductionStateMachine.PAUSED:
        actions.append({"id": "RESUME_PRODUCTION", "label": "Retomar producao", "enabled": True})
    elif status == ProductionStateMachine.STARTED:
        actions.append({"id": "PAUSE_PRODUCTION", "label": "Pausar producao", "enabled": True})
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
    if _undefined_flow_items(proposal):
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
    elif not pending:
        _finalize_production_destination(proposal)
    elif status in {"FINALIZADO_PARCIAL", "ITEM_PENDENTE_FABRICACAO"}:
        proposal.production_status = "INICIADO"
        proposal.current_status = "INICIADO"
        proposal.flow_situation = "NORMAL"
        proposal.has_production_pending = False


def _finalize_production_destination(proposal: Proposal, *, items: list[ProposalItem] | None = None) -> None:
    destination_items = items if items is not None else _active_items(proposal)
    proposal.production_status = "FINALIZADO"
    proposal.has_production_pending = False
    proposal.flow_situation = "NORMAL"
    if any(item.requires_galvanization == "SIM" and item.produced for item in destination_items):
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


async def _request_event_exists(
    session: AsyncSession,
    request_id: str | None,
    *,
    proposal_id: int | None = None,
    event_type: str,
    load_id: int | None = None,
) -> bool:
    """Consulta replay da mesma operação antes de validar a versão.

    A combinação request_id + operação + alvo impede que uma repetição causada
    por timeout duplique produção ou retorno, mas não transforma request_ids
    diferentes em idempotentes.
    """
    if not request_id:
        return False
    if load_id is not None:
        stmt = select(GalvanizationLoadEvent.id).where(
            GalvanizationLoadEvent.load_id == load_id,
            GalvanizationLoadEvent.request_id == request_id,
            GalvanizationLoadEvent.event_type == event_type,
        )
    else:
        stmt = select(ProposalEvent.id).where(
            ProposalEvent.proposal_id == proposal_id,
            ProposalEvent.request_id == request_id,
            ProposalEvent.event_type == event_type,
        )
    return (await session.execute(stmt.limit(1))).scalar_one_or_none() is not None


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
    security_details = {
        "proposal_id": proposal.id,
        "item_id": item_id,
        "from_area": from_area,
        "from_status": from_status,
        "to_area": to_area,
        "to_status": to_status,
    }
    if metadata:
        security_details["metadata"] = metadata
    await auth_repository.create_security_event(
        session,
        event_type,
        actor_user_id=actor.id,
        request_id=request_id,
        details=security_details,
    )


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
    security_details = {
        "load_id": load.id,
        "load_item_id": load_item.id if load_item is not None else None,
    }
    if metadata:
        security_details["metadata"] = metadata
    await auth_repository.create_security_event(
        session,
        event_type,
        actor_user_id=actor.id,
        request_id=request_id,
        details=security_details,
    )


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
        await _resolve_legacy_parent_links(session)
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


async def _resolve_legacy_parent_links(session: AsyncSession) -> int:
    """Vincula filhas legadas ao registro-mae canonico dentro da mesma transacao.

    Importacoes antigas carregavam apenas ``parent_legacy_id``. Enquanto o
    vinculo relacional nao existia, a filha podia aparecer indevidamente como
    proposta principal e escapar da consolidacao operacional.
    """
    candidates = (
        await session.execute(
            select(Proposal)
            .where(Proposal.parent_proposal_id.is_(None))
            .where(Proposal.parent_legacy_id.is_not(None))
        )
    ).scalars().all()
    if not candidates:
        return 0
    legacy_ids = {int(row.parent_legacy_id) for row in candidates if row.parent_legacy_id is not None}
    parents = (
        await session.execute(select(Proposal).where(Proposal.legacy_id.in_(legacy_ids)))
    ).scalars().all()
    by_legacy = {int(row.legacy_id): row for row in parents if row.legacy_id is not None}
    linked = 0
    for child in candidates:
        parent = by_legacy.get(int(child.parent_legacy_id)) if child.parent_legacy_id is not None else None
        if parent is None or parent.id == child.id:
            continue
        child.parent_proposal_id = parent.id
        linked += 1
    return linked


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
        elif _proposal_is_cancelled(existing):
            summary.unchanged += 1
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
        if _proposal_is_cancelled(proposal):
            summary.unchanged += 1
            return
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


async def _resolve_proposal_items_by_legacy_id(session: AsyncSession, legacy_ids: set[int]) -> dict[int, ProposalItem]:
    if not legacy_ids:
        return {}
    rows = (await session.execute(select(ProposalItem).where(ProposalItem.legacy_id.in_(legacy_ids)))).scalars().all()
    return {int(row.legacy_id): row for row in rows if row.legacy_id is not None}


async def _resolve_proposals_by_legacy_id(session: AsyncSession, legacy_ids: set[int]) -> dict[int, Proposal]:
    if not legacy_ids:
        return {}
    rows = (await session.execute(select(Proposal).where(Proposal.legacy_id.in_(legacy_ids)))).scalars().all()
    return {int(row.legacy_id): row for row in rows if row.legacy_id is not None}


async def sync_galvanization_batch(session: AsyncSession, batch: GalvanizationSyncBatch, actor: User, *, request_id: str | None) -> SyncSummary:
    errors = _validate_galvanization_batch(batch)
    if errors:
        return SyncSummary(received=len(batch.loads), rejected=len(errors), errors=errors, dry_run=batch.dry_run)
    if batch.dry_run:
        return await _simulate_galvanization(session, batch)

    locked = bool((await session.execute(text("SELECT pg_try_advisory_xact_lock(:lock_id)").bindparams(lock_id=GALVANIZATION_SYNC_LOCK_ID))).scalar_one())
    if not locked:
        raise ApiError(error_codes.SYNC_ALREADY_RUNNING, "Ja existe sincronizacao de galvanizacao em andamento.", status_code=409)

    run = SyncRun(sync_type="galvanization", status="RUNNING", source_identifier=batch.source_identifier, actor_user_id=actor.id, request_id=request_id)
    session.add(run)
    await session.flush()
    await auth_repository.create_security_event(session, "GALVANIZATION_SYNC_STARTED", actor_user_id=actor.id, request_id=request_id, details={"sync_run_id": run.id, "received": len(batch.loads)})

    summary = SyncSummary(received=len(batch.loads), dry_run=False, sync_run_id=run.id)
    try:
        item_legacy_ids = {item.proposal_item_legacy_id for load in batch.loads for item in load.items}
        items_by_legacy_id = await _resolve_proposal_items_by_legacy_id(session, item_legacy_ids)
        for payload in batch.loads:
            await _upsert_galvanization_load(session, payload, items_by_legacy_id, summary)
        run.status = "COMPLETED" if not summary.errors else "PARTIAL"
        run.finished_at = datetime.now(UTC)
        _copy_counts(run, summary)
        run.details = {"batch_number": batch.batch_number, "batch_total": batch.batch_total, "errors": summary.errors[:20]}
        event = "GALVANIZATION_SYNC_COMPLETED" if run.status == "COMPLETED" else "GALVANIZATION_SYNC_PARTIAL"
        await auth_repository.create_security_event(session, event, actor_user_id=actor.id, request_id=request_id, details={"sync_run_id": run.id, "received": summary.received, "created": summary.created, "updated": summary.updated, "unchanged": summary.unchanged, "rejected": summary.rejected})
        await session.commit()
        return summary
    except Exception as exc:
        await session.rollback()
        raise ApiError(error_codes.SYNC_BATCH_FAILED, "Nao foi possivel sincronizar o lote de galvanizacao.", status_code=422) from exc


def _validate_galvanization_batch(batch: GalvanizationSyncBatch) -> list[str]:
    errors: list[str] = []
    legacy_ids: set[int] = set()
    for load in batch.loads:
        if load.legacy_id in legacy_ids:
            errors.append(f"carga legacy_id duplicado no lote: {load.legacy_id}")
        legacy_ids.add(load.legacy_id)
        item_ids: set[int] = set()
        for item in load.items:
            if item.proposal_item_legacy_id in item_ids:
                errors.append(f"item legacy_id duplicado na carga {load.legacy_id}: {item.proposal_item_legacy_id}")
            item_ids.add(item.proposal_item_legacy_id)
    return errors


async def _simulate_galvanization(session: AsyncSession, batch: GalvanizationSyncBatch) -> SyncSummary:
    summary = SyncSummary(received=len(batch.loads), dry_run=True)
    for payload in batch.loads:
        existing = (await session.execute(select(GalvanizationLoad).where(GalvanizationLoad.legacy_id == payload.legacy_id))).scalars().first()
        if existing is None:
            summary.created += 1
        else:
            summary.updated += 1
    return summary


async def _upsert_galvanization_load(session: AsyncSession, payload: GalvanizationLoadSyncPayload, items_by_legacy_id: dict[int, ProposalItem], summary: SyncSummary) -> None:
    existing = (await session.execute(select(GalvanizationLoad).options(selectinload(GalvanizationLoad.items)).where(GalvanizationLoad.legacy_id == payload.legacy_id))).scalars().first()
    if existing is None:
        load = GalvanizationLoad(code=f"CGLEGADO{payload.legacy_id:05d}")
        session.add(load)
        summary.created += 1
        existing_items: list[GalvanizationLoadItem] = []
    else:
        load = existing
        existing_items = list(existing.items)
        summary.updated += 1
    _apply_galvanization_load(load, payload)
    await session.flush()
    for item_payload in payload.items:
        proposal_item = items_by_legacy_id.get(item_payload.proposal_item_legacy_id)
        if proposal_item is None:
            summary.errors.append(f"item legado {item_payload.proposal_item_legacy_id} nao encontrado na carga {payload.legacy_id}")
            continue
        item = next((candidate for candidate in existing_items if candidate.proposal_item_id == proposal_item.id), None)
        if item is None:
            item = GalvanizationLoadItem(load_id=load.id, proposal_id=proposal_item.proposal_id, proposal_item_id=proposal_item.id)
            session.add(item)
            summary.item_created += 1
        else:
            summary.item_updated += 1
        _apply_galvanization_load_item(item, item_payload)


def _apply_galvanization_load(load: GalvanizationLoad, payload: GalvanizationLoadSyncPayload) -> None:
    for field in ("legacy_id", "driver_name", "max_weight", "total_weight", "status", "expected_return_date", "sent_at", "returned_at", "closed_at", "notes"):
        setattr(load, field, getattr(payload, field))


def _apply_galvanization_load_item(item: GalvanizationLoadItem, payload: GalvanizationLoadItemSyncPayload) -> None:
    for field in ("sent_quantity", "returned_quantity", "unit_weight", "sent_weight", "returned_weight", "status", "returned_at"):
        value = getattr(payload, field)
        if isinstance(value, Decimal):
            value = value.quantize(Decimal("0.0001"))
        setattr(item, field, value)


async def sync_fiscal_batch(session: AsyncSession, batch: FiscalSyncBatch, actor: User, *, request_id: str | None) -> SyncSummary:
    errors = _validate_fiscal_batch(batch)
    if errors:
        return SyncSummary(received=len(batch.records), rejected=len(errors), errors=errors, dry_run=batch.dry_run)
    if batch.dry_run:
        return await _simulate_fiscal(session, batch)

    locked = bool((await session.execute(text("SELECT pg_try_advisory_xact_lock(:lock_id)").bindparams(lock_id=FISCAL_SYNC_LOCK_ID))).scalar_one())
    if not locked:
        raise ApiError(error_codes.SYNC_ALREADY_RUNNING, "Ja existe sincronizacao fiscal em andamento.", status_code=409)

    run = SyncRun(sync_type="fiscal", status="RUNNING", source_identifier=batch.source_identifier, actor_user_id=actor.id, request_id=request_id)
    session.add(run)
    await session.flush()
    await auth_repository.create_security_event(session, "FISCAL_SYNC_STARTED", actor_user_id=actor.id, request_id=request_id, details={"sync_run_id": run.id, "received": len(batch.records)})

    summary = SyncSummary(received=len(batch.records), dry_run=False, sync_run_id=run.id)
    try:
        proposal_legacy_ids = {record.proposal_legacy_id for record in batch.records}
        proposals_by_legacy_id = await _resolve_proposals_by_legacy_id(session, proposal_legacy_ids)
        item_legacy_ids = {
            item.proposal_item_legacy_id
            for record in batch.records
            for item in record.items
        } | {
            invoice_item.proposal_item_legacy_id
            for record in batch.records
            for invoice in record.invoices
            for invoice_item in invoice.items
        }
        items_by_legacy_id = await _resolve_proposal_items_by_legacy_id(session, item_legacy_ids)
        for payload in batch.records:
            await _upsert_fiscal_record(session, payload, proposals_by_legacy_id, items_by_legacy_id, summary)
        run.status = "COMPLETED" if not summary.errors else "PARTIAL"
        run.finished_at = datetime.now(UTC)
        _copy_counts(run, summary)
        run.details = {"batch_number": batch.batch_number, "batch_total": batch.batch_total, "errors": summary.errors[:20]}
        event = "FISCAL_SYNC_COMPLETED" if run.status == "COMPLETED" else "FISCAL_SYNC_PARTIAL"
        await auth_repository.create_security_event(session, event, actor_user_id=actor.id, request_id=request_id, details={"sync_run_id": run.id, "received": summary.received, "created": summary.created, "updated": summary.updated, "unchanged": summary.unchanged, "rejected": summary.rejected})
        await session.commit()
        return summary
    except Exception as exc:
        await session.rollback()
        raise ApiError(error_codes.SYNC_BATCH_FAILED, "Nao foi possivel sincronizar o lote fiscal.", status_code=422) from exc


def _validate_fiscal_batch(batch: FiscalSyncBatch) -> list[str]:
    errors: list[str] = []
    legacy_ids: set[int] = set()
    for record in batch.records:
        if record.legacy_id in legacy_ids:
            errors.append(f"registro fiscal legacy_id duplicado no lote: {record.legacy_id}")
        legacy_ids.add(record.legacy_id)
    return errors


async def _simulate_fiscal(session: AsyncSession, batch: FiscalSyncBatch) -> SyncSummary:
    summary = SyncSummary(received=len(batch.records), dry_run=True)
    proposal_legacy_ids = {record.proposal_legacy_id for record in batch.records}
    proposals_by_legacy_id = await _resolve_proposals_by_legacy_id(session, proposal_legacy_ids)
    for payload in batch.records:
        proposal = proposals_by_legacy_id.get(payload.proposal_legacy_id)
        if proposal is None:
            summary.errors.append(f"proposta legada {payload.proposal_legacy_id} nao encontrada para o registro fiscal {payload.legacy_id}")
            continue
        existing = (await session.execute(select(FiscalRecord).where(FiscalRecord.proposal_id == proposal.id))).scalars().first()
        if existing is None:
            summary.created += 1
        else:
            summary.updated += 1
    return summary


async def _upsert_fiscal_record(
    session: AsyncSession,
    payload: FiscalRecordSyncPayload,
    proposals_by_legacy_id: dict[int, Proposal],
    items_by_legacy_id: dict[int, ProposalItem],
    summary: SyncSummary,
) -> None:
    proposal = proposals_by_legacy_id.get(payload.proposal_legacy_id)
    if proposal is None:
        summary.errors.append(f"proposta legada {payload.proposal_legacy_id} nao encontrada para o registro fiscal {payload.legacy_id}")
        return

    # Casa por proposal_id (UNIQUE em fiscal_records), nao por legacy_id: um
    # FiscalRecord pode ja existir sem legacy_id (auto-provisionado por outro
    # fluxo de leitura da tela fiscal) antes desta sincronizacao rodar.
    existing = (
        await session.execute(
            select(FiscalRecord)
            .options(selectinload(FiscalRecord.items), selectinload(FiscalRecord.invoices).selectinload(FiscalInvoice.items))
            .where(FiscalRecord.proposal_id == proposal.id)
        )
    ).scalars().first()
    if existing is None:
        record = FiscalRecord(proposal_id=proposal.id)
        session.add(record)
        summary.created += 1
        existing_items: list[FiscalItem] = []
        existing_invoices: list[FiscalInvoice] = []
    else:
        record = existing
        existing_items = list(existing.items)
        existing_invoices = list(existing.invoices)
        summary.updated += 1
    _apply_fiscal_record(record, payload)
    record.proposal_id = proposal.id
    await session.flush()

    fiscal_items_by_proposal_item_id: dict[int, FiscalItem] = {int(item.proposal_item_id): item for item in existing_items}
    for item_payload in payload.items:
        proposal_item = items_by_legacy_id.get(item_payload.proposal_item_legacy_id)
        if proposal_item is None:
            summary.errors.append(f"item legado {item_payload.proposal_item_legacy_id} nao encontrado no registro fiscal {payload.legacy_id}")
            continue
        fiscal_item = fiscal_items_by_proposal_item_id.get(proposal_item.id)
        if fiscal_item is None:
            fiscal_item = FiscalItem(fiscal_record_id=record.id, proposal_id=proposal.id, proposal_item_id=proposal_item.id)
            session.add(fiscal_item)
            summary.item_created += 1
        else:
            summary.item_updated += 1
        _apply_fiscal_item(fiscal_item, item_payload)
        fiscal_items_by_proposal_item_id[proposal_item.id] = fiscal_item
    await session.flush()

    invoices_by_legacy_id: dict[int, FiscalInvoice] = {int(invoice.legacy_id): invoice for invoice in existing_invoices if invoice.legacy_id is not None}
    invoice_items_by_invoice_id: dict[int, dict[int, FiscalInvoiceItem]] = {
        invoice.id: {int(line.proposal_item_id): line for line in invoice.items} for invoice in existing_invoices
    }
    for invoice_payload in payload.invoices:
        invoice = invoices_by_legacy_id.get(invoice_payload.legacy_id)
        is_new_invoice = invoice is None
        if invoice is None:
            invoice = FiscalInvoice(fiscal_record_id=record.id, proposal_id=proposal.id)
            session.add(invoice)
        _apply_fiscal_invoice(invoice, invoice_payload)
        await session.flush()
        existing_invoice_items = {} if is_new_invoice else invoice_items_by_invoice_id.get(invoice.id, {})
        for invoice_item_payload in invoice_payload.items:
            proposal_item = items_by_legacy_id.get(invoice_item_payload.proposal_item_legacy_id)
            if proposal_item is None:
                summary.errors.append(f"item legado {invoice_item_payload.proposal_item_legacy_id} nao encontrado na emissao {invoice_payload.legacy_id}")
                continue
            fiscal_item = fiscal_items_by_proposal_item_id.get(proposal_item.id)
            if fiscal_item is None:
                summary.errors.append(f"item fiscal para {invoice_item_payload.proposal_item_legacy_id} nao encontrado no registro {payload.legacy_id}; linha de emissao {invoice_payload.legacy_id} pulada")
                continue
            invoice_line = existing_invoice_items.get(proposal_item.id)
            if invoice_line is None:
                invoice_line = FiscalInvoiceItem(
                    fiscal_invoice_id=invoice.id,
                    fiscal_item_id=fiscal_item.id,
                    proposal_id=proposal.id,
                    proposal_item_id=proposal_item.id,
                )
                session.add(invoice_line)
            invoice_line.quantity = invoice_item_payload.quantity.quantize(Decimal("0.0001"))
            invoice_line.weight = invoice_item_payload.weight.quantize(Decimal("0.0001")) if invoice_item_payload.weight is not None else None


def _apply_fiscal_record(record: FiscalRecord, payload: FiscalRecordSyncPayload) -> None:
    for field in ("legacy_id", "status_fiscal", "fiscal_situation", "entry_date", "last_emission_at", "invoice_withdrawn_at", "withdrawal_observation", "observation"):
        setattr(record, field, getattr(payload, field))


def _apply_fiscal_item(item: FiscalItem, payload: FiscalItemSyncPayload) -> None:
    for field in ("total_quantity", "billed_quantity", "total_weight", "billed_weight", "status"):
        value = getattr(payload, field)
        if isinstance(value, Decimal):
            value = value.quantize(Decimal("0.0001"))
        setattr(item, field, value)


def _apply_fiscal_invoice(invoice: FiscalInvoice, payload: FiscalInvoiceSyncPayload) -> None:
    for field in ("legacy_id", "invoice_number", "series", "issued_at", "emission_type", "observation", "source"):
        setattr(invoice, field, getattr(payload, field))


async def sync_expedition_backfill(session: AsyncSession, actor: User, *, request_id: str | None) -> SyncSummary:
    """Fecha ExpeditionItem para itens legados ja entregues (ProposalItem.delivered=True).

    Nao le o SQLite diretamente -- deriva do que a sincronizacao de propostas
    (sync_batch) ja gravou em ProposalItem.delivered/delivered_at. Itens
    produzidos mas ainda nao entregues nao precisam de linha explicita: o
    backfill preguicoso existente (_sync_expedition_from_available_items,
    chamado a cada leitura da tela de Expedicao) ja cuida deles a partir do
    estado de ProposalItem.
    """
    rows = (
        await session.execute(
            select(ProposalItem)
            .options(selectinload(ProposalItem.expedition_item))
            .where(ProposalItem.delivered.is_(True))
        )
    ).scalars().all()
    summary = SyncSummary(received=len(rows), dry_run=False)
    for item in rows:
        if item.expedition_item is not None:
            summary.unchanged += 1
            continue
        quantity = item.quantity.quantize(Decimal("0.0001"))
        session.add(
            ExpeditionItem(
                proposal_id=item.proposal_id,
                proposal_item_id=item.id,
                available_quantity=quantity,
                separated_quantity=quantity,
                delivered_quantity=quantity,
                origin="LEGADO",
                status="ENTREGUE",
                separated_at=item.delivered_at,
                delivered_at=item.delivered_at,
            )
        )
        summary.created += 1
    await auth_repository.create_security_event(session, "EXPEDITION_BACKFILL_COMPLETED", actor_user_id=actor.id, request_id=request_id, details={"created": summary.created, "unchanged": summary.unchanged})
    await session.commit()
    return summary
