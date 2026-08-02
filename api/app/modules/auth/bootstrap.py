from __future__ import annotations

import logging

from api.app.database.session import get_sessionmaker
from api.app.modules.auth import repository
from api.app.modules.auth.models import User
from api.app.modules.auth.security import hash_password
from api.app.modules.auth.tokens import utcnow
from api.app.modules.provisioning.service import _ensure_admin_role

log = logging.getLogger("api.auth.bootstrap")
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin12345"


async def ensure_default_admin() -> None:
    session_factory = get_sessionmaker()
    if session_factory is None:
        raise RuntimeError("DATABASE_URL nao configurada.")

    async with session_factory() as session:
        username = repository.normalize_username(DEFAULT_ADMIN_USERNAME)
        existing = await repository.get_user_by_username(session, username)

        # Se já existe, sempre garante que admin/admin funcione.
        if existing is not None:
            existing.password_hash = hash_password(DEFAULT_ADMIN_PASSWORD)
            existing.active = True
            existing.is_superuser = True
            existing.password_must_change = False
            existing.password_changed_at = utcnow()

            role = await _ensure_admin_role(session)
            if role not in existing.roles:
                existing.roles.append(role)

            await session.commit()

            log.warning(
                "Administrador padrao atualizado | usuario=%s | senha=%s",
                DEFAULT_ADMIN_USERNAME,
                DEFAULT_ADMIN_PASSWORD,
            )
            return

        # Se não existe, cria automaticamente.
        role = await _ensure_admin_role(session)

        user = User(
            username=username,
            display_name="Administrador",
            password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
            active=True,
            is_superuser=True,
            password_must_change=False,
            password_changed_at=utcnow(),
        )

        user.roles.append(role)

        session.add(user)
        await session.commit()

        log.warning(
            "Administrador padrao criado automaticamente | usuario=%s | senha=%s",
            DEFAULT_ADMIN_USERNAME,
            DEFAULT_ADMIN_PASSWORD,
        )
