"""ensure_default_admin(): cria o `admin` uma vez com BOOTSTRAP_ADMIN_PASSWORD e
depois nunca mais mexe nele. Regressao do achado 1 de seguranca: antes a API
redefinia a cada startup uma senha fixa do codigo e escrevia a senha no log."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text

from api.app.core.config import get_settings
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker
from api.app.modules.auth import repository
from api.app.modules.auth.bootstrap import ensure_default_admin
from api.app.modules.auth.models import User
from api.app.modules.auth.security import hash_password, verify_password
from api.app.modules.auth.tokens import utcnow


ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "api"
TEST_DATABASE_URL = os.environ.get("POSTGRES_TEST_DATABASE_URL", "")
PASSWORD = "Senha inicial de teste 123"
OTHER_PASSWORD = "Senha trocada pelo admin 456"


def _integration_enabled() -> bool:
    name = urlparse(TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)).path.lstrip("/")
    return bool(TEST_DATABASE_URL) and os.environ.get("APP_ENV") == "test" and "test" in name.lower()


pytestmark = pytest.mark.skipif(not _integration_enabled(), reason="PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")


def _alembic_config() -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    return config


@pytest.fixture(scope="module", autouse=True)
def _database():
    previous = {key: os.environ.get(key) for key in ("DATABASE_URL", "APP_ENV", "SECRET_KEY")}
    os.environ["APP_ENV"] = "test"
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "admin-bootstrap-secret-key-more-than-32-chars"
    get_settings.cache_clear()
    get_engine.cache_clear()
    command.downgrade(_alembic_config(), "base")
    command.upgrade(_alembic_config(), "head")
    # fileConfig() do alembic/env.py desliga loggers ja criados; sem isto o caplog nao ve nada.
    logging.getLogger("api.auth.bootstrap").disabled = False
    yield
    command.upgrade(_alembic_config(), "head")
    asyncio.run(dispose_engine())
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    get_settings.cache_clear()
    get_engine.cache_clear()


@pytest.fixture(autouse=True)
def _clean_users(monkeypatch):
    asyncio.run(_truncate_users())
    _use_password(monkeypatch, "")
    yield
    get_settings.cache_clear()


def _use_password(monkeypatch, value: str) -> None:
    # setenv("") e nao delenv: vence um BOOTSTRAP_ADMIN_PASSWORD de um api/.env local.
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", value)
    get_settings.cache_clear()


async def _truncate_users():
    async with get_engine().begin() as conn:
        await conn.execute(text("TRUNCATE TABLE security_events, auth_sessions, role_permissions, user_roles, users, roles RESTART IDENTITY CASCADE"))


async def _admin() -> User | None:
    async with get_sessionmaker()() as session:
        return await repository.get_user_by_username(session, "admin")


async def _user_count() -> int:
    async with get_sessionmaker()() as session:
        return int((await session.execute(select(func.count()).select_from(User))).scalar_one())


async def _update_admin(**fields) -> None:
    async with get_sessionmaker()() as session:
        user = await repository.get_user_by_username(session, "admin")
        for name, value in fields.items():
            setattr(user, name, value)
        await session.commit()


async def _seed_admin(**fields) -> None:
    async with get_sessionmaker()() as session:
        session.add(User(username="admin", display_name="Administrador", password_hash=hash_password(OTHER_PASSWORD), password_changed_at=utcnow(), **fields))
        await session.commit()


def _bootstrap_logs(caplog) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == "api.auth.bootstrap"]


def test_creates_admin_once_with_env_and_must_change(monkeypatch):
    _use_password(monkeypatch, PASSWORD)
    asyncio.run(ensure_default_admin())
    asyncio.run(ensure_default_admin())

    admin = asyncio.run(_admin())
    assert admin is not None
    assert admin.active and admin.is_superuser and admin.password_must_change
    assert verify_password(PASSWORD, admin.password_hash)
    assert "admin" in {role.code for role in admin.roles}
    assert asyncio.run(_user_count()) == 1


def test_second_startup_does_not_reset_changed_password(monkeypatch):
    _use_password(monkeypatch, PASSWORD)
    asyncio.run(ensure_default_admin())
    changed_hash = hash_password(OTHER_PASSWORD)
    asyncio.run(_update_admin(password_hash=changed_hash, password_must_change=False))

    asyncio.run(ensure_default_admin())

    admin = asyncio.run(_admin())
    assert admin.password_hash == changed_hash
    assert admin.password_must_change is False


def test_does_not_reactivate_disabled_admin(monkeypatch):
    _use_password(monkeypatch, PASSWORD)
    asyncio.run(ensure_default_admin())
    asyncio.run(_update_admin(active=False))

    asyncio.run(ensure_default_admin())

    assert asyncio.run(_admin()).active is False


def test_does_not_touch_superuser_or_must_change_of_existing_admin(monkeypatch):
    asyncio.run(_seed_admin(active=True, is_superuser=False, password_must_change=False))
    before = asyncio.run(_admin())
    _use_password(monkeypatch, PASSWORD)

    asyncio.run(ensure_default_admin())

    admin = asyncio.run(_admin())
    assert admin.is_superuser is False
    assert admin.password_must_change is False
    assert admin.password_hash == before.password_hash
    assert admin.roles == []


def test_without_env_and_with_admin_does_nothing_silently(caplog):
    asyncio.run(_seed_admin(active=False, is_superuser=True, password_must_change=False))
    before = asyncio.run(_admin())
    caplog.set_level(logging.DEBUG)

    asyncio.run(ensure_default_admin())

    admin = asyncio.run(_admin())
    assert (admin.active, admin.is_superuser, admin.password_must_change, admin.password_hash) == (False, True, False, before.password_hash)
    assert _bootstrap_logs(caplog) == []


def test_without_env_and_without_admin_creates_nothing_and_warns(caplog):
    caplog.set_level(logging.DEBUG)

    asyncio.run(ensure_default_admin())

    assert asyncio.run(_user_count()) == 0
    warnings = [record for record in _bootstrap_logs(caplog) if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "BOOTSTRAP_ADMIN_PASSWORD" in warnings[0].getMessage()


def test_password_never_appears_in_logs(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    _use_password(monkeypatch, PASSWORD)

    asyncio.run(ensure_default_admin())
    asyncio.run(_update_admin(active=False))
    asyncio.run(ensure_default_admin())

    admin = asyncio.run(_admin())
    assert _bootstrap_logs(caplog), "a criacao deve registrar um aviso (sem a senha)"
    assert PASSWORD not in caplog.text
    assert admin.password_hash not in caplog.text
