from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from api.app.audit import service as audit_service
from api.app.audit.models import ActorType, AuditEventType, Component, EventResult, EventSeverity
from api.app.audit.spool import AuditSpool
from api.app.core.config import get_settings
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker

ACTOR = "release.admin"


def _spool(tmp: Path) -> AuditSpool:
    return AuditSpool(pending_dir=tmp / "pending", processed_dir=tmp / "processed", failed_dir=tmp / "failed")


class RecordEventUnitTests(unittest.TestCase):
    """Sem banco: cobre so o comportamento sincrono de `record_event`
    (Secao 18 -- sempre grava no spool, nunca toca o Postgres diretamente,
    nunca levanta excecao para quem chama)."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.spool = _spool(Path(self._tmp.name))

    def test_record_event_writes_a_pending_spool_entry_with_unique_event_id(self):
        first = audit_service.record_event(
            event_type=AuditEventType.RELEASE_AUTHORIZED, component=Component.UPDATE_SERVER,
            result=EventResult.SUCCEEDED, message="release autorizada", actor_type=ActorType.ADMIN_API,
            actor_id=ACTOR, spool=self.spool,
        )
        second = audit_service.record_event(
            event_type=AuditEventType.RELEASE_AUTHORIZED, component=Component.UPDATE_SERVER,
            result=EventResult.SUCCEEDED, message="release autorizada de novo", actor_type=ActorType.ADMIN_API,
            actor_id=ACTOR, spool=self.spool,
        )
        self.assertNotEqual(first.event_id, second.event_id)
        pending_ids = {event.event_id for event in self.spool.list_pending()}
        self.assertEqual(pending_ids, {first.event_id, second.event_id})

    def test_record_event_sanitizes_metadata_before_persisting(self):
        event = audit_service.record_event(
            event_type=AuditEventType.RELEASE_AUTHORIZED, component=Component.UPDATE_SERVER,
            result=EventResult.SUCCEEDED, message="x", metadata={"password": "super-secret", "sha256": "abc"},
            spool=self.spool,
        )
        self.assertEqual(event.metadata["password"], "***REDACTED***")
        self.assertEqual(event.metadata["sha256"], "abc")
        persisted = self.spool.list_pending()[0]
        self.assertEqual(persisted.metadata["password"], "***REDACTED***")

    def test_record_event_threads_correlation_id_through(self):
        event = audit_service.record_event(
            event_type=AuditEventType.DEPLOYMENT_STARTED, component=Component.DEPLOYMENT,
            result=EventResult.STARTED, message="x", correlation_id="upd-20260812-fixed01", spool=self.spool,
        )
        self.assertEqual(event.correlation_id, "upd-20260812-fixed01")

    def test_record_event_never_raises_even_if_spool_write_fails(self):
        class ExplodingSpool(AuditSpool):
            def write_pending(self, event):
                raise OSError("disco cheio")

        exploding = ExplodingSpool(pending_dir=Path("x"), processed_dir=Path("y"), failed_dir=Path("z"))
        try:
            event = audit_service.record_event(
                event_type=AuditEventType.DEPLOYMENT_FAILED, component=Component.DEPLOYMENT,
                result=EventResult.FAILED, message="falhou", spool=exploding,
            )
        except Exception as exc:  # pragma: no cover - only triggers on regression
            self.fail(f"record_event nao deveria propagar excecao: {exc}")
        self.assertEqual(event.result, EventResult.FAILED)

    def test_drain_returns_zero_immediately_when_no_sessionmaker_available(self):
        audit_service.record_event(
            event_type=AuditEventType.DEPLOYMENT_STARTED, component=Component.DEPLOYMENT,
            result=EventResult.STARTED, message="x", spool=self.spool,
        )
        drained = asyncio.run(audit_service.drain_spool_to_database(spool=self.spool, sessionmaker=None))
        self.assertEqual(drained, 0)
        # nada foi perdido -- continua pendente para a proxima tentativa.
        self.assertEqual(self.spool.pending_count(), 1)


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
class DrainAndQueryIntegrationTests(unittest.TestCase):
    """Fase 16, Secao 29: drenagem idempotente, filtros, timeline ordenada,
    paginacao, snapshot por instalacao -- ponta a ponta contra Postgres real."""

    @classmethod
    def setUpClass(cls):
        cls.previous = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "APP_ENV": os.environ.get("APP_ENV"), "SECRET_KEY": os.environ.get("SECRET_KEY")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "audit-service-integration-secret-key-32ch"
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
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.spool = _spool(Path(self._tmp.name))
        asyncio.run(self._truncate())

    async def _truncate(self):
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE update_audit_events RESTART IDENTITY CASCADE"))
            await conn.execute(text("TRUNCATE TABLE client_installations, pilot_client_reports RESTART IDENTITY CASCADE"))

    def _record(self, **overrides):
        defaults = dict(
            event_type=AuditEventType.DEPLOYMENT_STARTED, component=Component.DEPLOYMENT,
            result=EventResult.STARTED, message="x", spool=self.spool,
        )
        defaults.update(overrides)
        return audit_service.record_event(**defaults)

    async def _drain(self) -> int:
        return await audit_service.drain_spool_to_database(spool=self.spool, sessionmaker=get_sessionmaker())

    def test_drain_moves_pending_events_into_the_database(self):
        self._record()
        drained = asyncio.run(self._drain())
        self.assertEqual(drained, 1)
        self.assertEqual(self.spool.pending_count(), 0)
        self.assertEqual(len(self.spool.list_processed()), 1)

    def test_draining_the_same_event_twice_does_not_duplicate_rows(self):
        event = self._record(event_type=AuditEventType.RELEASE_AUTHORIZED, correlation_id="upd-20260812-dup0001")
        asyncio.run(self._drain())
        # Reinjeta manualmente o mesmo evento (ja processado) de volta em
        # pending para simular uma segunda tentativa de drenagem do mesmo id.
        self.spool.write_pending(event)
        second_drain = asyncio.run(self._drain())
        self.assertEqual(second_drain, 1)  # ON CONFLICT DO NOTHING ainda conta como "processado" localmente

        async def _count():
            async with get_sessionmaker()() as session:
                result = await session.execute(text("SELECT COUNT(*) FROM update_audit_events WHERE event_id = :eid"), {"eid": event.event_id})
                return result.scalar_one()

        self.assertEqual(asyncio.run(_count()), 1)

    def test_failed_drain_for_one_event_does_not_block_others_and_stays_pending(self):
        from api.app.audit.models import UpdateAuditEvent as _UpdateAuditEvent

        good = self._record(event_type=AuditEventType.RELEASE_AUTHORIZED)
        broken = _UpdateAuditEvent(
            event_id="x" * 40,  # excede o limite da coluna (String(36)) -- forca falha no INSERT
            event_type=AuditEventType.RELEASE_AUTHORIZED, severity=EventSeverity.INFO,
            actor_type=ActorType.SYSTEM, component=Component.UPDATE_SERVER,
            result=EventResult.SUCCEEDED, message="evento com id invalido",
        )
        self.spool.write_pending(broken)
        drained = asyncio.run(self._drain())
        self.assertEqual(drained, 1)
        pending_ids = {event.event_id for event in self.spool.list_pending()}
        self.assertIn(broken.event_id, pending_ids)
        self.assertNotIn(good.event_id, pending_ids)

    def test_list_events_filters_by_version_and_paginates(self):
        for index in range(3):
            self._record(version="3.3.0", message=f"evento {index}")
        self._record(version="3.2.0", message="outra versao")
        asyncio.run(self._drain())

        async def _query():
            async with get_sessionmaker()() as session:
                page = await audit_service.list_events(session, version="3.3.0", limit=2, offset=0)
                return page

        page = asyncio.run(_query())
        self.assertEqual(page.total, 3)
        self.assertEqual(len(page.items), 2)

    def test_list_events_filters_by_installation_id(self):
        self._record(installation_id="pc-1")
        self._record(installation_id="pc-2")
        asyncio.run(self._drain())

        async def _query():
            async with get_sessionmaker()() as session:
                return await audit_service.list_events(session, installation_id="pc-1")

        page = asyncio.run(_query())
        self.assertEqual(page.total, 1)
        self.assertEqual(page.items[0].installation_id, "pc-1")

    def test_build_timeline_returns_events_for_correlation_id_in_chronological_order(self):
        corr = "upd-20260812-timeline1"
        self._record(event_type=AuditEventType.DEPLOYMENT_STARTED, correlation_id=corr)
        self._record(event_type=AuditEventType.BACKUP_STARTED, correlation_id=corr)
        self._record(event_type=AuditEventType.DEPLOYMENT_SUCCEEDED, correlation_id=corr)
        self._record(event_type=AuditEventType.DEPLOYMENT_STARTED, correlation_id="upd-other")
        asyncio.run(self._drain())

        async def _query():
            async with get_sessionmaker()() as session:
                return await audit_service.build_timeline(session, corr)

        timeline = asyncio.run(_query())
        self.assertEqual(len(timeline), 3)
        occurred = [row.occurred_at for row in timeline]
        self.assertEqual(occurred, sorted(occurred))

    def test_get_installation_status_combines_installation_row_with_latest_events(self):
        from api.app.channels.db_models import ClientInstallation

        async def _seed():
            async with get_sessionmaker()() as session:
                session.add(ClientInstallation(installation_id="pc-status-1", machine_name="PC-STATUS-1", channel="PRODUCTION", current_desktop_version="3.2.0"))
                await session.commit()

        asyncio.run(_seed())
        self._record(
            event_type=AuditEventType.UPDATE_INSTALL_SUCCEEDED, installation_id="pc-status-1", version="3.3.0",
            result=EventResult.SUCCEEDED,
        )
        self._record(
            event_type=AuditEventType.DESKTOP_COMPATIBILITY_CHECKED, installation_id="pc-status-1",
            metadata={"desktop_state": "COMPATIBLE"},
        )
        asyncio.run(self._drain())

        async def _query():
            async with get_sessionmaker()() as session:
                return await audit_service.get_installation_status(session, "pc-status-1")

        status = asyncio.run(_query())
        self.assertIsNotNone(status)
        self.assertEqual(status.last_update_version, "3.3.0")
        self.assertEqual(status.last_update_result, "SUCCEEDED")
        self.assertEqual(status.compatibility_state, "COMPATIBLE")

    def test_get_installation_status_returns_none_for_unknown_installation(self):
        async def _query():
            async with get_sessionmaker()() as session:
                return await audit_service.get_installation_status(session, "does-not-exist")

        self.assertIsNone(asyncio.run(_query()))

    def test_querying_audit_never_mutates_operational_tables(self):
        from api.app.channels.db_models import ClientInstallation

        async def _seed_and_count():
            async with get_sessionmaker()() as session:
                session.add(ClientInstallation(installation_id="pc-readonly", machine_name="PC-RO", channel="PRODUCTION", current_desktop_version="3.2.0"))
                await session.commit()
                before = (await session.execute(text("SELECT COUNT(*) FROM client_installations"))).scalar_one()
                await audit_service.list_events(session, limit=5)
                await audit_service.get_installation_status(session, "pc-readonly")
                after = (await session.execute(text("SELECT COUNT(*) FROM client_installations"))).scalar_one()
                return before, after

        before, after = asyncio.run(_seed_and_count())
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
