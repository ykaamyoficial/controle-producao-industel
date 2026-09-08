from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from api.app.core import error_codes
from api.app.core.config import get_settings
from api.app.core.exceptions import ApiError
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker
from api.app.modules.auth.bootstrap import sync_official_permissions
from api.app.modules.auth.models import Permission, User
from api.app.modules.auth.permissions import CHAT_SEND, CHAT_VIEW, OFFICIAL_PERMISSIONS, PROPOSALS_VIEW, USERS_VIEW
from api.app.modules.auth.security import hash_password
from api.app.modules.auth.tokens import utcnow
from api.app.modules.users import service as users_service
from api.app.modules.users.schemas import UserCreate


ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "api"
TEST_DATABASE_URL = os.environ.get("POSTGRES_TEST_DATABASE_URL", "")


def _database_name(url: str) -> str:
    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    return parsed.path.lstrip("/")


def _integration_enabled() -> bool:
    return bool(TEST_DATABASE_URL) and os.environ.get("APP_ENV") == "test" and "test" in _database_name(TEST_DATABASE_URL).lower()


def _alembic_config() -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    return config


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class PermissionCatalogSyncTests(unittest.TestCase):
    """Regressao do incidente: tabela `permissions` esvaziada (por um reset
    de dados fora do Alembic) fazia toda criacao/edicao de usuario com
    permissoes granulares falhar com 'Permissao inexistente', mesmo pra
    codigos validos — porque as migrations soh inserem o catalogo uma vez,
    na primeira aplicacao, sem mecanismo de re-seed. sync_official_permissions()
    e a correcao: idempotente, roda no startup, nunca apaga nada."""

    @classmethod
    def setUpClass(cls):
        cls.previous = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "APP_ENV": os.environ.get("APP_ENV"), "SECRET_KEY": os.environ.get("SECRET_KEY")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "permission-sync-secret-key-more-than-32-chars"
        get_settings.cache_clear()
        get_engine.cache_clear()
        command.downgrade(_alembic_config(), "base")
        command.upgrade(_alembic_config(), "head")

    @classmethod
    def tearDownClass(cls):
        command.upgrade(_alembic_config(), "head")
        asyncio.run(dispose_engine())
        for key, value in cls.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        get_engine.cache_clear()

    def setUp(self):
        asyncio.run(self._empty_permissions_table())

    async def _empty_permissions_table(self):
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "TRUNCATE TABLE role_permissions, user_roles, users, roles, permissions RESTART IDENTITY CASCADE"
                )
            )

    def test_sync_populates_empty_permissions_table(self):
        asyncio.run(self._run_sync_and_assert_full_catalog())

    async def _run_sync_and_assert_full_catalog(self):
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            count_before = (await session.execute(select(Permission))).scalars().all()
            self.assertEqual(len(count_before), 0)

        await sync_official_permissions()

        async with session_factory() as session:
            codes = set((await session.execute(select(Permission.code))).scalars().all())
        self.assertEqual(codes, {code for code, _name, _module in OFFICIAL_PERMISSIONS})

    def test_sync_is_idempotent(self):
        asyncio.run(self._run_sync_twice_and_assert_no_duplicates())

    async def _run_sync_twice_and_assert_no_duplicates(self):
        await sync_official_permissions()
        await sync_official_permissions()

        session_factory = get_sessionmaker()
        async with session_factory() as session:
            rows = (await session.execute(select(Permission))).scalars().all()
        self.assertEqual(len(rows), len(OFFICIAL_PERMISSIONS))

    def test_valid_permission_codes_accepted_after_sync(self):
        asyncio.run(self._create_user_with_valid_codes())

    async def _create_user_with_valid_codes(self):
        await sync_official_permissions()
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            actor = User(username="actor", display_name="Actor", password_hash=hash_password("senha-atriz-teste-123"), active=True, is_superuser=True, password_changed_at=utcnow())
            session.add(actor)
            await session.flush()

            payload = UserCreate(
                username="novo.usuario",
                display_name="Novo Usuario",
                password="senha-teste-123",
                permission_codes=[PROPOSALS_VIEW, CHAT_VIEW, CHAT_SEND, USERS_VIEW],
            )
            created = await users_service.create_user(session, payload, actor)
            self.assertIsNotNone(created.id)

    def test_invalid_permission_code_still_rejected(self):
        asyncio.run(self._create_user_with_invalid_code())

    async def _create_user_with_invalid_code(self):
        await sync_official_permissions()
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            actor = User(username="actor2", display_name="Actor2", password_hash=hash_password("senha-atriz-teste-123"), active=True, is_superuser=True, password_changed_at=utcnow())
            session.add(actor)
            await session.flush()

            payload = UserCreate(
                username="outro.usuario",
                display_name="Outro Usuario",
                password="senha-teste-123",
                permission_codes=[PROPOSALS_VIEW, "isso.nao.existe"],
            )
            with self.assertRaises(ApiError) as ctx:
                await users_service.create_user(session, payload, actor)
            self.assertEqual(ctx.exception.code, error_codes.PERMISSION_NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
