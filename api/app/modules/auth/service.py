from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core import error_codes
from api.app.core.config import get_settings
from api.app.core.exceptions import ApiError, AuthenticationError
from api.app.modules.auth import repository
from api.app.modules.auth.models import AuthSession, User
from api.app.modules.auth.schemas import RoleOut, TokenResponse, UserOut
from api.app.modules.auth.security import hash_password, password_needs_rehash, verify_password
from api.app.modules.auth.tokens import create_access_token, generate_refresh_token, hash_refresh_token, utcnow


def public_user(user: User) -> UserOut:
    codes = sorted({"*" if user.is_superuser else code for code in effective_permissions(user)})
    return UserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        active=user.active,
        is_superuser=user.is_superuser,
        password_must_change=bool(user.password_must_change),
        locked_until=user.locked_until,
        roles=[RoleOut(id=role.id, code=role.code, name=role.name, active=role.active) for role in user.roles],
        permissions=codes,
        avatar_available=user.avatar_bytes is not None,
        avatar_mime=user.avatar_mime,
    )


def effective_permissions(user: User) -> set[str]:
    if user.is_superuser:
        return {"*"}
    permissions: set[str] = set()
    for role in user.roles:
        if role.active:
            permissions.update(permission.code for permission in role.permissions if permission.active)
    return permissions


def is_locked(user: User) -> bool:
    return bool(user.locked_until and user.locked_until > utcnow())


async def login(
    session: AsyncSession,
    username: str,
    password: str,
    *,
    request_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> TokenResponse:
    settings = get_settings()
    if not settings.auth_ready:
        raise ApiError(error_codes.CONFIGURATION_ERROR, "Configuracao de autenticacao incompleta.", status_code=503)

    user = await repository.get_user_by_username(session, username)
    generic_error = AuthenticationError(error_codes.INVALID_CREDENTIALS, "Usuario ou senha invalidos.")
    if user is None:
        await repository.create_security_event(
            session,
            "LOGIN_FAILED",
            actor_user_id=None,
            request_id=request_id,
            ip_address=ip_address,
            user_agent=user_agent,
            success=False,
            details={"reason": "invalid_credentials"},
        )
        await session.commit()
        raise generic_error
    if not user.active:
        await repository.create_security_event(session, "LOGIN_FAILED", actor_user_id=user.id, target_user_id=user.id, request_id=request_id, ip_address=ip_address, user_agent=user_agent, success=False, details={"reason": "inactive"})
        await session.commit()
        raise generic_error
    if is_locked(user):
        await repository.create_security_event(session, "LOGIN_FAILED", actor_user_id=user.id, target_user_id=user.id, request_id=request_id, ip_address=ip_address, user_agent=user_agent, success=False, details={"reason": "locked"})
        await session.commit()
        raise AuthenticationError(error_codes.ACCOUNT_LOCKED, "Conta temporariamente bloqueada.")
    if not verify_password(password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.login_max_failed_attempts:
            user.locked_until = utcnow() + timedelta(minutes=settings.login_lock_minutes)
            await repository.create_security_event(session, "ACCOUNT_LOCKED", actor_user_id=user.id, target_user_id=user.id, request_id=request_id, ip_address=ip_address, user_agent=user_agent, success=True)
        await repository.create_security_event(session, "LOGIN_FAILED", actor_user_id=user.id, target_user_id=user.id, request_id=request_id, ip_address=ip_address, user_agent=user_agent, success=False, details={"reason": "invalid_credentials"})
        await session.commit()
        raise generic_error

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        user.password_changed_at = utcnow()
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = utcnow()

    refresh_token = generate_refresh_token()
    auth_session = AuthSession(
        user_id=user.id,
        refresh_token_hash=hash_refresh_token(refresh_token),
        token_family=uuid.uuid4().hex,
        expires_at=utcnow() + timedelta(days=settings.refresh_token_expire_days),
        created_ip=ip_address,
        last_ip=ip_address,
        user_agent=user_agent,
    )
    session.add(auth_session)
    await session.flush()
    access_token, _expires_at, _jti = create_access_token(user.id, auth_session.id)
    await repository.create_security_event(session, "LOGIN_SUCCESS", actor_user_id=user.id, target_user_id=user.id, request_id=request_id, ip_address=ip_address, user_agent=user_agent)
    await session.commit()
    await session.refresh(user, attribute_names=["roles"])
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, expires_in=settings.access_token_expire_minutes * 60, user=public_user(user))


async def refresh(session: AsyncSession, refresh_token: str, *, request_id: str | None = None, ip_address: str | None = None, user_agent: str | None = None) -> TokenResponse:
    settings = get_settings()
    token_hash = hash_refresh_token(refresh_token)
    auth_session = (await session.execute(select(AuthSession).where(AuthSession.refresh_token_hash == token_hash))).scalars().first()
    if auth_session is None:
        raise AuthenticationError(error_codes.TOKEN_INVALID, "Token invalido.")
    user = await repository.get_user_by_id(session, auth_session.user_id)
    if auth_session.revoked_at is not None:
        await session.execute(update(AuthSession).where(AuthSession.token_family == auth_session.token_family).values(revoked_at=utcnow(), revoke_reason="reuse_detected"))
        await repository.create_security_event(session, "TOKEN_REUSE_DETECTED", actor_user_id=auth_session.user_id, target_user_id=auth_session.user_id, request_id=request_id, ip_address=ip_address, user_agent=user_agent, success=False)
        await session.commit()
        raise AuthenticationError(error_codes.REFRESH_TOKEN_REUSED, "Token reutilizado.")
    if auth_session.expires_at <= utcnow() or user is None or not user.active:
        auth_session.revoked_at = utcnow()
        auth_session.revoke_reason = "expired_or_inactive"
        await session.commit()
        raise AuthenticationError(error_codes.TOKEN_REVOKED, "Sessao expirada ou revogada.")

    auth_session.revoked_at = utcnow()
    auth_session.revoke_reason = "rotated"
    auth_session.last_used_at = utcnow()
    auth_session.last_ip = ip_address
    new_refresh = generate_refresh_token()
    new_session = AuthSession(
        user_id=user.id,
        refresh_token_hash=hash_refresh_token(new_refresh),
        token_family=auth_session.token_family,
        expires_at=utcnow() + timedelta(days=settings.refresh_token_expire_days),
        created_ip=auth_session.created_ip,
        last_ip=ip_address,
        user_agent=user_agent or auth_session.user_agent,
    )
    session.add(new_session)
    await session.flush()
    access_token, _expires_at, _jti = create_access_token(user.id, new_session.id)
    await repository.create_security_event(session, "TOKEN_REFRESHED", actor_user_id=user.id, target_user_id=user.id, request_id=request_id, ip_address=ip_address, user_agent=user_agent)
    await session.commit()
    return TokenResponse(access_token=access_token, refresh_token=new_refresh, expires_in=settings.access_token_expire_minutes * 60, user=public_user(user))


async def logout(session: AsyncSession, refresh_token: str | None, current_user: User, *, request_id: str | None = None) -> None:
    if refresh_token:
        token_hash = hash_refresh_token(refresh_token)
        auth_session = (await session.execute(select(AuthSession).where(AuthSession.refresh_token_hash == token_hash, AuthSession.user_id == current_user.id))).scalars().first()
        if auth_session and auth_session.revoked_at is None:
            auth_session.revoked_at = utcnow()
            auth_session.revoke_reason = "logout"
    await repository.create_security_event(session, "LOGOUT", actor_user_id=current_user.id, target_user_id=current_user.id, request_id=request_id)
    await session.commit()


async def logout_all(session: AsyncSession, current_user: User, *, request_id: str | None = None) -> None:
    await repository.revoke_user_sessions(session, current_user.id, "logout_all")
    await repository.create_security_event(session, "LOGOUT_ALL", actor_user_id=current_user.id, target_user_id=current_user.id, request_id=request_id)
    await session.commit()
