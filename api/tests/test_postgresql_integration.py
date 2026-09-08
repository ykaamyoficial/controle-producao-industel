from __future__ import annotations

import asyncio
import os
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from api.app.core.config import API_CONTRACT_VERSION, API_VERSION, EXPECTED_DATABASE_REVISION, get_settings
from api.app.database.health import current_database_revision, database_check
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker
from api.app.main import create_app


ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "api"
TEST_DATABASE_URL = os.environ.get("POSTGRES_TEST_DATABASE_URL", "")


def _database_name(url: str) -> str:
    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    return parsed.path.lstrip("/")


def _integration_enabled() -> bool:
    return (
        bool(TEST_DATABASE_URL)
        and os.environ.get("APP_ENV") == "test"
        and TEST_DATABASE_URL.startswith("postgresql+asyncpg://")
        and "test" in _database_name(TEST_DATABASE_URL).lower()
    )


def _alembic_config() -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    return config


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class PostgreSQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = {
            "DATABASE_URL": os.environ.get("DATABASE_URL"),
            "APP_ENV": os.environ.get("APP_ENV"),
            "OPERATIONAL_COMPANY_CODE": os.environ.get("OPERATIONAL_COMPANY_CODE"),
            "OPERATIONAL_COMPANY_NAME": os.environ.get("OPERATIONAL_COMPANY_NAME"),
            "OPERATIONAL_ENVIRONMENT_TYPE": os.environ.get("OPERATIONAL_ENVIRONMENT_TYPE"),
        }
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["OPERATIONAL_COMPANY_CODE"] = "teste01"
        os.environ["OPERATIONAL_COMPANY_NAME"] = "teste01"
        os.environ["OPERATIONAL_ENVIRONMENT_TYPE"] = "production"
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

    def tearDown(self):
        asyncio.run(self._truncate_test_data())

    async def _truncate_test_data(self):
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE security_events, auth_sessions, fiscal_events, fiscal_invoice_items, fiscal_invoices, fiscal_items, fiscal_records, expedition_events, expedition_items, galvanization_load_events, galvanization_load_items, galvanization_loads, proposal_events, proposal_items, proposals, sync_runs, role_permissions, user_roles, users, roles RESTART IDENTITY CASCADE"))
            await conn.execute(text("TRUNCATE TABLE system_metadata RESTART IDENTITY"))

    def test_engine_and_select_one(self):
        async def run():
            engine = get_engine()
            self.assertIsNotNone(engine)
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT 1"))
                self.assertEqual(result.scalar_one(), 1)

        asyncio.run(run())

    def test_async_session_rolls_back_after_exception(self):
        async def run():
            session_factory = get_sessionmaker()
            self.assertIsNotNone(session_factory)
            async with session_factory() as session:
                with self.assertRaises(RuntimeError):
                    async with session.begin():
                        await session.execute(
                            text("INSERT INTO system_metadata (key, value) VALUES ('rollback_test', '{\"ok\": true}')")
                        )
                        raise RuntimeError("force rollback")

            async with session_factory() as session:
                result = await session.execute(text("SELECT count(*) FROM system_metadata WHERE key='rollback_test'"))
                self.assertEqual(result.scalar_one(), 0)

        asyncio.run(run())

    def test_unique_constraint_on_system_metadata_key(self):
        async def run():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                await session.execute(text("INSERT INTO system_metadata (key, value) VALUES ('unique_key', '{}')"))
                await session.commit()
                with self.assertRaises(Exception):
                    await session.execute(text("INSERT INTO system_metadata (key, value) VALUES ('unique_key', '{}')"))
                    await session.commit()
                await session.rollback()

        asyncio.run(run())

    def test_readiness_with_available_database(self):
        client = TestClient(create_app())
        response = client.get("/api/v1/system/ready")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready", "database": "connected", "mode": "development"})

    def test_version_reports_current_revision(self):
        client = TestClient(create_app())
        response = client.get("/api/v1/system/version")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["database_revision"], EXPECTED_DATABASE_REVISION)
        self.assertEqual(response.json()["database_status"], "compatible")

    def test_compatibility_reports_current_state_from_real_database(self):
        client = TestClient(create_app())
        first = client.get("/api/v1/system/compatibility")
        second = client.get("/api/v1/system/compatibility")

        self.assertEqual(first.status_code, 200)
        body = first.json()
        self.assertEqual(body["database_revision"], EXPECTED_DATABASE_REVISION)
        self.assertEqual(body["server_version"], API_VERSION)
        self.assertEqual(body["api_contract_version"], API_CONTRACT_VERSION)
        self.assertEqual(first.json(), second.json())

    def test_identity_reports_stable_instance_and_company_context(self):
        client = TestClient(create_app())

        first = client.get("/api/v1/system/identity")
        second = client.get("/api/v1/system/identity")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        first_body = first.json()
        second_body = second.json()
        uuid.UUID(first_body["instance_id"])
        self.assertEqual(first_body["instance_id"], second_body["instance_id"])
        self.assertEqual(first_body["company_code"], "teste01")
        self.assertEqual(first_body["company_name"], "teste01")
        self.assertEqual(first_body["environment_type"], "production")
        self.assertEqual(first_body["api_name"], "controle-producao-api")
        self.assertEqual(first_body["database_revision"], EXPECTED_DATABASE_REVISION)
        self.assertEqual(first_body["database_status"], "compatible")

    def test_current_revision_and_compatibility(self):
        async def run():
            self.assertEqual(await current_database_revision(), EXPECTED_DATABASE_REVISION)
            check = await database_check()
            self.assertEqual(check.status, "connected")
            self.assertEqual(check.revision_status, "compatible")

        asyncio.run(run())

    def test_migration_downgrade_and_reapply(self):
        command.downgrade(_alembic_config(), "base")
        command.upgrade(_alembic_config(), "head")

        async def run():
            self.assertEqual(await current_database_revision(), EXPECTED_DATABASE_REVISION)

        asyncio.run(run())

    def test_only_structural_tables_exist(self):
        async def run():
            engine = get_engine()
            async with engine.connect() as conn:
                result = await conn.execute(
                    text(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = 'public'
                        ORDER BY table_name
                        """
                    )
                )
                self.assertEqual(
                    [row[0] for row in result],
                    [
                        "alembic_version",
                        "auth_sessions",
                        "chat_attachments",
                        "chat_conversations",
                        "chat_message_reads",
                        "chat_messages",
                        "chat_notifications",
                        "client_installations",
                        "expedition_events",
                        "expedition_items",
                        "fiscal_events",
                        "fiscal_invoice_items",
                        "fiscal_invoices",
                        "fiscal_items",
                        "fiscal_records",
                        "galvanization_load_events",
                        "galvanization_load_items",
                        "galvanization_loads",
                        "notification_deliveries",
                        "notification_preferences",
                        "notification_user_settings",
                        "notifications",
                        "permissions",
                        "pilot_client_reports",
                        "product_catalog_entries",
                        "production_allocation_transfers",
                        "proposal_events",
                        "proposal_items",
                        "proposal_remanagement_items",
                        "proposal_remanagements",
                        "proposals",
                        "role_permissions",
                        "roles",
                        "security_events",
                        "sync_runs",
                        "system_metadata",
                        "update_audit_events",
                        "user_roles",
                        "users",
                    ],
                )

        asyncio.run(run())

    def test_pool_can_be_closed_and_recreated(self):
        async def run():
            first = get_engine()
            await dispose_engine()
            second = get_engine()
            self.assertIsNotNone(second)
            self.assertIsNot(first, second)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
