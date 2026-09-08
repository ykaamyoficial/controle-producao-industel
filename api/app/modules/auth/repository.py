from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.app.modules.auth.models import AuthSession, Permission, Role, RolePermission, SecurityEvent, User, UserRole


def normalize_username(username: str) -> str:
    return " ".join(str(username or "").strip().lower().split())


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    stmt = (
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .where(func.lower(User.username) == normalize_username(username))
        .execution_options(populate_existing=True)
    )
    return (await session.execute(stmt)).scalars().first()


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    stmt = (
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .where(User.id == user_id)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(stmt)).scalars().first()


async def get_role(session: AsyncSession, role_id: int) -> Role | None:
    return await session.get(Role, role_id, options=[selectinload(Role.permissions)])


async def get_permission(session: AsyncSession, permission_id: int) -> Permission | None:
    return await session.get(Permission, permission_id)


async def get_permission_by_code(session: AsyncSession, code: str) -> Permission | None:
    return (await session.execute(select(Permission).where(Permission.code == code))).scalars().first()


async def user_permissions(user: User) -> set[str]:
    if user.is_superuser:
        return {"*"}
    permissions: set[str] = set()
    for role in user.roles:
        if not role.active:
            continue
        for permission in role.permissions:
            if permission.active:
                permissions.add(permission.code)
    return permissions


async def active_admin_count(session: AsyncSession, exclude_user_id: int | None = None) -> int:
    stmt: Select = select(func.count()).select_from(User).where(User.active.is_(True), User.is_superuser.is_(True))
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    return int((await session.execute(stmt)).scalar_one())


async def create_security_event(
    session: AsyncSession,
    event_type: str,
    *,
    actor_user_id: int | None,
    target_user_id: int | None = None,
    request_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    success: bool = True,
    details: dict | None = None,
) -> SecurityEvent:
    event = SecurityEvent(
        event_type=event_type,
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        request_id=request_id,
        ip_address=ip_address,
        user_agent=user_agent,
        success=success,
        details=details or None,
    )
    session.add(event)
    return event


async def revoke_user_sessions(session: AsyncSession, user_id: int, reason: str) -> None:
    await session.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC), revoke_reason=reason)
    )
