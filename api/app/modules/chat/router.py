from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core.exceptions import PermissionDeniedError
from api.app.database.session import get_db_session
from api.app.modules.auth.dependencies import require_permission
from api.app.modules.auth.models import User
from api.app.modules.auth.permissions import CHAT_SEND, CHAT_VIEW
from api.app.modules.chat import service
from api.app.modules.chat.schemas import (
    ConversationList,
    MarkReadRequest,
    MentionableUserList,
    MessageCreate,
    MessageList,
    MessageOut,
    NotificationList,
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
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(CHAT_VIEW)),
):
    _ensure_can_view_status(actor, status_filter)
    return await service.list_conversations(session, actor, status=status_filter, search=search, limit=limit, offset=offset)


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


@router.get("/chat/proposals/{proposal_id}/timeline", response_model=TimelineList)
async def get_proposal_timeline(
    proposal_id: int,
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(CHAT_VIEW)),
):
    return await service.get_proposal_timeline(session, proposal_id, actor)


@router.post("/chat/conversations/{conversation_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    conversation_id: int,
    payload: MarkReadRequest,
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(CHAT_VIEW)),
):
    await service.mark_read(session, conversation_id, actor, payload.last_read_message_id)


@router.get("/chat/unread-summary", response_model=UnreadSummary)
async def unread_summary(
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(CHAT_VIEW)),
):
    return await service.unread_summary(session, actor)


@router.get("/chat/notifications", response_model=NotificationList)
async def list_notifications(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    actor: User = Depends(require_permission(CHAT_VIEW)),
):
    return await service.list_notifications(session, actor, limit=limit, offset=offset)


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
