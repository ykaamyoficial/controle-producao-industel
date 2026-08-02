from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import select
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from api.app.core.config import EXPECTED_DATABASE_REVISION, get_settings
from api.app.database.health import current_database_revision
from api.app.database.session import dispose_engine, get_sessionmaker
from api.app.modules.auth import repository
from api.app.modules.auth.models import Permission, Role, User
from api.app.modules.auth.permissions import ADMIN_PERMISSION_CODES
from api.app.modules.auth.security import hash_password
from api.app.modules.auth.tokens import utcnow


def _read_secret(prompt: str, env_name: str) -> str:
    value = os.environ.get(env_name)
    if value:
        return value
    return getpass.getpass(prompt)


def _read_text(prompt: str, env_name: str, default: str | None = None) -> str:
    value = os.environ.get(env_name)
    if value:
        return value
    entered = input(prompt).strip()
    if entered:
        return entered
    if default is not None:
        return default
    return ""


async def create_admin(_args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.auth_ready:
        print("SECRET_KEY obrigatoria ausente ou fraca. Defina uma chave com pelo menos 32 caracteres.", file=sys.stderr)
        return 2

    revision = await current_database_revision()
    if revision != EXPECTED_DATABASE_REVISION:
        print(f"Revisao atual {revision!r} incompativel. Execute a migration ate {EXPECTED_DATABASE_REVISION}.", file=sys.stderr)
        return 2

    session_factory = get_sessionmaker()
    if session_factory is None:
        print("DATABASE_URL nao configurada.", file=sys.stderr)
        return 2

    username = repository.normalize_username(_read_text("Login do administrador: ", "API_BOOTSTRAP_USERNAME"))
    display_name = _read_text("Nome exibido: ", "API_BOOTSTRAP_DISPLAY_NAME", username)
    password = _read_secret("Senha do administrador: ", "API_BOOTSTRAP_PASSWORD")

    if not username:
        print("Login obrigatorio.", file=sys.stderr)
        return 2

    async with session_factory() as session:
        if await repository.active_admin_count(session) > 0:
            print("Ja existe administrador ativo. Bootstrap cancelado.", file=sys.stderr)
            return 1

        permissions = (await session.execute(select(Permission).where(Permission.code.in_(ADMIN_PERMISSION_CODES)))).scalars().all()
        found_codes = {permission.code for permission in permissions}
        missing = sorted(set(ADMIN_PERMISSION_CODES) - found_codes)
        if missing:
            print(f"Permissoes oficiais ausentes: {', '.join(missing)}", file=sys.stderr)
            return 2

        admin_role = (await session.execute(select(Role).options(selectinload(Role.permissions)).where(Role.code == "admin"))).scalars().first()
        if admin_role is None:
            admin_role = Role(
                code="admin",
                name="Administrador",
                description="Perfil de sistema com permissoes administrativas da API.",
                active=True,
                system_role=True,
            )
        else:
            admin_role.name = "Administrador"
            admin_role.active = True
            admin_role.system_role = True
        admin_role.permissions.clear()
        admin_role.permissions.extend(sorted(permissions, key=lambda permission: permission.code))
        session.add(admin_role)
        await session.flush()

        user = User(
            username=username,
            display_name=display_name.strip() or username,
            password_hash=hash_password(password),
            active=True,
            is_superuser=True,
            password_changed_at=utcnow(),
        )
        user.roles.append(admin_role)
        session.add(user)
        await session.flush()
        await repository.create_security_event(
            session,
            "ADMIN_BOOTSTRAP",
            actor_user_id=user.id,
            target_user_id=user.id,
            success=True,
            details={"role_id": admin_role.id},
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            print("Nao foi possivel criar administrador: login ou perfil ja existe.", file=sys.stderr)
            return 1

    print(f"Administrador criado com sucesso: {username}")
    return 0


async def reset_proposals_development_data(_args: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.app_env not in {"development", "test"}:
        print("Recusado: limpeza de propostas somente pode rodar em development ou test.", file=sys.stderr)
        return 2
    revision = await current_database_revision()
    if revision != EXPECTED_DATABASE_REVISION:
        print(f"Revisao atual {revision!r} incompativel. Execute a migration ate {EXPECTED_DATABASE_REVISION}.", file=sys.stderr)
        return 2
    session_factory = get_sessionmaker()
    if session_factory is None:
        print("DATABASE_URL nao configurada.", file=sys.stderr)
        return 2
    async with session_factory() as session:
        await session.execute(sa.text("TRUNCATE proposal_events, proposal_items, proposals, sync_runs RESTART IDENTITY CASCADE"))
        await session.commit()
    print("Dados de propostas/itens de desenvolvimento removidos com sucesso.")
    return 0


async def _run(args: argparse.Namespace) -> int:
    try:
        if args.command == "create-admin":
            return await create_admin(args)
        if args.command == "reset-proposals-development-data":
            return await reset_proposals_development_data(args)
        return 2
    finally:
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m api.app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("create-admin", help="Cria manualmente o primeiro administrador da API.")
    subparsers.add_parser("reset-proposals-development-data", help="Remove dados de propostas/itens apenas em development ou test.")
    raise SystemExit(asyncio.run(_run(parser.parse_args())))


if __name__ == "__main__":
    main()
