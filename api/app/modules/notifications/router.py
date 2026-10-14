from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core import error_codes
from api.app.core.exceptions import AuthenticationError
from api.app.database.session import get_db_session
from api.app.modules.auth.dependencies import bearer_scheme, require_permission
from api.app.modules.auth.models import User
from api.app.modules.auth.permissions import NOTIFICATIONS_VIEW
from api.app.modules.chat.ws_manager import manager as ws_manager
from api.app.modules.notifications import device_service, service
from api.app.modules.notifications.schemas import (
    CatchUpResponse,
    NotificationList,
    NotificationPreferenceOut,
    NotificationPreferencesPayload,
    NotificationSettingsPayload,
    NotificationUnreadSummary,
    NotificationUserSettingsOut,
    NotifierDeviceRegistered,
    NotifierDeviceRegisterPayload,
    NotifierTokenPayload,
    NotifierTokenResponse,
)

router = APIRouter(tags=["notifications"])

WS_LIVENESS_CHECK_SECONDS = 60


async def get_notifier_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    """Autentica o agente de avisos (--notifier) pelo token curto proprio dele.
    Um access token comum NAO passa aqui, e o token do agente nao passa nas
    rotas comuns: as duas credenciais nao se misturam."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError(error_codes.TOKEN_INVALID, "Token ausente ou invalido.")
    user, _expires_at = await device_service.authenticate_notifier(session, credentials.credentials)
    return user


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


# ------------------------------------------------- agente de avisos do Windows


@router.post("/notifications/devices", response_model=NotifierDeviceRegistered, status_code=status.HTTP_201_CREATED)
async def register_notifier_device(
    payload: NotifierDeviceRegisterPayload,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(NOTIFICATIONS_VIEW)),
):
    return await device_service.register_device(
        session,
        actor,
        payload,
        request_id=getattr(request.state, "request_id", None),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


@router.post("/notifications/devices/token", response_model=NotifierTokenResponse)
async def exchange_notifier_token(payload: NotifierTokenPayload, session: AsyncSession = Depends(get_db_session)):
    return await device_service.exchange_token(session, payload.device_token)


@router.get("/notifier/unread-summary", response_model=NotificationUnreadSummary)
async def notifier_unread_summary(
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(get_notifier_user),
):
    return await service.unread_summary(session, actor)


@router.get("/notifier/catch-up", response_model=CatchUpResponse)
async def notifier_catch_up(
    since_id: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(get_notifier_user),
):
    return await service.catch_up(session, actor, since_id=since_id, limit=limit, channel="tray")


@router.websocket("/notifier/ws")
async def notifier_websocket(websocket: WebSocket, session: AsyncSession = Depends(get_db_session)):
    """Gatilho em tempo real do agente de avisos: so recebe `notification.*`
    (o corpo vem por REST). Mesma regra do /chat/ws: autentica no handshake e
    fecha quando o token curto vence, forcando o cliente a reconectar."""
    auth_header = websocket.headers.get("authorization") or ""
    token = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""
    try:
        user, expires_at = await device_service.authenticate_notifier(session, token)
    except Exception:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    ws_manager.register_notifier(user.id, websocket)
    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=WS_LIVENESS_CHECK_SECONDS)
            except asyncio.TimeoutError:
                if time.time() >= expires_at:
                    await websocket.close(code=4401)
                    break
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.unregister_notifier(user.id, websocket)
