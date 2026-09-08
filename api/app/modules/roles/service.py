from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.app.core import error_codes
from api.app.core.exceptions import ApiError
from api.app.modules.auth import repository
from api.app.modules.auth.models import Permission, Role, User
from api.app.modules.auth.schemas import PermissionOut
from api.app.modules.roles.schemas import PermissionList, RoleCreate, RoleDetail, RoleList, RoleUpdate


def _normalize_code(code: str) -> str:
    return code.strip().lower()


def role_detail(role: Role) -> RoleDetail:
    return RoleDetail(
        id=role.id,
        code=role.code,
        name=role.name,
        active=role.active,
        description=role.description,
        system_role=role.system_role,
        permissions=[
            PermissionOut(id=permission.id, code=permission.code, name=permission.name, module=permission.module)
            for permission in sorted(role.permissions, key=lambda item: item.code)
            if permission.active
        ],
    )


async def list_roles(session: AsyncSession, limit: int, offset: int) -> RoleList:
    total = int((await session.execute(select(func.count()).select_from(Role))).scalar_one())
    rows = (
        await session.execute(
            select(Role).options(selectinload(Role.permissions)).order_by(Role.name).limit(limit).offset(offset)
        )
    ).scalars().all()
    return RoleList(items=[role_detail(role) for role in rows], total=total)


async def get_role(session: AsyncSession, role_id: int) -> Role:
    role = await repository.get_role(session, role_id)
    if role is None:
        raise ApiError(error_codes.ROLE_NOT_FOUND, "Perfil nao encontrado.", status_code=404)
    return role


async def create_role(session: AsyncSession, payload: RoleCreate, actor: User) -> Role:
    role = Role(
        code=_normalize_code(payload.code),
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        active=payload.active,
        system_role=False,
    )
    for permission_id in payload.permission_ids:
        permission = await repository.get_permission(session, permission_id)
        if permission is None:
            raise ApiError(error_codes.PERMISSION_NOT_FOUND, "Permissao informada nao existe.", status_code=404)
        role.permissions.append(permission)
    session.add(role)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ApiError(error_codes.ROLE_IN_USE, "Ja existe perfil com esse codigo.", status_code=409) from exc
    await repository.create_security_event(session, "ROLE_CREATED", actor_user_id=actor.id, details={"role_id": role.id})
    await session.commit()
    return await get_role(session, role.id)


async def update_role(session: AsyncSession, role_id: int, payload: RoleUpdate, actor: User) -> Role:
    role = await get_role(session, role_id)
    if payload.name is not None:
        role.name = payload.name.strip()
    if payload.description is not None:
        role.description = payload.description.strip() or None
    if payload.active is not None:
        role.active = payload.active
    await repository.create_security_event(session, "ROLE_UPDATED", actor_user_id=actor.id, details={"role_id": role.id})
    await session.commit()
    return await get_role(session, role.id)


async def assign_permission(session: AsyncSession, role_id: int, permission_id: int, actor: User) -> Role:
    role = await get_role(session, role_id)
    permission = await repository.get_permission(session, permission_id)
    if permission is None:
        raise ApiError(error_codes.PERMISSION_NOT_FOUND, "Permissao informada nao existe.", status_code=404)
    if permission not in role.permissions:
        role.permissions.append(permission)
    await repository.create_security_event(
        session,
        "PERMISSION_ASSIGNED",
        actor_user_id=actor.id,
        details={"role_id": role.id, "permission_id": permission.id},
    )
    await session.commit()
    return await get_role(session, role.id)


async def remove_permission(session: AsyncSession, role_id: int, permission_id: int, actor: User) -> Role:
    role = await get_role(session, role_id)
    permission = await repository.get_permission(session, permission_id)
    if permission is None:
        raise ApiError(error_codes.PERMISSION_NOT_FOUND, "Permissao informada nao existe.", status_code=404)
    if permission in role.permissions:
        role.permissions.remove(permission)
    await repository.create_security_event(
        session,
        "PERMISSION_REMOVED",
        actor_user_id=actor.id,
        details={"role_id": role.id, "permission_id": permission.id},
    )
    await session.commit()
    return await get_role(session, role.id)


async def list_permissions(session: AsyncSession, limit: int, offset: int) -> PermissionList:
    total = int((await session.execute(select(func.count()).select_from(Permission))).scalar_one())
    rows = (
        await session.execute(select(Permission).where(Permission.active.is_(True)).order_by(Permission.module, Permission.code).limit(limit).offset(offset))
    ).scalars().all()
    return PermissionList(
        items=[PermissionOut(id=permission.id, code=permission.code, name=permission.name, module=permission.module) for permission in rows],
        total=total,
    )
