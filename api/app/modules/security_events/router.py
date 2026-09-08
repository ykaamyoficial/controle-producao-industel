from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.database.session import get_db_session
from api.app.modules.auth.dependencies import require_permission
from api.app.modules.auth.models import User
from api.app.modules.auth.permissions import AUDIT_VIEW
from api.app.modules.security_events import service
from api.app.modules.security_events.schemas import SecurityEventList, SecurityEventOut


router = APIRouter(prefix="/security-events", tags=["security-events"])


@router.get("", response_model=SecurityEventList)
async def list_security_events(
    event_type: str | None = Query(default=None, max_length=80),
    user_id: int | None = Query(default=None, ge=1),
    success: bool | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    request_id: str | None = Query(default=None, max_length=100),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(AUDIT_VIEW)),
):
    return await service.list_events(
        session,
        event_type=event_type,
        user_id=user_id,
        success=success,
        date_from=date_from,
        date_to=date_to,
        request_id=request_id,
        limit=limit,
        offset=offset,
    )


@router.get("/{event_id}", response_model=SecurityEventOut)
async def get_security_event(event_id: int, session: AsyncSession = Depends(get_db_session), _actor: User = Depends(require_permission(AUDIT_VIEW))):
    return await service.get_event(session, event_id)
