from __future__ import annotations

import asyncio
import time
from datetime import datetime

from fastapi import APIRouter, Body, Depends, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core.exceptions import PermissionDeniedError
from api.app.database.session import get_db_session
from api.app.modules.auth.dependencies import get_current_user_ws, require_permission, user_has_permission
from api.app.modules.auth.models import User
from api.app.modules.auth.permissions import CHAT_SEND, CHAT_VIEW
from api.app.modules.chat import service
from api.app.modules.chat.ws_manager import manager as ws_manager
from api.app.modules.chat.schemas import (
    CancelQuestionRequest,
    ConversationList,
    ConversationReadState,
    MarkReadRequest,
    MentionableUserList,
    MessageCreate,
    MessageList,
    MessageOut,
    NotificationList,
    ReassignQuestionRequest,
    TimelineList,
    UnreadSummary,
)


router = APIRouter(tags=["chat"])


def _ensure_can_view_status(actor: User, status_filter: str | None) -> None:
    if status_filter != "FINALIZADA":
        return
    if not service.actor_can_view_finalized(actor):
        raise PermissionDeniedError("Seu usuario nao pode visualizar conversas finalizadas.")


@router.get("/chat/conversations", response_model=ConversationList)
async def list_conversations(
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None),
    conversation_id: int | None = Query(default=None, ge=1),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(CHAT_VIEW)),
):
    _ensure_can_view_status(actor, status_filter)
    return await service.list_conversations(
        session, actor, status=status_filter, search=search, conversation_id=conversation_id, limit=limit, offset=offset
    )


@router.get("/chat/conversations/{conversation_id}/messages", response_model=MessageList)
async def list_messages(
    conversation_id: int,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(CHAT_VIEW)),
):
    return await service.list_messages(session, conversation_id, actor, limit=limit, offset=offset)


@router.post("/chat/conversations/{conversation_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def post_message(
    conversation_id: int,
    payload: MessageCreate,
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(CHAT_SEND)),
):
    return await service.post_message(session, conversation_id, actor, payload)


@router.post("/chat/messages/{message_id}/answer", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def answer_question(
    message_id: int,
    body: str = Body(embed=True),
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(CHAT_SEND)),
):
    return await service.answer_question(session, message_id, actor, body)


@router.post("/chat/messages/{message_id}/viewed", response_model=MessageOut)
async def mark_question_viewed(
    message_id: int,
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(CHAT_VIEW)),
):
    return await service.mark_question_viewed(session, message_id, actor)


@router.post("/chat/messages/{message_id}/cancel", response_model=MessageOut)
async def cancel_question(
    message_id: int,
    payload: CancelQuestionRequest,
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(CHAT_SEND)),
):
    return await service.cancel_question(session, message_id, actor, payload.reason)


@router.patch("/chat/messages/{message_id}/assignee", response_model=MessageOut)
async def reassign_question(
    message_id: int,
    payload: ReassignQuestionRequest,
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(CHAT_SEND)),
):
    return await service.reassign_question(session, message_id, actor, payload.assignee_user_id, payload.reason)


@router.get("/chat/proposals/{proposal_id}/timeline", response_model=TimelineList)
async def get_proposal_timeline(
    proposal_id: int,
    before: datetime | None = Query(default=None),
    limit: int = Query(200, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(CHAT_VIEW)),
):
    return await service.get_proposal_timeline(session, proposal_id, actor, before=before, limit=limit)


@router.post("/chat/conversations/{conversation_id}/read", response_model=ConversationReadState)
async def mark_read(
    conversation_id: int,
    payload: MarkReadRequest,
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(CHAT_VIEW)),
):
    return await service.mark_read(session, conversation_id, actor, payload.last_read_message_id)


@router.get("/chat/unread-summary", response_model=UnreadSummary)
async def unread_summary(
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(CHAT_VIEW)),
):
    return await service.unread_summary(session, actor)


@router.get("/chat/notifications", response_model=NotificationList)
async def list_notifications(
    status: str | None = Query(None, pattern="^(unread|all)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(CHAT_VIEW)),
):
    return await service.list_notifications(session, actor, status=status, limit=limit, offset=offset)


@router.post("/chat/notifications/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_notification_read(
    notification_id: int,
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(CHAT_VIEW)),
):
    await service.mark_notification_read(session, notification_id, actor)


@router.post("/chat/notifications/mark-all-read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_notifications_read(
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(CHAT_VIEW)),
):
    await service.mark_all_notifications_read(session, actor)


@router.get("/chat/mentionable-users", response_model=MentionableUserList)
async def list_mentionable_users(
    search: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
    _actor: User = Depends(require_permission(CHAT_VIEW)),
):
    return await service.list_mentionable_users(session, search)


WS_LIVENESS_CHECK_SECONDS = 60


@router.websocket("/chat/ws")
async def chat_websocket(websocket: WebSocket, session: AsyncSession = Depends(get_db_session)):
    """Canal de push em tempo real: o cliente so recebe avisos ("essa
    conversa mudou"), nunca envia nada alem do handshake — a leitura em loop
    abaixo existe so pra detectar quando a conexao cai.

    ETAPA 7: autenticacao so acontece no handshake, mas a conexao pode ficar
    aberta bem mais tempo que a validade do access token (15 min por
    padrao). Em vez de reautenticar toda hora, so verificamos o `exp` ja
    validado no handshake periodicamente (WS_LIVENESS_CHECK_SECONDS) — se
    venceu, fecha a conexao; o RealtimeClient do desktop ja reconecta
    sozinho com backoff e ja busca um token novo a cada tentativa
    (current_access_token() renova sozinho), entao nao precisa de nenhuma
    logica nova do lado do cliente pra isso."""
    auth = await get_current_user_ws(websocket, session)
    if auth is None or not user_has_permission(auth[0], CHAT_VIEW):
        await websocket.close(code=4401)
        return
    user, expires_at = auth
    await websocket.accept()
    ws_manager.register(user.id, websocket)
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
        ws_manager.unregister(user.id, websocket)
