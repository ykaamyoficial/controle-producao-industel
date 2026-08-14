from __future__ import annotations

import asyncio
import os
import unittest

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from api.app.core.config import EXPECTED_DATABASE_REVISION, get_settings
from api.app.core.migration_state import build_migration_state
from api.app.database.health import current_database_revision
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker
from api.app.main import create_app
from api.app.modules.proposals.models import Proposal
from api.tests._migration_test_support import alembic_config, integration_enabled, temporary_chain_with_broken_head

TEST_DATABASE_URL = os.environ.get("POSTGRES_TEST_DATABASE_URL", "")

_SKIP_REASON = "Testes de migration exigem APP_ENV=test e POSTGRES_TEST_DATABASE_URL apontando para um banco de teste descartavel."


def _swap_env_for_test_database() -> dict[str, str | None]:
    previous = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "APP_ENV": os.environ.get("APP_ENV")}
    os.environ["APP_ENV"] = "test"
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    get_settings.cache_clear()
    get_engine.cache_clear()
    return previous


def _restore_env(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    get_settings.cache_clear()
    get_engine.cache_clear()


@unittest.skipUnless(integration_enabled(), _SKIP_REASON)
class FreshDatabaseMigrationTests(unittest.TestCase):
    """Secao 21 da Fase 04: banco vazio deve aplicar toda a cadeia ate o head."""

    @classmethod
    def setUpClass(cls):
        cls.previous_env = _swap_env_for_test_database()

    @classmethod
    def tearDownClass(cls):
        command.upgrade(alembic_config(), "head")
        asyncio.run(dispose_engine())
        _restore_env(cls.previous_env)

    def test_fresh_database_reaches_expected_head_in_order(self):
        command.downgrade(alembic_config(), "base")
        command.upgrade(alembic_config(), "head")

        async def run():
            revision = await current_database_revision()
            self.assertEqual(revision, EXPECTED_DATABASE_REVISION)
            engine = get_engine()
            async with engine.connect() as conn:
                # constraint basica (seed de permissoes da migration 0002) existe
                result = await conn.execute(text("SELECT count(*) FROM permissions"))
                self.assertGreater(result.scalar_one(), 0)

        asyncio.run(run())

        state = build_migration_state(EXPECTED_DATABASE_REVISION)
        self.assertTrue(state.is_at_head)
        self.assertTrue(state.migration_history_consistent)

    def test_app_initializes_and_serves_against_fresh_database(self):
        command.downgrade(alembic_config(), "base")
        command.upgrade(alembic_config(), "head")

        client = TestClient(create_app())
        response = client.get("/api/v1/system/ready")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["database"], "connected")


@unittest.skipUnless(integration_enabled(), _SKIP_REASON)
class UpgradeFromEarlierRevisionTests(unittest.TestCase):
    """Secao 22 da Fase 04: dados pre-existentes de uma revisao anterior suportada
    devem sobreviver ao upgrade, com backfill correto e sem perda silenciosa."""

    @classmethod
    def setUpClass(cls):
        cls.previous_env = _swap_env_for_test_database()

    @classmethod
    def tearDownClass(cls):
        command.upgrade(alembic_config(), "head")
        asyncio.run(dispose_engine())
        _restore_env(cls.previous_env)

    def test_upgrade_preserves_data_and_backfills_new_weight_columns(self):
        # 20260807_0014 e a revisao imediatamente anterior a 20260810_0015 (que
        # introduz weight_source/weight_status com NOT NULL + server_default e
        # afrouxa unit_weight/total_weight para nullable).
        command.downgrade(alembic_config(), "base")
        command.upgrade(alembic_config(), "20260807_0014")

        async def seed():
            engine = get_engine()
            async with engine.begin() as conn:
                await conn.execute(
                    text("INSERT INTO proposals (proposal_number, customer_name) VALUES ('PROP-F04-0001', 'Cliente Teste Fase 04')")
                )
                await conn.execute(
                    text(
                        "INSERT INTO proposal_items "
                        "(proposal_id, item_number, description, quantity, unit_weight, total_weight, produce_internally, requires_galvanization) "
                        "SELECT id, 'ITEM-01', 'Peca de teste', 10, 2.5, 25.0, 'YES', 'NO' "
                        "FROM proposals WHERE proposal_number = 'PROP-F04-0001'"
                    )
                )

        asyncio.run(seed())

        command.upgrade(alembic_config(), "head")

        async def check_raw():
            engine = get_engine()
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text(
                            "SELECT weight_source, weight_status, unit_weight, total_weight "
                            "FROM proposal_items JOIN proposals ON proposals.id = proposal_items.proposal_id "
                            "WHERE proposals.proposal_number = 'PROP-F04-0001'"
                        )
                    )
                ).one()
                # backfill pelo server_default da migration 0015, dado que a linha
                # ja existia antes da coluna ser criada
                self.assertEqual(row.weight_source, "LEGACY")
                self.assertEqual(row.weight_status, "LEGACY")
                # dados pre-existentes preservados (nao zerados pelo afrouxamento
                # de NOT NULL para nullable)
                self.assertEqual(float(row.unit_weight), 2.5)
                self.assertEqual(float(row.total_weight), 25.0)

        asyncio.run(check_raw())

        async def check_via_orm():
            # a API atual (schema final, modelos atuais) consegue consultar os
            # dados migrados normalmente
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                result = await session.execute(select(Proposal).where(Proposal.proposal_number == "PROP-F04-0001"))
                proposal = result.scalar_one()
                self.assertEqual(len(proposal.items), 1)
                self.assertEqual(proposal.items[0].weight_source, "LEGACY")

        asyncio.run(check_via_orm())


@unittest.skipUnless(integration_enabled(), _SKIP_REASON)
class MigrationFailureAtomicityTests(unittest.TestCase):
    """Secao 23 da Fase 04: uma migration que falha deve reverter por completo,
    sem avancar a revisao registrada e sem deixar o banco inconsistente."""

    @classmethod
    def setUpClass(cls):
        cls.previous_env = _swap_env_for_test_database()
        command.downgrade(alembic_config(), "base")
        command.upgrade(alembic_config(), "head")

    @classmethod
    def tearDownClass(cls):
        command.upgrade(alembic_config(), "head")
        asyncio.run(dispose_engine())
        _restore_env(cls.previous_env)

    def test_failed_migration_rolls_back_transaction_and_does_not_advance_revision(self):
        before = asyncio.run(current_database_revision())
        self.assertEqual(before, EXPECTED_DATABASE_REVISION)

        with temporary_chain_with_broken_head(EXPECTED_DATABASE_REVISION) as (broken_config, broken_revision):
            with self.assertRaises(Exception):
                command.upgrade(broken_config, broken_revision)

        async def check_after():
            revision = await current_database_revision()
            self.assertEqual(revision, before, "revision nao pode avancar quando a migration falha")

            engine = get_engine()
            async with engine.connect() as conn:
                probe_exists = (await conn.execute(text("SELECT to_regclass('public.fase04_atomicity_probe')"))).scalar_one()
                self.assertIsNone(probe_exists, "DDL da migration quebrada nao pode sobreviver ao rollback")

                # banco permanece utilizavel/consistente apos a falha
                sanity = (await conn.execute(text("SELECT 1"))).scalar_one()
                self.assertEqual(sanity, 1)

        asyncio.run(check_after())


@unittest.skipUnless(integration_enabled(), _SKIP_REASON)
class BackwardCompatibilityDetectionTests(unittest.TestCase):
    """Secao 24 da Fase 04: 'schema antigo abaixo do minimo -> API deve detectar
    e nao operar silenciosamente'. As duas primeiras linhas da matriz da Secao 24
    (schema novo + API atual/anterior) ja sao cobertas por
    UpgradeFromEarlierRevisionTests e pelos testes de compatibilidade da Fase 02;
    nao foi viavel executar um binario de API anterior real neste ambiente de
    teste (limitacao documentada, conforme permitido pela Secao 24 do prompt)."""

    @classmethod
    def setUpClass(cls):
        cls.previous_env = _swap_env_for_test_database()
        command.downgrade(alembic_config(), "base")
        command.upgrade(alembic_config(), "head")

    @classmethod
    def tearDownClass(cls):
        command.upgrade(alembic_config(), "head")
        asyncio.run(dispose_engine())
        _restore_env(cls.previous_env)

    def test_schema_below_expected_revision_is_detected_not_silently_accepted(self):
        command.downgrade(alembic_config(), "20260803_0013")
        try:
            client = TestClient(create_app())

            ready_response = client.get("/api/v1/system/ready")
            self.assertEqual(ready_response.status_code, 503)

            version_response = client.get("/api/v1/system/version")
            self.assertEqual(version_response.status_code, 200)
            self.assertEqual(version_response.json()["database_status"], "incompatible")

            compatibility_response = client.get("/api/v1/system/compatibility")
            self.assertEqual(compatibility_response.status_code, 503)
        finally:
            command.upgrade(alembic_config(), "head")


if __name__ == "__main__":
    unittest.main()
