from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.database.session import get_db_session
from api.app.modules.auth.dependencies import require_permission
from api.app.modules.auth.models import User
from api.app.modules.auth.permissions import GALVANIZATION_UPDATE, GALVANIZATION_VIEW
from api.app.modules.planned_loads import service
from api.app.modules.planned_loads.schemas import (
    PaginatedPlannedLoadResponse,
    PlannedLoadBuildResult,
    PlannedLoadConvertedRequest,
    PlannedLoadCreate,
    PlannedLoadDetail,
    PlannedLoadItemUpdate,
    PlannedLoadItemsRequest,
    PlannedLoadUpdate,
    PlannedLoadVersionRequest,
)


router = APIRouter(tags=["planned-loads"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("/planned-loads", response_model=PaginatedPlannedLoadResponse)
async def list_planned_loads(
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(GALVANIZATION_VIEW)),
):
    return await service.list_planned_loads(session, status=status_filter, search=search, limit=limit, offset=offset)


@router.post("/planned-loads", response_model=PlannedLoadDetail, status_code=status.HTTP_201_CREATED)
async def create_planned_load(
    payload: PlannedLoadCreate,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(GALVANIZATION_UPDATE)),
):
    return await service.create_planned_load(session, payload, actor, request_id=_request_id(request))


@router.get("/planned-loads/{planned_load_id}", response_model=PlannedLoadDetail)
async def get_planned_load(
    planned_load_id: int,
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(GALVANIZATION_VIEW)),
):
    return await service.get_planned_load_detail(session, planned_load_id)


@router.patch("/planned-loads/{planned_load_id}", response_model=PlannedLoadDetail)
async def update_planned_load(
    planned_load_id: int,
    payload: PlannedLoadUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(GALVANIZATION_UPDATE)),
):
    return await service.update_planned_load(session, planned_load_id, payload, actor, request_id=_request_id(request))


@router.post("/planned-loads/{planned_load_id}/items", response_model=PlannedLoadDetail)
async def add_planned_load_items(
    planned_load_id: int,
    payload: PlannedLoadItemsRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(GALVANIZATION_UPDATE)),
):
    return await service.add_planned_load_items(session, planned_load_id, payload, actor, request_id=_request_id(request))


@router.patch("/planned-loads/{planned_load_id}/items/{item_id}", response_model=PlannedLoadDetail)
async def update_planned_load_item(
    planned_load_id: int,
    item_id: int,
    payload: PlannedLoadItemUpdate,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(GALVANIZATION_UPDATE)),
):
    return await service.update_planned_load_item(session, planned_load_id, item_id, payload, actor, request_id=_request_id(request))


@router.delete("/planned-loads/{planned_load_id}/items/{item_id}", response_model=PlannedLoadDetail)
async def delete_planned_load_item(
    planned_load_id: int,
    item_id: int,
    request: Request,
    version: int = Query(..., ge=1),
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(GALVANIZATION_UPDATE)),
):
    return await service.delete_planned_load_item(session, planned_load_id, item_id, version, actor, request_id=_request_id(request))


@router.post("/planned-loads/{planned_load_id}/cancel", response_model=PlannedLoadDetail)
async def cancel_planned_load(
    planned_load_id: int,
    payload: PlannedLoadVersionRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(GALVANIZATION_UPDATE)),
):
    return await service.cancel_planned_load(session, planned_load_id, payload, actor, request_id=_request_id(request))


@router.post("/planned-loads/{planned_load_id}/build", response_model=PlannedLoadBuildResult)
async def build_planned_load(
    planned_load_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(GALVANIZATION_UPDATE)),
):
    return await service.build_planned_load(session, planned_load_id, actor, request_id=_request_id(request))


@router.post("/planned-loads/{planned_load_id}/mark-converted", response_model=PlannedLoadDetail)
async def mark_planned_load_converted(
    planned_load_id: int,
    payload: PlannedLoadConvertedRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(GALVANIZATION_UPDATE)),
):
    return await service.mark_planned_load_converted(session, planned_load_id, payload, actor, request_id=_request_id(request))
