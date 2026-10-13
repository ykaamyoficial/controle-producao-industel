from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core import error_codes
from api.app.core.config import get_settings
from api.app.core.exceptions import AuthenticationError
from api.app.modules.auth import repository
from api.app.modules.auth.models import User
from api.app.modules.auth.permissions import NOTIFICATIONS_VIEW
from api.app.modules.auth.service import effective_permissions
from api.app.modules.auth.tokens import (
    create_notifier_token,
    decode_notifier_token,
    generate_refresh_token,
    hash_refresh_token,
    utcnow,
)
from api.app.modules.notifications.models import NotificationDevice
from api.app.modules.notifications.schemas import (
    NotifierDeviceRegistered,
    NotifierDeviceRegisterPayload,
    NotifierTokenResponse,
    NotifierUserOut,
)

logger = logging.getLogger("api.notifications.devices")


def _user_out(user: User) -> NotifierUserOut:
    return NotifierUserOut(id=user.id, username=user.username, display_name=user.display_name)


def _can_receive(user: User | None) -> bool:
    if user is None or not user.active:
        return False
    return user.is_superuser or NOTIFICATIONS_VIEW in effective_permissions(user)


async def register_device(
    session: AsyncSession,
    actor: User,
    payload: NotifierDeviceRegisterPayload,
    *,
    request_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> NotifierDeviceRegistered:
    """Chamado pelo Desktop logo apos o login. O ultimo login vence: qualquer
    credencial ativa da mesma instalacao + usuario do Windows e revogada, seja
    de quem for."""
    settings = get_settings()
    installation_id = payload.installation_id.strip()
    os_user = payload.os_user.strip().lower()
    now = utcnow()
    await session.execute(
        update(NotificationDevice)
        .where(
            NotificationDevice.installation_id == installation_id,
            NotificationDevice.os_user == os_user,
            NotificationDevice.revoked_at.is_(None),
        )
        .values(revoked_at=now, revoke_reason="replaced_by_login")
    )
    device_token = generate_refresh_token()
    device = NotificationDevice(
        user_id=actor.id,
        installation_id=installation_id,
        os_user=os_user,
        device_name=(payload.device_name or "").strip() or None,
        token_hash=hash_refresh_token(device_token),
        expires_at=now + timedelta(days=settings.notifier_device_expire_days),
    )
    session.add(device)
    await repository.create_security_event(
        session,
        "NOTIFIER_DEVICE_REGISTERED",
        actor_user_id=actor.id,
        target_user_id=actor.id,
        request_id=request_id,
        ip_address=ip_address,
        user_agent=user_agent,
        details={"installation_id": installation_id, "device_name": device.device_name},
    )
    await session.commit()
    return NotifierDeviceRegistered(device_token=device_token, expires_at=device.expires_at, user=_user_out(actor))


async def exchange_token(session: AsyncSession, device_token: str) -> NotifierTokenResponse:
    """Troca a credencial do computador por um token curto so de avisos. A
    credencial NAO rotaciona (sem disputa entre processos); so a validade
    desliza: cada uso empurra o vencimento para mais N dias."""
    settings = get_settings()
    device = (
        await session.execute(
            select(NotificationDevice).where(NotificationDevice.token_hash == hash_refresh_token(device_token))
        )
    ).scalars().first()
    if device is None:
        raise AuthenticationError(error_codes.TOKEN_INVALID, "Token invalido.")
    if device.revoked_at is not None:
        raise AuthenticationError(error_codes.TOKEN_REVOKED, "Credencial de avisos revogada.")
    now = utcnow()
    user = await repository.get_user_by_id(session, device.user_id)
    if device.expires_at <= now or not _can_receive(user):
        device.revoked_at = now
        device.revoke_reason = "expired_or_inactive"
        await session.commit()
        raise AuthenticationError(error_codes.TOKEN_REVOKED, "Credencial de avisos expirada ou revogada.")
    device.last_used_at = now
    device.expires_at = now + timedelta(days=settings.notifier_device_expire_days)
    access_token, _expires_at = create_notifier_token(user.id, device.id)
    await session.commit()
    return NotifierTokenResponse(
        access_token=access_token,
        expires_in=settings.access_token_expire_minutes * 60,
        user=_user_out(user),
    )


async def authenticate_notifier(session: AsyncSession, token: str) -> tuple[User, int]:
    """Valida o token curto E a credencial por tras dele: um novo login no
    mesmo computador (ou a revogacao da conta) corta o agente na hora, sem
    esperar o token curto vencer. Devolve (usuario, exp)."""
    payload = decode_notifier_token(token)
    device = await session.get(NotificationDevice, int(payload["did"]))
    if device is None or device.revoked_at is not None or device.user_id != int(payload["sub"]):
        raise AuthenticationError(error_codes.TOKEN_REVOKED, "Credencial de avisos revogada.")
    user = await repository.get_user_by_id(session, device.user_id)
    if not _can_receive(user):
        raise AuthenticationError(error_codes.TOKEN_REVOKED, "Credencial de avisos revogada.")
    return user, int(payload["exp"])
