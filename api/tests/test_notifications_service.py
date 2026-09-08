from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from api.app.core.config import get_settings
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker
from api.app.modules.auth.models import Permission, Role, User
from api.app.modules.auth.permissions import ADMIN_PERMISSION_CODES
from api.app.modules.auth.security import hash_password
from api.app.modules.auth.tokens import utcnow
from api.app.modules.notifications import service as notifications_service
from api.app.modules.notifications.models import Notification, NotificationDelivery
from api.app.modules.notifications.schemas import (
    NotificationPreferenceItem,
    NotificationPreferencesPayload,
    NotificationSettingsPayload,
)


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
class NotificationsServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = {
            "DATABASE_URL": os.environ.get("DATABASE_URL"),
            "APP_ENV": os.environ.get("APP_ENV"),
            "SECRET_KEY": os.environ.get("SECRET_KEY"),
            "NOTIFICATIONS_DIGEST_HOUR": os.environ.get("NOTIFICATIONS_DIGEST_HOUR"),
        }
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "notifications-secret-key-more-than-32-chars"
        os.environ["NOTIFICATIONS_DIGEST_HOUR"] = "0"
        get_settings.cache_clear()
        get_engine.cache_clear()
        command.downgrade(_alembic_config(), "base")
        command.upgrade(_alembic_config(), "head")

    @classmethod
    def tearDownClass(cls):
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
            await conn.execute(
                text(
                    "TRUNCATE TABLE notification_deliveries, notification_preferences, "
                    "notification_user_settings, notifications, "
                    "proposal_events, chat_messages, chat_conversations, proposals, sync_runs, "
                    "role_permissions, user_roles, users, roles RESTART IDENTITY CASCADE"
                )
            )

    async def _make_user(self, session, username: str, *, email: str | None = None) -> User:
        role = (await session.execute(select(Role).where(Role.code == "admin"))).scalars().first()
        if role is None:
            perms = (await session.execute(select(Permission).where(Permission.code.in_(ADMIN_PERMISSION_CODES)))).scalars().all()
            role = Role(code="admin", name="Administrador", active=True, system_role=True)
            role.permissions.extend(perms)
            session.add(role)
            await session.flush()
        user = User(username=username, display_name=username.title(), email=email, password_hash=hash_password("Senha forte notif 123"), active=True, password_changed_at=utcnow())
        session.add(user)
        await session.flush()
        return user

    def test_emit_creates_one_row_per_target_and_is_idempotent(self):
        async def _run():
            factory = get_sessionmaker()
            async with factory() as session:
                actor = await self._make_user(session, "notif_actor")
                a = await self._make_user(session, "notif_a")
                b = await self._make_user(session, "notif_b")
                await session.commit()

                first = await notifications_service.emit(
                    session,
                    user_ids=[a.id, b.id, actor.id],
                    category="PROPOSTA_STATUS",
                    title="Proposta 123 mudou de status",
                    body="Agora esta em PRODUCAO",
                    deep_link="proposal/123",
                    actor_user_id=actor.id,
                    dedup_key="proposal:123:PRODUCAO",
                )
                await session.commit()
                # o proprio ator nunca recebe; A e B sim
                self.assertCountEqual(first, [a.id, b.id])

                again = await notifications_service.emit(
                    session,
                    user_ids=[a.id, b.id],
                    category="PROPOSTA_STATUS",
                    title="Proposta 123 mudou de status",
                    dedup_key="proposal:123:PRODUCAO",
                )
                await session.commit()
                self.assertEqual(again, [])

                rows = (await session.execute(select(Notification))).scalars().all()
                self.assertEqual(len(rows), 2)
                deliveries = (await session.execute(select(NotificationDelivery))).scalars().all()
                # in_app + tray + email por notificacao
                self.assertEqual(len(deliveries), 6)

                summary = await notifications_service.unread_summary(session, a)
                self.assertEqual(summary.total_unread, 1)
                self.assertEqual(summary.by_category.get("PROPOSTA_STATUS"), 1)

                listing = await notifications_service.list_notifications(session, b)
                self.assertEqual(listing.total, 1)
                self.assertEqual(listing.items[0].actor_name, "Notif_Actor")

                changed = await notifications_service.mark_all_read(session, a)
                self.assertEqual(changed, 1)
                self.assertEqual((await notifications_service.unread_summary(session, a)).total_unread, 0)

        asyncio.run(_run())

    def test_email_delivery_status_follows_severity(self):
        async def _run():
            factory = get_sessionmaker()
            async with factory() as session:
                user = await self._make_user(session, "notif_sev")
                await session.commit()
                await notifications_service.emit(
                    session, user_ids=[user.id], category="PROPOSTA_STATUS", severity="info",
                    title="mensagem", dedup_key="k-info",
                )
                await notifications_service.emit(
                    session, user_ids=[user.id], category="NOMUS_IMPORTACAO", severity="critica",
                    title="falha", dedup_key="k-crit",
                )
                await session.commit()
                statuses = {
                    n.dedup_key: d.status
                    for n in (await session.execute(select(Notification))).scalars().all()
                    for d in n.deliveries
                    if d.channel == "email"
                }
                self.assertEqual(statuses["k-info"], "agrupado_digest")
                self.assertEqual(statuses["k-crit"], "pendente")

        asyncio.run(_run())


    def test_preferences_and_quiet_hours_shape_delivery(self):
        async def _run():
            factory = get_sessionmaker()
            async with factory() as session:
                user = await self._make_user(session, "notif_pref")
                await session.commit()

                # desliga tray e liga email (min normal) para PROPOSTA_STATUS
                await notifications_service.put_preferences(
                    session,
                    user,
                    NotificationPreferencesPayload(items=[
                        NotificationPreferenceItem(
                            category="PROPOSTA_STATUS",
                            channel_in_app=True,
                            channel_tray=False,
                            channel_email=True,
                            min_severity_email="normal",
                        )
                    ]),
                )
                # silencio cobrindo o dia inteiro para o canal email
                await notifications_service.put_settings(
                    session, user,
                    NotificationSettingsPayload(quiet_start="00:00", quiet_end="23:59", quiet_channels=["email"]),
                )

                await notifications_service.emit(
                    session, user_ids=[user.id], category="PROPOSTA_STATUS", severity="normal",
                    title="mudou", dedup_key="p:1",
                )
                await notifications_service.emit(
                    session, user_ids=[user.id], category="PROPOSTA_STATUS", severity="critica",
                    title="cancelada", dedup_key="p:2",
                )
                await session.commit()

                by_key = {
                    n.dedup_key: {d.channel: d.status for d in n.deliveries}
                    for n in (await session.execute(select(Notification))).scalars().all()
                }
                # tray desligado por preferencia nas duas
                self.assertEqual(by_key["p:1"]["tray"], "suprimido_preferencia")
                # email: normal cai no digest por causa do silencio; critica fura
                self.assertEqual(by_key["p:1"]["email"], "agrupado_digest")
                self.assertEqual(by_key["p:2"]["email"], "pendente")

                prefs = await notifications_service.get_preferences(session, user)
                custom = next(p for p in prefs if p.category == "PROPOSTA_STATUS")
                self.assertTrue(custom.is_custom)
                self.assertFalse(custom.channel_tray)

        asyncio.run(_run())


    def test_proposal_event_notifies_creator_and_chat_participants_not_actor(self):
        from datetime import date

        from api.app.modules.chat.models import ChatConversation, ChatMessage
        from api.app.modules.proposals import service as proposals_service
        from api.app.modules.proposals.models import Proposal

        async def _run():
            factory = get_sessionmaker()
            async with factory() as session:
                creator = await self._make_user(session, "pe_creator")
                participant = await self._make_user(session, "pe_participant")
                actor = await self._make_user(session, "pe_actor")
                await session.flush()
                proposal = Proposal(
                    proposal_number="PE-1", customer_name="Cliente PE", proposal_date=date(2026, 9, 1),
                    deadline_date=date(2026, 9, 20), source="MANUAL", version=1,
                    source_hash="pe-1", legacy_id=-777, created_by=creator.id,
                )
                session.add(proposal)
                await session.flush()
                conversation = ChatConversation(kind="PROPOSTA", proposal_id=proposal.id, status="ATIVA")
                session.add(conversation)
                await session.flush()
                session.add(ChatMessage(conversation_id=conversation.id, author_user_id=participant.id, message_type="MENSAGEM", body="acompanhando"))
                await session.commit()

                await proposals_service._emit_proposal_event_notification(
                    session, proposal, "PRODUCTION_COMPLETED", actor,
                    request_id="req-1", from_status="EM_PRODUCAO", to_status="CONCLUIDO", metadata={},
                )
                await session.commit()

                rows = (await session.execute(select(Notification))).scalars().all()
                got = {n.user_id for n in rows}
                self.assertEqual(got, {creator.id, participant.id})
                self.assertEqual(rows[0].category, "PRODUCAO_LOTE")
                self.assertEqual(rows[0].deep_link, f"proposal/{proposal.id}")

        asyncio.run(_run())

    def test_delivery_worker_sends_immediate_then_digests_the_rest(self):
        from api.app.modules.notifications import delivery_worker

        async def _seed():
            factory = get_sessionmaker()
            async with factory() as session:
                user = await self._make_user(session, "notif_mail", email="dest@example.com")
                await session.commit()
                # critica -> email 'pendente'; info -> email 'agrupado_digest'
                await notifications_service.emit(
                    session, user_ids=[user.id], category="NOMUS_IMPORTACAO", severity="critica",
                    title="Importacao falhou", dedup_key="d:1",
                )
                await notifications_service.emit(
                    session, user_ids=[user.id], category="PROPOSTA_STATUS", severity="info",
                    title="mudou de status", dedup_key="d:2",
                )
                await session.commit()

        asyncio.run(_seed())

        with patch.object(delivery_worker, "send_email", new_callable=AsyncMock) as sender:
            immediate, digest = asyncio.run(delivery_worker.process_once())

        self.assertEqual(immediate, 1)
        self.assertEqual(digest, 1)
        subjects = [c.kwargs["subject"] for c in sender.await_args_list]
        self.assertTrue(any("URGENTE" in s for s in subjects))
        self.assertTrue(any("Resumo diario" in s for s in subjects))

        async def _check():
            factory = get_sessionmaker()
            async with factory() as session:
                statuses = {
                    n.dedup_key: {d.channel: d.status for d in n.deliveries}
                    for n in (await session.execute(select(Notification))).scalars().all()
                }
                return statuses

        statuses = asyncio.run(_check())
        self.assertEqual(statuses["d:1"]["email"], "enviado")
        self.assertEqual(statuses["d:2"]["email"], "enviado")


if __name__ == "__main__":
    unittest.main()
