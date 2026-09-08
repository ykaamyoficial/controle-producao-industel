from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config

from api.app.channels import installations
from api.app.channels.models import Channel
from api.app.core.config import get_settings
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker
from sqlalchemy import text

TEST_DATABASE_URL = os.environ.get("POSTGRES_TEST_DATABASE_URL", "")


def _database_name(url: str) -> str:
    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    return parsed.path.lstrip("/")


def _integration_enabled() -> bool:
    return bool(TEST_DATABASE_URL) and os.environ.get("APP_ENV") == "test" and "test" in _database_name(TEST_DATABASE_URL).lower()


def _alembic_config() -> Config:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "api" / "alembic.ini"))
    config.set_main_option("script_location", str(root / "api" / "alembic"))
    return config


@unittest.skipUnless(_integration_enabled(), "Exige APP_ENV=test e POSTGRES_TEST_DATABASE_URL (mesmo guard das demais integracoes Postgres).")
class ClientInstallationRepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "APP_ENV": os.environ.get("APP_ENV")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
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
        asyncio.run(self._truncate())

    async def _truncate(self):
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE client_installations, pilot_client_reports RESTART IDENTITY CASCADE"))

    def _run(self, coro):
        return asyncio.run(coro)

    async def _session(self):
        return get_sessionmaker()()

    def test_resolve_channel_falls_back_to_production_when_no_installation_id(self):
        async def scenario():
            async with await self._session() as session:
                return await installations.resolve_channel(session, None)

        self.assertEqual(self._run(scenario()), Channel.PRODUCTION)

    def test_resolve_channel_falls_back_to_production_when_unknown(self):
        async def scenario():
            async with await self._session() as session:
                return await installations.resolve_channel(session, "never-registered")

        self.assertEqual(self._run(scenario()), Channel.PRODUCTION)

    def test_upsert_heartbeat_creates_row_in_production_by_default(self):
        async def scenario():
            async with await self._session() as session:
                row = await installations.upsert_heartbeat(
                    session, installation_id="pc-new", machine_name="PC-NEW", os_version="Windows", current_desktop_version="3.2.0",
                )
                return row

        row = self._run(scenario())
        self.assertEqual(row.channel, Channel.PRODUCTION.value)
        self.assertEqual(row.current_desktop_version, "3.2.0")
        self.assertIsNotNone(row.last_seen_at)

    def test_upsert_heartbeat_updates_existing_row_without_changing_channel(self):
        async def scenario():
            async with await self._session() as session:
                await installations.assign_channel(session, "pc-1", channel=Channel.PILOT, actor="admin")
            async with await self._session() as session:
                return await installations.upsert_heartbeat(
                    session, installation_id="pc-1", machine_name=None, os_version=None, current_desktop_version="3.4.0",
                )

        row = self._run(scenario())
        self.assertEqual(row.channel, Channel.PILOT.value)
        self.assertEqual(row.current_desktop_version, "3.4.0")

    def test_assign_then_resolve_channel_returns_assigned_channel(self):
        async def scenario():
            async with await self._session() as session:
                await installations.assign_channel(session, "pc-pilot", channel=Channel.PILOT, actor="admin")
            async with await self._session() as session:
                return await installations.resolve_channel(session, "pc-pilot")

        self.assertEqual(self._run(scenario()), Channel.PILOT)

    def test_remove_assignment_falls_back_to_production(self):
        async def scenario():
            async with await self._session() as session:
                await installations.assign_channel(session, "pc-1", channel=Channel.PILOT, actor="admin")
            async with await self._session() as session:
                row = await installations.remove_channel_assignment(session, "pc-1", actor="admin")
                return row

        row = self._run(scenario())
        self.assertEqual(row.channel, Channel.PRODUCTION.value)

    def test_count_pilot_clients_reflects_assignments(self):
        async def scenario():
            async with await self._session() as session:
                await installations.assign_channel(session, "pc-1", channel=Channel.PILOT, actor="admin")
                await installations.assign_channel(session, "pc-2", channel=Channel.PILOT, actor="admin")
                await installations.assign_channel(session, "pc-3", channel=Channel.PRODUCTION, actor="admin")
            async with await self._session() as session:
                return await installations.count_pilot_clients(session)

        self.assertEqual(self._run(scenario()), 2)

    def test_submit_and_list_pilot_reports_never_include_operational_fields(self):
        async def scenario():
            async with await self._session() as session:
                await installations.submit_pilot_report(
                    session, installation_id="pc-1", release_version="3.3.0",
                    update_result="SUCCESS", app_start_result="SUCCESS", compatibility_result="OK", error_code=None,
                )
            async with await self._session() as session:
                return await installations.list_reports_for_version(session, "3.3.0")

        reports = self._run(scenario())
        self.assertEqual(len(reports), 1)
        fields = {column.name for column in reports[0].__table__.columns}
        self.assertEqual(
            fields,
            {"id", "installation_id", "release_version", "update_result", "app_start_result", "compatibility_result", "error_code", "reported_at"},
        )


if __name__ == "__main__":
    unittest.main()
