from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.database.session import get_db_session
from api.app.modules.auth.dependencies import get_current_active_user, require_permission
from api.app.modules.auth.models import User
from api.app.modules.auth.permissions import USERS_CREATE, USERS_DISABLE, USERS_MANAGE_PERMISSIONS, USERS_UPDATE, USERS_VIEW
from api.app.modules.auth.schemas import UserOut
from api.app.modules.auth.service import public_user
from api.app.modules.users import service
from api.app.modules.users.schemas import ChangePassword, MeUpdate, PasswordReset, UserCreate, UserList, UserUpdate


router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_active_user)):
    return public_user(current_user)


@router.patch("/me", response_model=UserOut)
async def update_me(payload: MeUpdate, session: AsyncSession = Depends(get_db_session), actor: User = Depends(get_current_active_user)):
    return public_user(await service.update_me(session, actor, payload))


@router.post("/me/change-password", response_model=UserOut)
async def change_password(payload: ChangePassword, session: AsyncSession = Depends(get_db_session), actor: User = Depends(get_current_active_user)):
    return public_user(await service.change_my_password(session, actor, payload))


@router.post("/me/avatar", response_model=UserOut)
async def upload_avatar(file: UploadFile = File(...), session: AsyncSession = Depends(get_db_session), actor: User = Depends(get_current_active_user)):
    content = await file.read(5 * 1024 * 1024 + 1)
    return public_user(await service.update_avatar(session, actor, content, file.content_type or ""))


@router.delete("/me/avatar", response_model=UserOut)
async def delete_avatar(session: AsyncSession = Depends(get_db_session), actor: User = Depends(get_current_active_user)):
    return public_user(await service.remove_avatar(session, actor))


@router.get("/me/avatar")
async def get_avatar(actor: User = Depends(get_current_active_user)):
    if not actor.avatar_bytes or not actor.avatar_mime:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    return Response(content=actor.avatar_bytes, media_type=actor.avatar_mime, headers={"Cache-Control": "no-store"})


@router.get("/{user_id}/avatar")
async def get_user_avatar(user_id: int, session: AsyncSession = Depends(get_db_session), _actor: User = Depends(get_current_active_user)):
    user = await service.get_user(session, user_id)
    if not user.avatar_bytes or not user.avatar_mime:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    return Response(content=user.avatar_bytes, media_type=user.avatar_mime, headers={"Cache-Control": "no-store"})


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
