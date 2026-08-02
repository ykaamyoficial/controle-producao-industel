from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core import error_codes
from api.app.core.exceptions import AuthenticationError, PermissionDeniedError
from api.app.database.session import get_db_session
from api.app.modules.auth import repository
from api.app.modules.auth.models import User
from api.app.modules.auth.service import effective_permissions
from api.app.modules.auth.tokens import decode_access_token


bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError(error_codes.TOKEN_INVALID, "Token ausente ou invalido.")
    payload = decode_access_token(credentials.credentials)
    user = await repository.get_user_by_id(session, int(payload["sub"]))
    if user is None:
        raise AuthenticationError(error_codes.TOKEN_INVALID, "Token invalido.")
    return user


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.active:
        raise AuthenticationError(error_codes.ACCOUNT_INACTIVE, "Conta inativa.")
    return current_user


async def require_superuser(current_user: User = Depends(get_current_active_user)) -> User:
    if not current_user.is_superuser:
        raise PermissionDeniedError()
    return current_user


def require_permission(permission: str) -> Callable:
    async def dependency(current_user: User = Depends(get_current_active_user)) -> User:
        permissions = effective_permissions(current_user)
        if not current_user.is_superuser and permission not in permissions:
            raise PermissionDeniedError()
        return current_user

    return dependency


def require_any_permission(*required: str) -> Callable:
    async def dependency(current_user: User = Depends(get_current_active_user)) -> User:
        permissions = effective_permissions(current_user)
        if not current_user.is_superuser and not any(permission in permissions for permission in required):
            raise PermissionDeniedError()
        return current_user

    return dependency


def require_all_permissions(*required: str) -> Callable:
    async def dependency(current_user: User = Depends(get_current_active_user)) -> User:
        permissions = effective_permissions(current_user)
        if not current_user.is_superuser and not all(permission in permissions for permission in required):
            raise PermissionDeniedError()
        return current_user

    return dependency
