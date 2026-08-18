from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.database.session import get_db_session
from api.app.modules.auth.dependencies import require_permission, require_superuser
from api.app.modules.auth.models import User
from api.app.modules.auth.permissions import (
    AUDIT_VIEW,
    EXPEDITION_UPDATE,
    EXPEDITION_VIEW,
    FISCAL_CANCEL_LINK,
    FISCAL_REGISTER_EMISSION,
    FISCAL_VIEW,
    GALVANIZATION_UPDATE,
    GALVANIZATION_VIEW,
    PROPOSAL_ITEMS_CREATE,
    PROPOSAL_ITEMS_DELETE,
    PROPOSAL_ITEMS_UPDATE,
    PROPOSAL_ITEMS_VIEW,
    PROPOSALS_CANCEL,
    PROPOSALS_CHANGE_STATUS,
    PROPOSALS_CREATE,
    PROPOSALS_DELETE,
    PROPOSALS_UPDATE,
    PROPOSALS_VIEW,
    PRODUCTION_UPDATE,
    PRODUCTION_VIEW,
)
from api.app.modules.proposals import service
from api.app.modules.proposals.schemas import (
    ExpeditionItemsRequest,
    ExpeditionProposalDetail,
    ExpeditionRemanagementDeliveryRequest,
    ExpeditionRemanageRequest,
    ExpeditionVersionRequest,
    FiscalCancelInvoiceItemRequest,
    FiscalBatchRequest,
    FiscalBatchResponse,
    FiscalIndicators,
    FiscalRecordDetail,
    FiscalRecordSummary,
    FiscalRegisterInvoiceRequest,
    FiscalWithdrawalRequest,
    GalvanizationLoadCreate,
    GalvanizationLoadDetail,
    GalvanizationLoadUpdate,
    GalvanizationLoadVersionRequest,
    GalvanizationReturnRequest,
    PaginatedGalvanizationCandidateResponse,
    PaginatedGalvanizationLoadResponse,
    PaginatedPartialProposalResponse,
    PaginatedExpeditionResponse,
    PaginatedFiscalResponse,
    PaginatedProposalResponse,
    PaginatedProductionItemResponse,
    PaginatedProductionResponse,
    PaginatedRemanagementResponse,
    PaginatedWarehouseProposalResponse,
    ProposalActivityItem,
    ProposalCancelRequest,
    ProposalAdministrativeCorrectionOptionsResponse,
    ProposalAdministrativeCorrectionPreviewRequest,
    ProposalAdministrativeCorrectionPreviewResponse,
    ProposalAdministrativeCorrectionRequest,
    ProposalCreate,
    ProposalDetail,
    ProposalHistoryItem,
    ProposalItemCreate,
    ProposalItemDetail,
    ProposalItemSummary,
    ProposalItemUpdate,
    ProposalStatusChangeRequest,
    ProposalUpdate,
    ProductionCompleteItemsRequest,
    ProductionItemFlowRequest,
    ProductionItemWeightsRequest,
    ProductionPauseRequest,
    ProductionProposalDetail,
    ProductionResumeRequest,
    ProductionStartRequest,
    RemanagementAvailabilityRequest,
    RemanagementAvailabilityResponse,
    RemanagementCompatibleItem,
    RemanagementCompensationPlanResponse,
    RemanagementCompensationRequest,
    RemanagementConfirmRequest,
    RemanagementConfirmResult,
    RemanagementDestinationItem,
    RemanagementPreview,
    RemanagementReviewRequest,
    RemanagementReviewResult,
    RemanagementSummary,
    WarehouseStatusRequest,
)


router = APIRouter(tags=["proposals"])


@router.get("/proposals", response_model=PaginatedProposalResponse)
async def list_proposals(
    proposal_number: str | None = Query(default=None, max_length=80),
    customer: str | None = Query(default=None, max_length=180),
    project: str | None = Query(default=None, max_length=180),
    current_area: str | None = Query(default=None, max_length=80),
    current_status: str | None = Query(default=None, max_length=120),
    is_partial: bool | None = None,
    is_cancelled: bool | None = None,
    is_completed: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    updated_after: datetime | None = None,
    sort_by: str = Query(default="updated_at", pattern="^(proposal_number|proposal_date|deadline_date|legacy_updated_at|synced_at|updated_at)$"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(PROPOSALS_VIEW)),
):
    return await service.list_proposals(
        session,
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
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
    )


@router.post("/proposals", response_model=ProposalDetail, status_code=status.HTTP_201_CREATED)
async def create_proposal(payload: ProposalCreate, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(PROPOSALS_CREATE))):
    return await service.create_proposal(session, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.patch("/proposals/{proposal_id}", response_model=ProposalDetail)
async def update_proposal(proposal_id: int, payload: ProposalUpdate, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(PROPOSALS_UPDATE))):
    return await service.update_proposal(session, proposal_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.post("/proposals/{proposal_id}/cancel", response_model=ProposalDetail)
async def cancel_proposal(proposal_id: int, payload: ProposalCancelRequest, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(PROPOSALS_CANCEL))):
    return await service.cancel_proposal(session, proposal_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.post("/proposals/{proposal_id}/status", response_model=ProposalDetail)
async def change_proposal_status(proposal_id: int, payload: ProposalStatusChangeRequest, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(PROPOSALS_CHANGE_STATUS))):
    return await service.change_proposal_status(session, proposal_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.post("/proposals/{proposal_id}/administrative-correction", response_model=ProposalDetail)
async def administrative_correction(proposal_id: int, payload: ProposalAdministrativeCorrectionRequest, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_superuser)):
    return await service.administrative_correction(session, proposal_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.get(
    "/proposals/{proposal_id}/administrative-corrections/options",
    response_model=ProposalAdministrativeCorrectionOptionsResponse,
)
async def administrative_correction_options(
    proposal_id: int,
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_superuser),
):
    return await service.get_allowed_administrative_corrections(session, proposal_id)


@router.post(
    "/proposals/{proposal_id}/administrative-corrections/preview",
    response_model=ProposalAdministrativeCorrectionPreviewResponse,
)
async def administrative_correction_preview(
    proposal_id: int,
    payload: ProposalAdministrativeCorrectionPreviewRequest,
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_superuser),
):
    return await service.preview_administrative_correction(session, proposal_id, payload)


@router.get("/production/proposals", response_model=PaginatedProductionResponse)
async def list_production_proposals(
    search: str | None = Query(default=None, max_length=180),
    status_filter: str | None = Query(default=None, alias="status", max_length=120),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(PRODUCTION_VIEW)),
):
    return await service.list_production_proposals(session, search=search, status=status_filter, limit=limit, offset=offset)


@router.get("/production/items", response_model=PaginatedProductionItemResponse)
async def list_production_items(
    search: str | None = Query(default=None, max_length=180),
    pending: bool | None = Query(default=None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(PRODUCTION_VIEW)),
):
    return await service.list_production_items(session, search=search, pending=pending, limit=limit, offset=offset)


@router.get("/partials/proposals", response_model=PaginatedPartialProposalResponse)
async def list_partial_proposals(
    search: str | None = Query(default=None, max_length=180),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(PROPOSALS_VIEW)),
):
    return await service.list_partial_proposals(session, search=search, limit=limit, offset=offset)


@router.get("/warehouse/proposals", response_model=PaginatedWarehouseProposalResponse)
async def list_warehouse_proposals(
    search: str | None = Query(default=None, max_length=180),
    status_filter: str | None = Query(default=None, alias="status", max_length=120),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(PROPOSALS_VIEW)),
):
    return await service.list_warehouse_proposals(session, search=search, status=status_filter, limit=limit, offset=offset)


@router.post("/warehouse/proposals/{proposal_id}/status")
async def update_warehouse_status(
    proposal_id: int,
    payload: WarehouseStatusRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(PROPOSALS_CHANGE_STATUS)),
):
    return await service.update_warehouse_status(session, proposal_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.get("/production/proposals/{proposal_id}", response_model=ProductionProposalDetail)
async def get_production_detail(proposal_id: int, session: AsyncSession = Depends(get_db_session), _actor: User = Depends(require_permission(PRODUCTION_VIEW))):
    return await service.get_production_detail(session, proposal_id)


@router.post("/production/proposals/{proposal_id}/start", response_model=ProductionProposalDetail)
async def start_production(proposal_id: int, payload: ProductionStartRequest, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(PRODUCTION_UPDATE))):
    return await service.start_production(session, proposal_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.post("/production/proposals/{proposal_id}/pause", response_model=ProductionProposalDetail)
async def pause_production(proposal_id: int, payload: ProductionPauseRequest, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(PRODUCTION_UPDATE))):
    return await service.pause_production(session, proposal_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.post("/production/proposals/{proposal_id}/resume", response_model=ProductionProposalDetail)
async def resume_production(proposal_id: int, payload: ProductionResumeRequest, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(PRODUCTION_UPDATE))):
    return await service.resume_production(session, proposal_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.patch("/production/proposals/{proposal_id}/item-flow", response_model=ProductionProposalDetail)
async def update_production_item_flow(proposal_id: int, payload: ProductionItemFlowRequest, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(PRODUCTION_UPDATE))):
    return await service.update_production_item_flow(session, proposal_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.patch("/production/proposals/{proposal_id}/item-weights", response_model=ProductionProposalDetail)
async def update_production_item_weights(proposal_id: int, payload: ProductionItemWeightsRequest, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(PRODUCTION_UPDATE))):
    return await service.update_production_item_weights(session, proposal_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.post("/production/proposals/{proposal_id}/complete-items", response_model=ProductionProposalDetail)
async def complete_production_items(proposal_id: int, payload: ProductionCompleteItemsRequest, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(PRODUCTION_UPDATE))):
    return await service.complete_production_items(session, proposal_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.get("/galvanization/candidates", response_model=PaginatedGalvanizationCandidateResponse)
async def list_galvanization_candidates(
    search: str | None = Query(default=None, max_length=180),
    situation: str | None = Query(default=None, pattern="^(DISPONIVEL|EM_GALVANIZACAO)$"),
    include_unavailable: bool = Query(default=False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(GALVANIZATION_VIEW)),
):
    return await service.list_galvanization_candidates(session, search=search, situation=situation, include_unavailable=include_unavailable, limit=limit, offset=offset)


@router.get("/galvanization/loads", response_model=PaginatedGalvanizationLoadResponse)
async def list_galvanization_loads(
    status_filter: str | None = Query(default=None, alias="status", max_length=80),
    search: str | None = Query(default=None, max_length=180),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(GALVANIZATION_VIEW)),
):
    return await service.list_galvanization_loads(session, status=status_filter, search=search, limit=limit, offset=offset)


@router.post("/galvanization/loads", response_model=GalvanizationLoadDetail, status_code=status.HTTP_201_CREATED)
async def create_galvanization_load(payload: GalvanizationLoadCreate, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(GALVANIZATION_UPDATE))):
    return await service.create_galvanization_load(session, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.get("/galvanization/loads/{load_id}", response_model=GalvanizationLoadDetail)
async def get_galvanization_load(load_id: int, session: AsyncSession = Depends(get_db_session), _actor: User = Depends(require_permission(GALVANIZATION_VIEW))):
    return await service.get_galvanization_load_detail(session, load_id)


@router.patch("/galvanization/loads/{load_id}", response_model=GalvanizationLoadDetail)
async def update_galvanization_load(load_id: int, payload: GalvanizationLoadUpdate, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(GALVANIZATION_UPDATE))):
    return await service.update_galvanization_load(session, load_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.post("/galvanization/loads/{load_id}/release", response_model=GalvanizationLoadDetail)
async def release_galvanization_load(load_id: int, payload: GalvanizationLoadVersionRequest, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(GALVANIZATION_UPDATE))):
    return await service.release_galvanization_load(session, load_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.post("/galvanization/loads/{load_id}/returns", response_model=GalvanizationLoadDetail)
async def register_galvanization_return(load_id: int, payload: GalvanizationReturnRequest, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(GALVANIZATION_UPDATE))):
    return await service.register_galvanization_return(session, load_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.post("/galvanization/loads/{load_id}/close", response_model=GalvanizationLoadDetail)
async def close_galvanization_load(load_id: int, payload: GalvanizationLoadVersionRequest, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(GALVANIZATION_UPDATE))):
    return await service.close_galvanization_load(session, load_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.get("/shipping/proposals", response_model=PaginatedExpeditionResponse)
async def list_expedition_proposals(
    search: str | None = Query(default=None, max_length=180),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(EXPEDITION_VIEW)),
):
    return await service.list_expedition_proposals(session, search=search, limit=limit, offset=offset)


@router.get("/shipping/proposals/{proposal_id}", response_model=ExpeditionProposalDetail)
async def get_expedition_detail(proposal_id: int, session: AsyncSession = Depends(get_db_session), _actor: User = Depends(require_permission(EXPEDITION_VIEW))):
    return await service.get_expedition_detail(session, proposal_id)


@router.post("/shipping/proposals/{proposal_id}/start-separation", response_model=ExpeditionProposalDetail)
async def start_expedition_separation(proposal_id: int, payload: ExpeditionVersionRequest, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(EXPEDITION_UPDATE))):
    return await service.start_expedition_separation(session, proposal_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.post("/shipping/proposals/{proposal_id}/separate-items", response_model=ExpeditionProposalDetail)
async def separate_expedition_items(proposal_id: int, payload: ExpeditionItemsRequest, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(EXPEDITION_UPDATE))):
    return await service.separate_expedition_items(session, proposal_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.post("/shipping/proposals/{proposal_id}/deliver-items", response_model=ExpeditionProposalDetail)
async def deliver_expedition_items(proposal_id: int, payload: ExpeditionItemsRequest, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(EXPEDITION_UPDATE))):
    return await service.deliver_expedition_items(session, proposal_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.post("/shipping/proposals/{proposal_id}/return-to-production", response_model=ExpeditionProposalDetail)
async def return_expedition_items_to_production(proposal_id: int, payload: ExpeditionRemanageRequest, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(EXPEDITION_UPDATE))):
    return await service.return_expedition_items_to_production(session, proposal_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.post("/shipping/remanagements/preview", response_model=RemanagementPreview)
async def preview_remanagement(payload: ExpeditionRemanagementDeliveryRequest, session: AsyncSession = Depends(get_db_session), _actor: User = Depends(require_permission(EXPEDITION_UPDATE))):
    return await service.simulate_remanagement(session, payload)


@router.post("/shipping/remanagements", response_model=RemanagementSummary, status_code=status.HTTP_201_CREATED)
async def create_remanagement(payload: ExpeditionRemanagementDeliveryRequest, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(EXPEDITION_UPDATE))):
    return await service.apply_remanagement(session, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.get("/shipping/remanagements/compatible-items", response_model=list[RemanagementCompatibleItem])
async def get_compatible_remanagement_items(source_proposal_id: int = Query(gt=0), destination_proposal_id: int = Query(gt=0), session: AsyncSession = Depends(get_db_session), _actor: User = Depends(require_permission(EXPEDITION_UPDATE))):
    return await service.compatible_remanagement_items(session, source_proposal_id, destination_proposal_id)


@router.get("/shipping/remanagements/destination-items", response_model=list[RemanagementDestinationItem])
async def get_remanagement_destination_items(destination_proposal_id: int = Query(gt=0), session: AsyncSession = Depends(get_db_session), _actor: User = Depends(require_permission(EXPEDITION_UPDATE))):
    return await service.remanagement_destination_items(session, destination_proposal_id)


@router.post("/shipping/remanagements/availability", response_model=RemanagementAvailabilityResponse)
async def get_remanagement_availability(payload: RemanagementAvailabilityRequest, session: AsyncSession = Depends(get_db_session), _actor: User = Depends(require_permission(EXPEDITION_UPDATE))):
    """Fase 3: busca somente leitura (POST por ter um corpo estruturado de
    itens/quantidades, mas nunca chama `session.commit()`)."""
    return await service.find_remanagement_sources(session, payload)


@router.post("/shipping/remanagements/compensation-plan", response_model=RemanagementCompensationPlanResponse)
async def get_remanagement_compensation_plan(payload: RemanagementCompensationRequest, session: AsyncSession = Depends(get_db_session), _actor: User = Depends(require_permission(EXPEDITION_UPDATE))):
    """Fase 5: motor de compensacao, somente leitura/simulacao - nunca chama
    `session.commit()`. Recebe o plano de alocacao (Fase 4) e devolve o plano
    de compensacao determinístico para a Fase 6 revisar."""
    return await service.build_remanagement_compensation_plan(session, payload)


@router.post("/shipping/remanagements/review", response_model=RemanagementReviewResult)
async def get_remanagement_review(payload: RemanagementReviewRequest, session: AsyncSession = Depends(get_db_session), _actor: User = Depends(require_permission(EXPEDITION_UPDATE))):
    """Fase 6: revisao/simulacao final, somente leitura - nunca chama
    `session.commit()`. Revalida saldos (mesma fonte da Fase 5) e valida o
    motivo antes de habilitar a confirmacao."""
    return await service.simulate_remanagement_review(session, payload)


@router.post("/shipping/remanagements/confirm", response_model=RemanagementConfirmResult, status_code=status.HTTP_201_CREATED)
async def confirm_remanagement(payload: RemanagementConfirmRequest, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(EXPEDITION_UPDATE))):
    """Fase 7: unico endpoint do novo fluxo que de fato grava no banco.
    Revalida tudo dentro de uma unica transacao (destino, cada origem
    distinta, cada saldo), trava as propostas envolvidas e persiste tudo ou
    nada. Idempotente por `operation_id` (retry seguro em caso de timeout de
    rede ou duplo clique)."""
    return await service.confirm_remanagement_batch(session, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.get("/shipping/remanagements", response_model=PaginatedRemanagementResponse)
async def get_remanagement_history(proposal_id: int | None = Query(default=None, gt=0), limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), session: AsyncSession = Depends(get_db_session), _actor: User = Depends(require_permission(EXPEDITION_VIEW))):
    return await service.list_remanagements(session, proposal_id=proposal_id, limit=limit, offset=offset)


@router.post("/shipping/proposals/{proposal_id}/deliver-by-remanagement", response_model=RemanagementSummary, deprecated=True)
async def deliver_proposal_by_remanagement(proposal_id: int, payload: ExpeditionRemanagementDeliveryRequest, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(EXPEDITION_UPDATE))):
    return await service.deliver_proposal_by_remanagement(session, proposal_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.get("/fiscal/records", response_model=PaginatedFiscalResponse)
async def list_fiscal_records(
    search: str | None = Query(default=None, max_length=180),
    status_filter: str | None = Query(default=None, alias="status", max_length=80),
    situation: str | None = Query(default=None, max_length=80),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(FISCAL_VIEW)),
):
    return await service.list_fiscal_records(session, search=search, status=status_filter, situation=situation, limit=limit, offset=offset)


@router.get("/fiscal/records/{fiscal_record_id}", response_model=FiscalRecordDetail)
async def get_fiscal_record(fiscal_record_id: int, session: AsyncSession = Depends(get_db_session), _actor: User = Depends(require_permission(FISCAL_VIEW))):
    return await service.get_fiscal_detail(session, fiscal_record_id)


@router.get("/fiscal/indicators", response_model=FiscalIndicators)
async def get_fiscal_indicators(session: AsyncSession = Depends(get_db_session), _actor: User = Depends(require_permission(FISCAL_VIEW))):
    return await service.fiscal_indicators(session)


@router.get("/fiscal/indicator-rows/{indicator}", response_model=list[FiscalRecordSummary])
async def get_fiscal_indicator_rows(indicator: str, session: AsyncSession = Depends(get_db_session), _actor: User = Depends(require_permission(FISCAL_VIEW))):
    return await service.fiscal_indicator_records(session, indicator)


@router.post("/fiscal/records/{fiscal_record_id}/invoices", response_model=FiscalRecordDetail, status_code=status.HTTP_201_CREATED)
async def register_fiscal_invoice(fiscal_record_id: int, payload: FiscalRegisterInvoiceRequest, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(FISCAL_REGISTER_EMISSION))):
    return await service.register_fiscal_invoice(session, fiscal_record_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.post("/fiscal/emissions/batch", response_model=FiscalBatchResponse, status_code=status.HTTP_201_CREATED)
async def register_fiscal_batch(payload: FiscalBatchRequest, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(FISCAL_REGISTER_EMISSION))):
    return await service.register_fiscal_batch(session, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.post("/fiscal/invoice-items/{invoice_item_id}/cancel", response_model=FiscalRecordDetail)
async def cancel_fiscal_invoice_item(invoice_item_id: int, payload: FiscalCancelInvoiceItemRequest, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(FISCAL_CANCEL_LINK))):
    return await service.cancel_fiscal_invoice_item(session, invoice_item_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.post("/fiscal/records/{fiscal_record_id}/withdrawal", response_model=FiscalRecordDetail)
async def mark_fiscal_invoice_withdrawn(fiscal_record_id: int, payload: FiscalWithdrawalRequest, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(FISCAL_REGISTER_EMISSION))):
    return await service.mark_fiscal_invoice_withdrawn(session, fiscal_record_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.post("/proposals/{proposal_id}/activate", response_model=ProposalDetail)
async def activate_proposal(proposal_id: int, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(PROPOSALS_DELETE))):
    return await service.set_proposal_active(session, proposal_id, True, actor, request_id=getattr(request.state, "request_id", None))


@router.post("/proposals/{proposal_id}/deactivate", response_model=ProposalDetail)
async def deactivate_proposal(proposal_id: int, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(PROPOSALS_DELETE))):
    return await service.set_proposal_active(session, proposal_id, False, actor, request_id=getattr(request.state, "request_id", None))


@router.get("/proposals/history", response_model=list[ProposalHistoryItem])
async def list_proposal_history(
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(AUDIT_VIEW)),
):
    return await service.list_proposal_history(session, limit=limit, offset=offset)


@router.get("/proposals/{proposal_id}/history", response_model=list[ProposalHistoryItem])
async def get_proposal_history(
    proposal_id: int,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(PROPOSALS_VIEW)),
):
    return await service.list_proposal_history(session, proposal_id=proposal_id, limit=limit, offset=offset)


@router.get("/proposals/{proposal_id}/activities", response_model=list[ProposalActivityItem])
async def get_proposal_activities(
    proposal_id: int,
    area: str | None = Query(default=None, max_length=80),
    before: datetime | None = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(PROPOSALS_VIEW)),
):
    """Feed operacional legivel da proposta (Atividade), separado do chat —
    reusa a mesma permissao de visualizacao da proposta ja usada pelo
    historico de auditoria (/proposals/{id}/history)."""
    return await service.list_proposal_activities(session, proposal_id, area=area, before=before, limit=limit)


@router.get("/proposals/{proposal_id}", response_model=ProposalDetail)
async def get_proposal(proposal_id: int, session: AsyncSession = Depends(get_db_session), _actor: User = Depends(require_permission(PROPOSALS_VIEW))):
    return service.proposal_detail(await service.get_proposal(session, proposal_id))


@router.get("/proposals/{proposal_id}/items", response_model=list[ProposalItemSummary])
async def list_proposal_items(proposal_id: int, session: AsyncSession = Depends(get_db_session), _actor: User = Depends(require_permission(PROPOSAL_ITEMS_VIEW))):
    return await service.list_items_for_proposal(session, proposal_id)


@router.post("/proposals/{proposal_id}/items", response_model=ProposalItemDetail, status_code=status.HTTP_201_CREATED)
async def create_proposal_item(proposal_id: int, payload: ProposalItemCreate, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(PROPOSAL_ITEMS_CREATE))):
    return await service.create_item(session, proposal_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.get("/proposal-items/{item_id}", response_model=ProposalItemDetail)
async def get_proposal_item(item_id: int, session: AsyncSession = Depends(get_db_session), _actor: User = Depends(require_permission(PROPOSAL_ITEMS_VIEW))):
    return await service.get_item(session, item_id)


@router.patch("/proposal-items/{item_id}", response_model=ProposalItemDetail)
async def update_proposal_item(item_id: int, payload: ProposalItemUpdate, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(PROPOSAL_ITEMS_UPDATE))):
    return await service.update_item(session, item_id, payload, actor, request_id=getattr(request.state, "request_id", None))


@router.delete("/proposal-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_proposal_item(item_id: int, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(PROPOSAL_ITEMS_DELETE))):
    await service.delete_item(session, item_id, actor, request_id=getattr(request.state, "request_id", None))
