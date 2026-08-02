from __future__ import annotations

import asyncio
import os
import unittest
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from sqlalchemy import event, select, text

from api.app.core.config import get_settings
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker
from api.app.modules.auth.models import Permission, Role, User
from api.app.modules.auth.permissions import ADMIN_PERMISSION_CODES
from api.app.modules.auth.security import hash_password
from api.app.modules.auth.tokens import utcnow
from api.app.modules.chat import service as chat_service
from api.app.modules.chat.models import ChatConversation, ChatMessage, ChatMessageRead
from api.app.modules.proposals.models import Proposal, ProposalEvent


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


class QueryCounter:
    def __init__(self):
        self.count = 0

    def __call__(self, conn, cursor, statement, parameters, context, executemany):
        self.count += 1


@unittest.skipUnless(_integration_enabled(), "PostgreSQL integration tests require APP_ENV=test and POSTGRES_TEST_DATABASE_URL.")
class ChatPerformanceTests(unittest.TestCase):
    """Comprova a eliminacao das consultas N+1 do modulo de Chat: o numero
    de consultas SQL nao pode crescer proporcionalmente ao numero de
    propostas/conversas, e o resultado funcional precisa continuar
    identico ao comportamento original (mesmos valores, mesma contagem)."""

    @classmethod
    def setUpClass(cls):
        cls.previous = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "APP_ENV": os.environ.get("APP_ENV"), "SECRET_KEY": os.environ.get("SECRET_KEY")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "chat-performance-secret-key-more-than-32-chars"
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
            await conn.execute(
                text(
                    "TRUNCATE TABLE chat_notifications, chat_message_reads, chat_messages, chat_conversations, "
                    "fiscal_events, fiscal_invoice_items, fiscal_invoices, fiscal_items, fiscal_records, "
                    "expedition_events, expedition_items, galvanization_load_events, galvanization_load_items, "
                    "galvanization_loads, proposal_events, proposal_items, proposals, sync_runs, "
                    "role_permissions, user_roles, users, roles RESTART IDENTITY CASCADE"
                )
            )

    async def _seed(self, *, proposal_count: int, messages_per_proposal: int = 4, events_per_proposal: int = 2, mark_read: bool = True) -> tuple[User, list[int]]:
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            admin_permissions = (await session.execute(select(Permission).where(Permission.code.in_(ADMIN_PERMISSION_CODES)))).scalars().all()
            admin_role = Role(code="admin", name="Administrador", active=True, system_role=True)
            admin_role.permissions.extend(admin_permissions)
            admin = User(
                username=f"admin{proposal_count}",
                display_name="Administradora",
                password_hash=hash_password("Senha forte perf 123"),
                active=True,
                is_superuser=True,
                password_changed_at=utcnow(),
            )
            admin.roles.append(admin_role)
            session.add(admin)
            await session.flush()
            admin_id = admin.id

            proposal_ids = []
            for i in range(proposal_count):
                proposal = Proposal(
                    proposal_number=f"PERF-{proposal_count}-{i:05d}",
                    customer_name=f"Cliente {i}",
                    project_name=f"Obra {i}",
                    proposal_date=date(2026, 8, 1),
                    deadline_date=date(2026, 8, 20),
                    source="MANUAL",
                    current_area="CONTROLE GERAL",
                    current_status="AGUARDANDO_LIBERACAO",
                    version=1,
                    source_hash=f"perf-{proposal_count}-{i}",
                    legacy_id=-(proposal_count * 100000 + i + 1),
                )
                session.add(proposal)
                await session.flush()
                proposal_ids.append(proposal.id)

                conversation = ChatConversation(kind="PROPOSTA", proposal_id=proposal.id, status="ATIVA")
                session.add(conversation)
                await session.flush()

                for m in range(messages_per_proposal):
                    session.add(ChatMessage(conversation_id=conversation.id, author_user_id=admin_id, message_type="MENSAGEM", body=f"Mensagem {m}"))
                await session.flush()

                if mark_read:
                    last_message_id = (
                        await session.execute(
                            select(ChatMessage.id).where(ChatMessage.conversation_id == conversation.id).order_by(ChatMessage.id.desc()).limit(1)
                        )
                    ).scalar_one()
                    session.add(ChatMessageRead(conversation_id=conversation.id, user_id=admin_id, last_read_message_id=max(last_message_id - 1, 0)))

            await session.commit()

        # transacao separada: garante created_at dos eventos > updated_at das leituras
        async with session_factory() as session:
            for i, proposal_id in enumerate(proposal_ids):
                for e in range(events_per_proposal):
                    session.add(
                        ProposalEvent(
                            proposal_id=proposal_id,
                            event_type="STATUS_CHANGED",
                            from_status="X",
                            to_status="Y",
                            actor_user_id=admin_id,
                            metadata_={"observation": f"Observacao {e} da proposta {i}"},
                        )
                    )
            await session.commit()

        async with session_factory() as session:
            admin_row = (await session.execute(select(User).where(User.id == admin_id))).scalars().first()
        return admin_row, proposal_ids

    async def _count_queries(self, coro_factory):
        engine = get_engine()
        counter = QueryCounter()
        event.listen(engine.sync_engine, "before_cursor_execute", counter)
        try:
            result = await coro_factory()
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", counter)
        return result, counter.count

    def test_list_conversations_query_count_does_not_scale_with_proposal_count(self):
        async def _run():
            session_factory = get_sessionmaker()

            await self._truncate()
            admin_small, _ = await self._seed(proposal_count=5)
            async with session_factory() as session:
                admin = (await session.execute(select(User).where(User.id == admin_small.id))).scalars().first()
                _, small_count = await self._count_queries(lambda: chat_service.list_conversations(session, admin, limit=50, offset=0))

            await self._truncate()
            admin_big, _ = await self._seed(proposal_count=60)
            async with session_factory() as session:
                admin = (await session.execute(select(User).where(User.id == admin_big.id))).scalars().first()
                _, big_count = await self._count_queries(lambda: chat_service.list_conversations(session, admin, limit=50, offset=0))

            return small_count, big_count

        small_count, big_count = asyncio.run(_run())
        self.assertLess(big_count, 25, "list_conversations nao pode crescer proporcionalmente ao numero de propostas")
        self.assertEqual(small_count, big_count, "o numero de consultas deve ser o mesmo independente da quantidade de conversas (mesma pagina)")

    def test_unread_summary_query_count_bounded_and_correct(self):
        async def _run():
            admin, proposal_ids = await self._seed(proposal_count=40, events_per_proposal=2)
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                admin_row = (await session.execute(select(User).where(User.id == admin.id))).scalars().first()
                summary, queries = await self._count_queries(lambda: chat_service.unread_summary(session, admin_row))
            return summary, queries, len(proposal_ids)

        summary, queries, proposal_count = asyncio.run(_run())
        self.assertLess(queries, 25, f"unread_summary fez {queries} consultas para {proposal_count} propostas — deveria ser um numero fixo, nao proporcional")
        # 2 eventos com observacao por proposta, todas as propostas com leitura registrada
        self.assertEqual(summary.new_observations, proposal_count * 2)

    def test_list_notifications_query_count_bounded_and_matches_unread_summary(self):
        async def _run():
            admin, proposal_ids = await self._seed(proposal_count=40, events_per_proposal=2)
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                admin_row = (await session.execute(select(User).where(User.id == admin.id))).scalars().first()
                notifications, queries = await self._count_queries(lambda: chat_service.list_notifications(session, admin_row, limit=200, offset=0))
            return notifications, queries, len(proposal_ids)

        notifications, queries, proposal_count = asyncio.run(_run())
        self.assertLess(queries, 25, f"list_notifications fez {queries} consultas para {proposal_count} propostas")
        self.assertEqual(notifications.total, proposal_count * 2)

    def test_conversations_without_a_read_cursor_produce_no_observation_entries(self):
        async def _run():
            admin, proposal_ids = await self._seed(proposal_count=10, events_per_proposal=2, mark_read=False)
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                admin_row = (await session.execute(select(User).where(User.id == admin.id))).scalars().first()
                summary = await chat_service.unread_summary(session, admin_row)
            return summary

        summary = asyncio.run(_run())
        # ninguem nunca abriu nenhuma dessas conversas -> sem "ultima vez visto" -> sem novidade
        self.assertEqual(summary.new_observations, 0)

    def test_results_are_stable_across_repeated_calls(self):
        async def _run():
            admin, _ = await self._seed(proposal_count=15, events_per_proposal=2)
            session_factory = get_sessionmaker()
            results = []
            for _ in range(3):
                async with session_factory() as session:
                    admin_row = (await session.execute(select(User).where(User.id == admin.id))).scalars().first()
                    summary = await chat_service.unread_summary(session, admin_row)
                    results.append((summary.total_unread, summary.new_observations, summary.pending_questions))
            return results

        results = asyncio.run(_run())
        self.assertEqual(len(set(results)), 1, f"chamadas repetidas devem devolver exatamente o mesmo resultado, obtive {results}")

    def test_seen_counts_match_expected_per_message_after_optimization(self):
        async def _run():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                admin = User(username="seenadmin", display_name="Admin", password_hash=hash_password("Senha forte perf 123"), active=True, is_superuser=True, password_changed_at=utcnow())
                reader = User(username="seenreader", display_name="Leitor", password_hash=hash_password("Senha forte perf 123"), active=True, is_superuser=False, password_changed_at=utcnow())
                session.add_all([admin, reader])
                await session.flush()

                proposal = Proposal(
                    proposal_number="PERF-SEEN-0001",
                    customer_name="Cliente Seen",
                    proposal_date=date(2026, 8, 1),
                    deadline_date=date(2026, 8, 20),
                    source="MANUAL",
                    version=1,
                    source_hash="perf-seen-1",
                    legacy_id=-999001,
                )
                session.add(proposal)
                await session.flush()
                conversation = ChatConversation(kind="PROPOSTA", proposal_id=proposal.id, status="ATIVA")
                session.add(conversation)
                await session.flush()

                messages = [ChatMessage(conversation_id=conversation.id, author_user_id=admin.id, message_type="MENSAGEM", body=f"m{i}") for i in range(4)]
                session.add_all(messages)
                await session.flush()
                message_ids = [m.id for m in messages]

                # reader leu ate a 3a mensagem (nao leu a 4a ainda)
                session.add(ChatMessageRead(conversation_id=conversation.id, user_id=reader.id, last_read_message_id=message_ids[2]))
                await session.commit()

                seen = await chat_service._seen_counts(session, messages)
            return seen, message_ids

        seen, message_ids = asyncio.run(_run())
        # reader (que nao e o autor) leu ate a mensagem 3: mensagens 1,2,3 tem 1 leitor; a 4a tem 0
        self.assertEqual(seen[message_ids[0]], 1)
        self.assertEqual(seen[message_ids[1]], 1)
        self.assertEqual(seen[message_ids[2]], 1)
        self.assertEqual(seen[message_ids[3]], 0)

    def test_full_functional_pipeline_at_hundreds_of_proposals_and_thousands_of_messages(self):
        async def _run():
            admin, proposal_ids = await self._seed(proposal_count=200, messages_per_proposal=6, events_per_proposal=2)
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                admin_row = (await session.execute(select(User).where(User.id == admin.id))).scalars().first()
                conversations, conv_queries = await self._count_queries(lambda: chat_service.list_conversations(session, admin_row, limit=50, offset=0))
            async with session_factory() as session:
                admin_row = (await session.execute(select(User).where(User.id == admin.id))).scalars().first()
                summary, summary_queries = await self._count_queries(lambda: chat_service.unread_summary(session, admin_row))
            async with session_factory() as session:
                admin_row = (await session.execute(select(User).where(User.id == admin.id))).scalars().first()
                timeline, timeline_queries = await self._count_queries(lambda: chat_service.get_proposal_timeline(session, proposal_ids[0], admin_row))
            return conversations, conv_queries, summary, summary_queries, timeline, timeline_queries, len(proposal_ids)

        conversations, conv_queries, summary, summary_queries, timeline, timeline_queries, proposal_count = asyncio.run(_run())
        # 200 propostas x 6 mensagens = 1200 mensagens no total, +1 pelo Chat Geral sempre presente
        self.assertEqual(conversations.total, proposal_count + 1)
        self.assertEqual(summary.new_observations, proposal_count * 2)
        self.assertGreater(len(timeline.items), 0)
        for label, queries in (("list_conversations", conv_queries), ("unread_summary", summary_queries), ("get_proposal_timeline", timeline_queries)):
            self.assertLess(queries, 40, f"{label} fez {queries} consultas com {proposal_count} propostas — nao pode crescer com o volume")


if __name__ == "__main__":
    unittest.main()
