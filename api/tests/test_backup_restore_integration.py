from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

import asyncpg

from api.app.backup.connection import parse_database_url
from api.app.backup.models import BackupStatus, ValidationStatus
from api.app.backup.service import PreDeploymentBackupService
from api.app.core.config import EXPECTED_DATABASE_REVISION, Settings, get_settings
from api.app.database.health import current_database_revision
from api.app.database.session import dispose_engine, get_engine
from api.tests._migration_test_support import TEST_DATABASE_URL, integration_enabled

PG_DUMP_PATH = os.environ.get("PG_DUMP_PATH", "pg_dump")
PG_RESTORE_PATH = os.environ.get("PG_RESTORE_PATH", "pg_restore")


def _tools_available() -> bool:
    return shutil.which(PG_DUMP_PATH) is not None and shutil.which(PG_RESTORE_PATH) is not None


_SKIP_REASON = (
    "Teste de restauracao real (Secao 27) exige APP_ENV=test + POSTGRES_TEST_DATABASE_URL "
    "(mesmo guard de seguranca das Fases 04) E pg_dump/pg_restore alcancaveis via "
    "PG_DUMP_PATH/PG_RESTORE_PATH (ou 'pg_dump'/'pg_restore' no PATH). Nenhum dos dois esta "
    "disponivel no host de desenvolvimento por padrao (sem cliente PostgreSQL local) -- "
    "ver docs/architecture/BACKUP_PRE_DEPLOYMENT.md, secao 'Como rodar o teste de restore', "
    "para o procedimento reproduzivel."
)


def _admin_dsn() -> str:
    normalized = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
    return normalized


async def _create_database(name: str) -> None:
    conn = await asyncpg.connect(_admin_dsn())
    try:
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


async def _drop_database(name: str) -> None:
    conn = await asyncpg.connect(_admin_dsn())
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        await conn.close()


async def _query_scalar(dsn: str, query: str):
    conn = await asyncpg.connect(dsn)
    try:
        return await conn.fetchval(query)
    finally:
        await conn.close()


@unittest.skipUnless(integration_enabled() and _tools_available(), _SKIP_REASON)
class BackupRestoreIntegrationTests(unittest.TestCase):
    """Secao 27 da Fase 05: gera um dump real, restaura em banco temporario
    isolado, valida revisao e dados essenciais, descarta o banco temporario.
    Nunca roda contra o banco de desenvolvimento/producao -- so contra
    POSTGRES_TEST_DATABASE_URL (mesmo guard das Fases 04) e um banco novo
    criado exclusivamente para este teste, removido ao final."""

    @classmethod
    def setUpClass(cls):
        cls.previous_env = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "APP_ENV": os.environ.get("APP_ENV")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        get_settings.cache_clear()
        get_engine.cache_clear()

    @classmethod
    def tearDownClass(cls):
        asyncio.run(dispose_engine())
        for key, value in cls.previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()
        get_engine.cache_clear()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.backup_dir = Path(self._tmp.name)
        self.restore_db_name = f"controle_producao_test_restore_{uuid.uuid4().hex[:12]}"

    def tearDown(self):
        asyncio.run(_drop_database(self.restore_db_name))
        self._tmp.cleanup()

    def test_backup_then_restore_into_isolated_database_preserves_revision_and_data(self):
        marker_value = uuid.uuid4().hex

        async def seed_and_collect():
            engine = get_engine()
            async with engine.begin() as conn:
                from sqlalchemy import text

                await conn.execute(
                    text("INSERT INTO system_metadata (key, value) VALUES (:key, cast(:value as jsonb))"),
                    {"key": f"fase05_backup_probe_{marker_value}", "value": f'{{"marker": "{marker_value}"}}'},
                )
            revision = await current_database_revision()
            permissions_count = await conn_scalar(engine, "SELECT count(*) FROM permissions")
            return revision, permissions_count

        async def conn_scalar(engine, query):
            from sqlalchemy import text as sa_text

            async with engine.connect() as conn:
                result = await conn.execute(sa_text(query))
                return result.scalar_one()

        revision_before, permissions_before = asyncio.run(seed_and_collect())
        self.assertEqual(revision_before, EXPECTED_DATABASE_REVISION)
        self.assertGreater(permissions_before, 0)

        settings = Settings(
            DATABASE_URL=TEST_DATABASE_URL,
            SECRET_KEY="x" * 32,
            BACKUP_TIMEOUT_SECONDS=120,
            BACKUP_MIN_FREE_SPACE_MB=0,
            PG_DUMP_PATH=PG_DUMP_PATH,
            PG_RESTORE_PATH=PG_RESTORE_PATH,
        )
        connection = parse_database_url(TEST_DATABASE_URL)
        service = PreDeploymentBackupService(settings=settings, connection=connection, backup_dir=self.backup_dir)

        result = service.run(database_revision=revision_before, environment="test")

        self.assertEqual(result.status, BackupStatus.SUCCESS, result.error_message)
        self.assertEqual(result.validation_status, ValidationStatus.VALID)
        self.assertTrue(result.is_usable_for_deployment)
        self.assertTrue(Path(result.file_path).exists())
        self.assertGreater(result.size_bytes, 0)

        manifest_path = self.backup_dir / f"{result.backup_id}.manifest.json"
        self.assertTrue(manifest_path.exists())
        manifest_text = manifest_path.read_text(encoding="utf-8")
        self.assertNotIn(connection.password, manifest_text)

        # -- restauracao em banco temporario isolado -----------------------
        asyncio.run(_create_database(self.restore_db_name))

        import subprocess

        restore_args = [
            PG_RESTORE_PATH,
            *connection.as_args(),
            "-d", self.restore_db_name,
            "--no-owner",
            "--no-privileges",
            result.file_path,
        ]
        restore_proc = subprocess.run(restore_args, capture_output=True, timeout=120, env=connection.env())
        self.assertEqual(restore_proc.returncode, 0, restore_proc.stderr.decode("utf-8", errors="replace"))

        restore_dsn = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1).rsplit("/", 1)[0] + f"/{self.restore_db_name}"
        restored_revision = asyncio.run(_query_scalar(restore_dsn, "SELECT version_num FROM alembic_version"))
        self.assertEqual(restored_revision, revision_before)

        restored_permissions = asyncio.run(_query_scalar(restore_dsn, "SELECT count(*) FROM permissions"))
        self.assertEqual(restored_permissions, permissions_before)

        restored_marker = asyncio.run(
            _query_scalar(restore_dsn, f"SELECT value->>'marker' FROM system_metadata WHERE key = 'fase05_backup_probe_{marker_value}'")
        )
        self.assertEqual(restored_marker, marker_value)

        # limpeza do dado de teste no banco de origem (nao deixa rastro no banco de teste)
        async def cleanup_marker():
            from sqlalchemy import text as sa_text

            engine = get_engine()
            async with engine.begin() as conn:
                await conn.execute(sa_text("DELETE FROM system_metadata WHERE key = :key"), {"key": f"fase05_backup_probe_{marker_value}"})

        asyncio.run(cleanup_marker())


if __name__ == "__main__":
    unittest.main()
