from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.database.session import get_db_session
from api.app.modules.auth import service
from api.app.modules.auth.dependencies import get_current_active_user
from api.app.modules.auth.models import User
from api.app.modules.auth.schemas import LoginRequest, LogoutRequest, RefreshRequest, TokenResponse, UserOut


router = APIRouter(prefix="/auth", tags=["auth"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request, session: AsyncSession = Depends(get_db_session)):
    return await service.login(
        session,
        payload.username,
        payload.password,
        request_id=getattr(request.state, "request_id", None),
        ip_address=_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, request: Request, session: AsyncSession = Depends(get_db_session)):
    return await service.refresh(
        session,
        payload.refresh_token,
        request_id=getattr(request.state, "request_id", None),
        ip_address=_ip(request),
        user_agent=request.headers.get("user-agent"),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: LogoutRequest,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await service.logout(session, payload.refresh_token, current_user, request_id=getattr(request.state, "request_id", None))


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
):
    await service.logout_all(session, current_user, request_id=getattr(request.state, "request_id", None))


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_active_user)):
    return service.public_user(current_user)
