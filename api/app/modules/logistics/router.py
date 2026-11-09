from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.database.session import get_db_session
from api.app.modules.auth.dependencies import require_permission
from api.app.modules.auth.models import User
from api.app.modules.auth.permissions import LOGISTICS_EDIT, LOGISTICS_VIEW
from api.app.modules.logistics import schemas, service

router = APIRouter(prefix="/logistics", tags=["logistics"])

_view = require_permission(LOGISTICS_VIEW)
_edit = require_permission(LOGISTICS_EDIT)


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


# --- LOGs ----------------------------------------------------------------------------------


@router.get("/logs", response_model=schemas.LogList)
async def list_logs(
    stage: str | None = Query(None, pattern="^(reservada|docs|aprovada|entregue)$"),
    search: str | None = Query(None, max_length=120),
    in_load: bool | None = Query(None),
    state: str | None = Query(None, max_length=40),
    load_id: int | None = Query(None, ge=1),
    limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session), _actor: User = Depends(_view),
):
    return await service.list_logs(
        session, stage=stage, search=search, in_load=in_load, state=state, load_id=load_id, limit=limit, offset=offset,
    )


@router.get("/log-states", response_model=list[str])  # antes de /logs/{log_id}
async def list_log_states(session: AsyncSession = Depends(get_db_session), _actor: User = Depends(_view)):
    return await service.list_states(session)


@router.get("/eligible-proposals", response_model=schemas.EligibleProposalList)
async def list_eligible(
    search: str | None = Query(None, max_length=120),
    limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session), _actor: User = Depends(_view),
):
    return await service.list_eligible(session, search=search, limit=limit, offset=offset)


@router.get("/logs/{log_id}", response_model=schemas.LogDetail)
async def get_log(log_id: int, session: AsyncSession = Depends(get_db_session), _actor: User = Depends(_view)):
    return await service.get_log(session, log_id)


@router.post("/logs", response_model=schemas.LogDetail, status_code=status.HTTP_201_CREATED)
async def create_log(payload: schemas.LogCreate, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.create_log(session, payload, actor, _rid(request))


@router.patch("/logs/{log_id}/dates", response_model=schemas.LogDetail)
async def update_log_dates(log_id: int, payload: schemas.LogDatesPayload, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.update_log_dates(session, log_id, payload, actor, _rid(request))


@router.post("/logs/{log_id}/delivery", response_model=schemas.LogDetail)
async def set_delivery(log_id: int, payload: schemas.LogDeliveryPayload, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.set_delivery(session, log_id, payload, actor, _rid(request))


@router.post("/logs/{log_id}/docs", response_model=schemas.LogDetail)
async def send_docs(log_id: int, payload: schemas.DocsPayload, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.send_docs(session, log_id, payload, actor, _rid(request))


@router.post("/logs/{log_id}/approve", response_model=schemas.LogDetail)
async def approve_log(
    log_id: int, request: Request, payload: schemas.ApprovePayload | None = None,
    session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit),
):
    return await service.approve_log(session, log_id, actor, _rid(request), payload)


@router.post("/logs/{log_id}/proposals", response_model=schemas.LogDetail)
async def add_proposals(log_id: int, payload: schemas.AddProposalsPayload, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.add_proposals(session, log_id, payload, actor, _rid(request))


@router.post("/logs/{log_id}/items/{item_id}/resolve", response_model=schemas.LogDetail | schemas.RemoveResult)
async def resolve_item(log_id: int, item_id: int, payload: schemas.ResolveItemPayload, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.resolve_item(session, log_id, item_id, payload, actor, _rid(request))


@router.post("/logs/{log_id}/items/{item_id}/remove", response_model=schemas.RemoveResult)
async def remove_item(log_id: int, item_id: int, payload: schemas.ReasonPayload, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.remove_item(session, log_id, item_id, payload, actor, _rid(request))


# --- Cargas de entrega -------------------------------------------------------------------------


@router.get("/loads", response_model=schemas.LoadList)
async def list_loads(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), session: AsyncSession = Depends(get_db_session), _actor: User = Depends(_view)):
    return await service.list_loads(session, limit=limit, offset=offset)


@router.get("/loads/{load_id}", response_model=schemas.LoadDetail)
async def get_load(load_id: int, session: AsyncSession = Depends(get_db_session), _actor: User = Depends(_view)):
    return await service.get_load(session, load_id)


@router.post("/loads", response_model=schemas.LoadDetail, status_code=status.HTTP_201_CREATED)
async def create_load(payload: schemas.LoadCreate, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.create_load(session, payload, actor, _rid(request))


@router.patch("/loads/{load_id}", response_model=schemas.LoadDetail)
async def update_load(load_id: int, payload: schemas.LoadUpdate, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.update_load(session, load_id, payload, actor, _rid(request))


@router.post("/loads/{load_id}/departed", response_model=schemas.LoadDetail)
async def set_departed(load_id: int, payload: schemas.LoadDepartedPayload, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.set_departed(session, load_id, payload, actor, _rid(request))


@router.post("/loads/{load_id}/logs", response_model=schemas.LoadDetail)
async def add_log_to_load(load_id: int, payload: schemas.LogIdPayload, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.add_log_to_load(session, load_id, payload, actor, _rid(request))


@router.delete("/loads/{load_id}/logs/{log_id}", response_model=schemas.LoadDetail)
async def remove_log_from_load(load_id: int, log_id: int, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    return await service.remove_log_from_load(session, load_id, log_id, actor, _rid(request))


@router.delete("/loads/{load_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_load(load_id: int, request: Request, session: AsyncSession = Depends(get_db_session), actor: User = Depends(_edit)):
    await service.delete_load(session, load_id, actor, _rid(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
