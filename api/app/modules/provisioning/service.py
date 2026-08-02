from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.app.core import error_codes
from api.app.core.exceptions import ApiError
from api.app.modules.auth import repository
from api.app.modules.auth.models import Permission, Role, User
from api.app.modules.auth.permissions import ADMIN_PERMISSION_CODES
from api.app.modules.auth.security import hash_password
from api.app.modules.auth.service import public_user
from api.app.modules.auth.tokens import utcnow
from api.app.modules.provisioning.schemas import InitialAdminCreate, InitialAdminResponse


async def provision_initial_admin(session: AsyncSession, payload: InitialAdminCreate, request_id: str | None = None) -> InitialAdminResponse:
    username = repository.normalize_username(payload.username)
    existing = await repository.get_user_by_username(session, username)
    if existing is not None:
        if not existing.is_superuser:
            raise ApiError(error_codes.USERNAME_ALREADY_EXISTS, "Ja existe usuario com esse login sem perfil administrador.", status_code=409)
        return InitialAdminResponse(user=public_user(existing), created=False, message="Administrador operacional inicial ja existia.")

    role = await _ensure_admin_role(session)
    user = User(
        username=username,
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.temporary_password),
        active=True,
        is_superuser=True,
        password_must_change=True,
        password_changed_at=utcnow(),
    )
    user.roles.append(role)
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ApiError(error_codes.USERNAME_ALREADY_EXISTS, "Ja existe usuario com esse login.", status_code=409) from exc
    await repository.create_security_event(
        session,
        "INITIAL_ADMIN_PROVISIONED",
        actor_user_id=None,
        target_user_id=user.id,
        request_id=request_id,
        details={"source": "platform_admin"},
    )
    await session.commit()
    user = await repository.get_user_by_id(session, user.id)
    if user is None:
        raise ApiError(error_codes.USER_NOT_FOUND, "Administrador criado nao foi localizado.", status_code=500)
    return InitialAdminResponse(user=public_user(user), created=True, message="Administrador operacional inicial criado.")


async def _ensure_admin_role(session: AsyncSession) -> Role:
    result = await session.execute(select(Role).options(selectinload(Role.permissions)).where(Role.code == "admin"))
    role = result.scalars().first()
    if role is None:
        role = Role(code="admin", name="Administrador", description="Administrador operacional", active=True, system_role=True)
        session.add(role)
        await session.flush()
    permissions = (await session.execute(select(Permission).where(Permission.code.in_(ADMIN_PERMISSION_CODES)))).scalars().all()

    if role.id is not None:
        await session.refresh(role, attribute_names=["permissions"])

    existing_codes = {permission.code for permission in role.permissions}
    
    for permission in permissions:
        if permission.code not in existing_codes:
            role.permissions.append(permission)
    await session.flush()
    return role
