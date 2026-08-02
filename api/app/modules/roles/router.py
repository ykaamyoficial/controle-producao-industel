from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.database.session import get_db_session
from api.app.modules.auth.dependencies import require_permission
from api.app.modules.auth.models import User
from api.app.modules.auth.permissions import PERMISSIONS_VIEW, ROLES_CREATE, ROLES_MANAGE_PERMISSIONS, ROLES_UPDATE, ROLES_VIEW
from api.app.modules.roles import service
from api.app.modules.roles.schemas import PermissionList, RoleCreate, RoleDetail, RoleList, RoleUpdate


router = APIRouter(tags=["roles"])


@router.get("/roles", response_model=RoleList)
async def list_roles(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), session: AsyncSession = Depends(get_db_session), _actor: User = Depends(require_permission(ROLES_VIEW))):
    return await service.list_roles(session, limit, offset)


@router.get("/roles/{role_id}", response_model=RoleDetail)
async def get_role(role_id: int, session: AsyncSession = Depends(get_db_session), _actor: User = Depends(require_permission(ROLES_VIEW))):
    return service.role_detail(await service.get_role(session, role_id))


@router.post("/roles", response_model=RoleDetail, status_code=status.HTTP_201_CREATED)
async def create_role(payload: RoleCreate, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(ROLES_CREATE))):
    return service.role_detail(await service.create_role(session, payload, actor))


@router.patch("/roles/{role_id}", response_model=RoleDetail)
async def update_role(role_id: int, payload: RoleUpdate, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(ROLES_UPDATE))):
    return service.role_detail(await service.update_role(session, role_id, payload, actor))


@router.post("/roles/{role_id}/permissions", response_model=RoleDetail)
async def assign_permission(role_id: int, permission_id: int, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(ROLES_MANAGE_PERMISSIONS))):
    return service.role_detail(await service.assign_permission(session, role_id, permission_id, actor))


@router.delete("/roles/{role_id}/permissions/{permission_id}", response_model=RoleDetail)
async def remove_permission(role_id: int, permission_id: int, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(ROLES_MANAGE_PERMISSIONS))):
    return service.role_detail(await service.remove_permission(session, role_id, permission_id, actor))


@router.get("/permissions", response_model=PermissionList)
async def list_permissions(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), session: AsyncSession = Depends(get_db_session), _actor: User = Depends(require_permission(PERMISSIONS_VIEW))):
    return await service.list_permissions(session, limit, offset)
