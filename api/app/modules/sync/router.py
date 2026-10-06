from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.database.session import get_db_session
from api.app.modules.auth.dependencies import get_current_active_user
from api.app.modules.auth.models import User
from api.app.modules.sync import service
from api.app.modules.sync.schemas import SyncChangesResponse, SyncHead, SyncSnapshotResponse

router = APIRouter(tags=["sync"])


@router.get("/sync/head", response_model=SyncHead)
async def sync_head(
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(get_current_active_user),
):
    return await service.get_head(session, actor)


@router.get("/sync/changes", response_model=SyncChangesResponse)
async def sync_changes(
    since: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(get_current_active_user),
):
    return await service.get_changes(session, actor, since=since, limit=limit)


@router.get("/sync/snapshot", response_model=SyncSnapshotResponse)
async def sync_snapshot(
    entity: str = Query(min_length=1, max_length=60),
    after_id: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(get_current_active_user),
):
    return await service.get_snapshot(session, actor, entity=entity, after_id=after_id, limit=limit)
