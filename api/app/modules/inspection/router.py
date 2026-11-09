from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.database.session import get_db_session
from api.app.modules.auth.dependencies import require_permission
from api.app.modules.auth.models import User
from api.app.modules.auth.permissions import INSPECTION_EDIT, INSPECTION_VIEW
from api.app.modules.inspection import schemas, service

router = APIRouter(prefix="/inspections", tags=["inspection"])

_view = require_permission(INSPECTION_VIEW)
_edit = require_permission(INSPECTION_EDIT)


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("", response_model=schemas.InspectionList)
async def list_inspections(
    stage: str | None = Query(None, pattern="^(open|pendente|cadastro|solicitada|nqt|dispensa|inloco|doc|fim)$"),
    search: str | None = Query(None, max_length=120),
    limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session), _actor: User = Depends(_view),
):
    return await service.list_inspections(session, stage=stage, search=search, limit=limit, offset=offset)


@router.get("/finished", response_model=schemas.FinishedInspectionList)
async def list_finished(pd_code: str | None = Query(None, max_length=120), session: AsyncSession = Depends(get_db_session), _actor: User = Depends(_view)):
    return await service.list_finished(session, pd_code)


@router.get("/proposal-lookup", response_model=schemas.ProposalLookupOut)  # antes de /{inspection_id}
async def proposal_lookup(number: str = Query(..., max_length=120), session: AsyncSession = Depends(get_db_session), _actor: User = Depends(_view)):
    return await service.proposal_lookup(session, number)


@router.get("/proposals/{proposal_id}/pd-suggestion", response_model=schemas.PdSuggestionOut)
async def pd_suggestion(proposal_id: int, session: AsyncSession = Depends(get_db_session), _actor: User = Depends(_view)):
    return await service.pd_suggestion(session, proposal_id)


@router.post("/from-proposal", response_model=schemas.InspectionStartResult)
async def start_from_proposal(payload: schemas.InspectionFromProposal, request: Request, response: Response, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    result = await service.start_from_proposal(session, payload, actor, _rid(request))
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    return result


@router.get("/{inspection_id}", response_model=schemas.InspectionDetail)
async def get_inspection(inspection_id: int, session: AsyncSession = Depends(get_db_session), _actor: User = Depends(_view)):
    return await service.get_inspection(session, inspection_id)


@router.post("", response_model=schemas.InspectionDetail, status_code=status.HTTP_201_CREATED)
async def create_inspection(payload: schemas.InspectionCreate, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.create_inspection(session, payload, actor, _rid(request))


@router.post("/{inspection_id}/request", response_model=schemas.InspectionDetail)
async def request_inspection(inspection_id: int, payload: schemas.RequestPayload, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.request_inspection(session, inspection_id, payload, actor, _rid(request))


@router.post("/{inspection_id}/register-pd", response_model=schemas.InspectionDetail)
async def register_pd(inspection_id: int, request: Request, payload: schemas.TransitionPayload | None = None, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.register_pd(session, inspection_id, actor, _rid(request), payload)


@router.post("/{inspection_id}/nqt", response_model=schemas.InspectionDetail)
async def register_nqt(inspection_id: int, payload: schemas.NqtPayload, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.register_nqt(session, inspection_id, payload, actor, _rid(request))


@router.post("/{inspection_id}/decision", response_model=schemas.InspectionDetail)
async def register_decision(inspection_id: int, payload: schemas.DecisionPayload, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.register_decision(session, inspection_id, payload, actor, _rid(request))


@router.post("/{inspection_id}/pit", response_model=schemas.InspectionDetail)
async def register_pit(inspection_id: int, payload: schemas.PitPayload, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.register_pit(session, inspection_id, payload, actor, _rid(request))


@router.post("/{inspection_id}/approve", response_model=schemas.InspectionDetail)
async def approve(inspection_id: int, request: Request, payload: schemas.TransitionPayload | None = None, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.approve(session, inspection_id, actor, _rid(request), payload)


@router.post("/{inspection_id}/reject", response_model=schemas.InspectionDetail)
async def reject(inspection_id: int, payload: schemas.RejectPayload, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.reject(session, inspection_id, payload, actor, _rid(request))


@router.post("/{inspection_id}/doc", response_model=schemas.InspectionDetail)
async def register_doc(inspection_id: int, payload: schemas.DocPayload, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.register_doc(session, inspection_id, payload, actor, _rid(request))


@router.post("/{inspection_id}/catch-up", response_model=schemas.InspectionDetail)
async def catch_up(inspection_id: int, payload: schemas.CatchUpPayload, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.catch_up(session, inspection_id, payload, actor, _rid(request))


@router.post("/{inspection_id}/reschedule-visit", response_model=schemas.InspectionDetail)
async def reschedule_visit(inspection_id: int, payload: schemas.RescheduleVisitPayload, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.reschedule_visit(session, inspection_id, payload, actor, _rid(request))


@router.post("/{inspection_id}/events/{event_id}/occurred-on", response_model=schemas.InspectionDetail)
async def correct_occurred_on(inspection_id: int, event_id: int, payload: schemas.CorrectOccurredOnPayload, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.correct_occurred_on(session, inspection_id, event_id, payload, actor, _rid(request))
