from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.database.session import get_db_session
from api.app.modules.auth.dependencies import require_permission
from api.app.modules.auth.models import User
from api.app.modules.auth.permissions import USERS_CREATE, USERS_DISABLE, USERS_MANAGE_PERMISSIONS, USERS_UPDATE, USERS_VIEW
from api.app.modules.auth.schemas import UserOut
from api.app.modules.auth.service import public_user
from api.app.modules.users import service
from api.app.modules.users.schemas import PasswordReset, UserCreate, UserList, UserUpdate


router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=UserList)
async def list_users(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), session: AsyncSession = Depends(get_db_session), _actor: User = Depends(require_permission(USERS_VIEW))):
    return await service.list_users(session, limit, offset)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(user_id: int, session: AsyncSession = Depends(get_db_session), _actor: User = Depends(require_permission(USERS_VIEW))):
    return public_user(await service.get_user(session, user_id))


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(USERS_CREATE))):
    return public_user(await service.create_user(session, payload, actor))


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: int, payload: UserUpdate, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(USERS_UPDATE))):
    return public_user(await service.update_user(session, user_id, payload, actor))


@router.post("/{user_id}/activate", response_model=UserOut)
async def activate_user(user_id: int, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(USERS_DISABLE))):
    return public_user(await service.activate_user(session, user_id, actor))


@router.post("/{user_id}/deactivate", response_model=UserOut)
async def deactivate_user(user_id: int, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(USERS_DISABLE))):
    return public_user(await service.deactivate_user(session, user_id, actor))


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: int, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(USERS_DISABLE))):
    await service.delete_user(session, user_id, actor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{user_id}/reset-password", response_model=UserOut)
async def reset_password(user_id: int, payload: PasswordReset, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(USERS_UPDATE))):
    return public_user(await service.reset_password(session, user_id, payload.password, actor, payload.revoke_sessions))


@router.post("/{user_id}/roles", response_model=UserOut)
async def assign_role(user_id: int, role_id: int, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(USERS_MANAGE_PERMISSIONS))):
    return public_user(await service.assign_role(session, user_id, role_id, actor))


@router.delete("/{user_id}/roles/{role_id}", response_model=UserOut)
async def remove_role(user_id: int, role_id: int, session: AsyncSession = Depends(get_db_session), actor: User = Depends(require_permission(USERS_MANAGE_PERMISSIONS))):
    return public_user(await service.remove_role(session, user_id, role_id, actor))
