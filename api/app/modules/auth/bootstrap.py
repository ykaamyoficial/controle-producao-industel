from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from api.app.core.config import get_settings
from api.app.database.session import get_sessionmaker
from api.app.modules.auth import repository
from api.app.modules.auth.models import Permission, User
from api.app.modules.auth.permissions import OFFICIAL_PERMISSIONS
from api.app.modules.auth.security import hash_password
from api.app.modules.auth.tokens import utcnow
from api.app.modules.provisioning.service import _ensure_admin_role

log = logging.getLogger("api.auth.bootstrap")
DEFAULT_ADMIN_USERNAME = "admin"


async def sync_official_permissions() -> None:
    """Garante que o catalogo oficial de permissoes (OFFICIAL_PERMISSIONS)
    existe na tabela `permissions` — idempotente: so insere o que estiver
    faltando, nunca apaga ou altera uma permissao ja existente (mesmo que
    tenha sido criada por outra via). Historicamente cada modulo inseria seu
    pedaco do catalogo direto numa migration (bulk_insert), sem um jeito de
    "re-seedar" se a tabela for esvaziada por fora do Alembic (ex: reset de
    dados de ambiente) — isso e o que da esse sync aqui, chamado sempre no
    startup, antes de ensure_default_admin() (que depende das permissoes ja
    existirem pra vincular o papel do admin corretamente)."""
    session_factory = get_sessionmaker()
    if session_factory is None:
        raise RuntimeError("DATABASE_URL nao configurada.")

    async with session_factory() as session:
        existing_codes = set((await session.execute(select(Permission.code))).scalars().all())
        missing = [(code, name, module) for code, name, module in OFFICIAL_PERMISSIONS if code not in existing_codes]
        if not missing:
            return
        # INSERT ... ON CONFLICT DO NOTHING (nao um simples add()+commit): dois
        # processos podem chamar sync_official_permissions() no startup ao
        # mesmo tempo (ex.: dois workers/instancias da API subindo juntos) e
        # ambos verem o mesmo codigo como "faltando" antes de qualquer commit -
        # sem o ON CONFLICT, o segundo a commitar estoura UniqueViolationError
        # em vez de simplesmente nao duplicar a linha.
        await session.execute(
            pg_insert(Permission)
            .values([{"code": code, "name": name, "module": module} for code, name, module in missing])
            .on_conflict_do_nothing(index_elements=["code"])
        )
        await session.commit()
        log.warning("Catalogo de permissoes sincronizado | inseridas=%s", [code for code, _name, _module in missing])


async def ensure_default_admin() -> None:
    """Cria o usuario `admin` UMA vez, com a senha de BOOTSTRAP_ADMIN_PASSWORD e
    troca obrigatoria no primeiro login. Se o `admin` ja existe (mesmo
    desativado, sem superusuario ou com senha trocada) nao toca em nada: nunca
    redefine senha, nunca reativa. A senha nunca vai para o log."""
    session_factory = get_sessionmaker()
    if session_factory is None:
        raise RuntimeError("DATABASE_URL nao configurada.")

    async with session_factory() as session:
        username = repository.normalize_username(DEFAULT_ADMIN_USERNAME)
        if await repository.get_user_by_username(session, username) is not None:
            return

        password = get_settings().bootstrap_admin_password
        if not password:
            log.warning("Usuario %s nao existe e BOOTSTRAP_ADMIN_PASSWORD nao esta definida; administrador inicial nao criado.", username)
            return

        role = await _ensure_admin_role(session)
        user = User(
            username=username,
            display_name="Administrador",
            password_hash=hash_password(password),
            active=True,
            is_superuser=True,
            password_must_change=True,
            password_changed_at=utcnow(),
        )
        user.roles.append(role)
        session.add(user)
        try:
            await session.commit()
        except IntegrityError:
            # Outro processo da API subindo junto criou o admin primeiro.
            await session.rollback()
            return

        log.warning("Administrador inicial criado | usuario=%s | troca de senha obrigatoria no primeiro login", username)
