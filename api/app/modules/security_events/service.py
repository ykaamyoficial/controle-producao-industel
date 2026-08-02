from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core import error_codes
from api.app.core.exceptions import ApiError
from api.app.modules.auth.models import SecurityEvent
from api.app.modules.security_events.schemas import SecurityEventList, SecurityEventOut


def _event_out(event: SecurityEvent) -> SecurityEventOut:
    return SecurityEventOut(
        id=event.id,
        event_type=event.event_type,
        actor_user_id=event.actor_user_id,
        target_user_id=event.target_user_id,
        request_id=event.request_id,
        ip_address=event.ip_address,
        user_agent=event.user_agent,
        success=event.success,
        details=event.details,
        created_at=event.created_at,
    )


def _apply_filters(
    stmt: Select,
    *,
    event_type: str | None,
    user_id: int | None,
    success: bool | None,
    date_from: datetime | None,
    date_to: datetime | None,
    request_id: str | None,
) -> Select:
    if event_type:
        stmt = stmt.where(SecurityEvent.event_type == event_type)
    if user_id is not None:
        stmt = stmt.where((SecurityEvent.actor_user_id == user_id) | (SecurityEvent.target_user_id == user_id))
    if success is not None:
        stmt = stmt.where(SecurityEvent.success.is_(success))
    if date_from is not None:
        stmt = stmt.where(SecurityEvent.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(SecurityEvent.created_at <= date_to)
    if request_id:
        stmt = stmt.where(SecurityEvent.request_id == request_id)
    return stmt


async def list_events(
    session: AsyncSession,
    *,
    event_type: str | None,
    user_id: int | None,
    success: bool | None,
    date_from: datetime | None,
    date_to: datetime | None,
    request_id: str | None,
    limit: int,
    offset: int,
) -> SecurityEventList:
    base = _apply_filters(
        select(SecurityEvent),
        event_type=event_type,
        user_id=user_id,
        success=success,
        date_from=date_from,
        date_to=date_to,
        request_id=request_id,
    )
    total = int((await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one())
    rows = (await session.execute(base.order_by(SecurityEvent.created_at.desc()).limit(limit).offset(offset))).scalars().all()
    return SecurityEventList(items=[_event_out(event) for event in rows], total=total)


async def get_event(session: AsyncSession, event_id: int) -> SecurityEventOut:
    event = await session.get(SecurityEvent, event_id)
    if event is None:
        raise ApiError(error_codes.NOT_FOUND, "Evento de seguranca nao encontrado.", status_code=404)
    return _event_out(event)
