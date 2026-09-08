from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, WebSocket
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


async def get_current_user_ws(websocket: WebSocket, session: AsyncSession) -> tuple[User, int] | None:
    """Autentica uma conexao websocket a partir do header Authorization do
    handshake. Nao usa Depends()/HTTPBearer (nao se comportam da mesma forma
    numa rota WebSocket) nem levanta excecao — quem chama decide como fechar
    a conexao, chamado manualmente antes de aceitar o socket.

    Devolve tambem o `exp` (unix timestamp) do access token: a conexao fica
    aberta bem mais tempo que a validade do token (ETAPA 7 — so autentica
    no handshake), entao quem chama usa esse valor pra fechar a conexao
    quando o token expirar, forcando o cliente a reconectar com um token
    novo em vez de manter um socket "autenticado" com credencial vencida."""
    auth_header = websocket.headers.get("authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header[7:].strip()
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        user = await repository.get_user_by_id(session, int(payload["sub"]))
    except Exception:
        return None
    if user is None or not user.active:
        return None
    expires_at = payload.get("exp")
    if not isinstance(expires_at, (int, float)):
        return None
    return user, int(expires_at)


def user_has_permission(user: User, permission: str) -> bool:
    return user.is_superuser or permission in effective_permissions(user)
