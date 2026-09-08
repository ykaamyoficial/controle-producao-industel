from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.database.session import get_db_session
from api.app.modules.auth.dependencies import require_permission
from api.app.modules.auth.models import User
from api.app.modules.auth.permissions import NOTIFICATIONS_VIEW
from api.app.modules.notifications import service
from api.app.modules.notifications.schemas import (
    CatchUpResponse,
    NotificationList,
    NotificationPreferenceOut,
    NotificationPreferencesPayload,
    NotificationSettingsPayload,
    NotificationUnreadSummary,
    NotificationUserSettingsOut,
)

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=NotificationList)
async def list_notifications(
    status: str | None = Query(default=None, pattern="^(unread|all)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(NOTIFICATIONS_VIEW)),
):
    return await service.list_notifications(session, actor, status=status, limit=limit, offset=offset)


@router.get("/notifications/unread-summary", response_model=NotificationUnreadSummary)
async def unread_summary(
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(NOTIFICATIONS_VIEW)),
):
    return await service.unread_summary(session, actor)


@router.get("/notifications/catch-up", response_model=CatchUpResponse)
async def catch_up(
    since_id: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(NOTIFICATIONS_VIEW)),
):
    return await service.catch_up(session, actor, since_id=since_id, limit=limit)


@router.post("/notifications/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_notification_read(
    notification_id: int,
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(NOTIFICATIONS_VIEW)),
):
    await service.mark_read(session, notification_id, actor)


@router.post("/notifications/mark-all-read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_notifications_read(
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(NOTIFICATIONS_VIEW)),
):
    await service.mark_all_read(session, actor)


@router.get("/notifications/preferences", response_model=list[NotificationPreferenceOut])
async def get_preferences(
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(NOTIFICATIONS_VIEW)),
):
    return await service.get_preferences(session, actor)


@router.put("/notifications/preferences", response_model=list[NotificationPreferenceOut])
async def put_preferences(
    payload: NotificationPreferencesPayload,
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(NOTIFICATIONS_VIEW)),
):
    return await service.put_preferences(session, actor, payload)


@router.get("/notifications/settings", response_model=NotificationUserSettingsOut)
async def get_settings(
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(NOTIFICATIONS_VIEW)),
):
    return await service.get_settings(session, actor)


@router.put("/notifications/settings", response_model=NotificationUserSettingsOut)
async def put_settings(
    payload: NotificationSettingsPayload,
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(NOTIFICATIONS_VIEW)),
):
    return await service.put_settings(session, actor, payload)
