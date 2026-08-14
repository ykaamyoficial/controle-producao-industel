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
from api.app.modules.proposals.models import Proposal


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
class ChatSeenByTests(unittest.TestCase):
    """ETAPA 5: comprova que a contagem de 'visto por' e calculada inteiramente
    pelo banco (uma unica consulta agregada), com resultado correto em todos
    os casos de borda pedidos e desempenho que nao degrada com o volume."""

    @classmethod
    def setUpClass(cls):
        cls.previous = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "APP_ENV": os.environ.get("APP_ENV"), "SECRET_KEY": os.environ.get("SECRET_KEY")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "chat-seen-by-secret-key-more-than-32-chars"
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
        self._role_ready = False

    async def _truncate(self):
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "TRUNCATE TABLE chat_notifications, chat_message_reads, chat_messages, chat_conversations, "
                    "proposal_events, proposal_items, proposals, sync_runs, "
                    "role_permissions, user_roles, users, roles RESTART IDENTITY CASCADE"
                )
            )

    async def _ensure_admin_role(self, session) -> Role:
        role = (await session.execute(select(Role).where(Role.code == "admin"))).scalars().first()
        if role is not None:
            return role
        admin_permissions = (await session.execute(select(Permission).where(Permission.code.in_(ADMIN_PERMISSION_CODES)))).scalars().all()
        role = Role(code="admin", name="Administrador", active=True, system_role=True)
        role.permissions.extend(admin_permissions)
        session.add(role)
        await session.flush()
        return role

    async def _make_user(self, session, username: str, *, is_superuser: bool = False) -> User:
        role = await self._ensure_admin_role(session)
        user = User(username=username, display_name=username.title(), password_hash=hash_password("Senha forte seen 123"), active=True, is_superuser=is_superuser, password_changed_at=utcnow())
        if is_superuser:
            user.roles.append(role)
        session.add(user)
        await session.flush()
        return user

    async def _make_conversation(self, session, *, proposal_number: str) -> ChatConversation:
        proposal = Proposal(
            proposal_number=proposal_number,
            customer_name="Cliente Seen",
            proposal_date=date(2026, 8, 1),
            deadline_date=date(2026, 8, 20),
            source="MANUAL",
            version=1,
            source_hash=f"seen-{proposal_number}",
            legacy_id=-abs(hash(proposal_number)) % 1_000_000_000,
        )
        session.add(proposal)
        await session.flush()
        conversation = ChatConversation(kind="PROPOSTA", proposal_id=proposal.id, status="ATIVA")
        session.add(conversation)
        await session.flush()
        return conversation

    async def _count_queries(self, coro_factory):
        engine = get_engine()
        counter = QueryCounter()
        event.listen(engine.sync_engine, "before_cursor_execute", counter)
        try:
            result = await coro_factory()
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", counter)
        return result, counter.count

    def test_message_without_any_view(self):
        async def _run():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                author = await self._make_user(session, "author_novisao")
                conversation = await self._make_conversation(session, proposal_number="SEEN-NOVIEW")
                message = ChatMessage(conversation_id=conversation.id, author_user_id=author.id, message_type="MENSAGEM", body="oi")
                session.add(message)
                await session.commit()
                return await chat_service._seen_counts(session, [message])

        seen = asyncio.run(_run())
        self.assertEqual(list(seen.values())[0], 0)

    def test_message_with_a_single_view(self):
        async def _run():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                author = await self._make_user(session, "author_umavisao")
                reader = await self._make_user(session, "reader_umavisao")
                conversation = await self._make_conversation(session, proposal_number="SEEN-ONEVIEW")
                message = ChatMessage(conversation_id=conversation.id, author_user_id=author.id, message_type="MENSAGEM", body="oi")
                session.add(message)
                await session.flush()
                session.add(ChatMessageRead(conversation_id=conversation.id, user_id=reader.id, last_read_message_id=message.id))
                await session.commit()
                return await chat_service._seen_counts(session, [message])

        seen = asyncio.run(_run())
        self.assertEqual(list(seen.values())[0], 1)

    def test_message_with_multiple_views(self):
        async def _run():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                author = await self._make_user(session, "author_multiplas")
                readers = [await self._make_user(session, f"reader_multiplas_{i}") for i in range(7)]
                conversation = await self._make_conversation(session, proposal_number="SEEN-MULTIVIEW")
                message = ChatMessage(conversation_id=conversation.id, author_user_id=author.id, message_type="MENSAGEM", body="oi")
                session.add(message)
                await session.flush()
                for reader in readers:
                    session.add(ChatMessageRead(conversation_id=conversation.id, user_id=reader.id, last_read_message_id=message.id))
                await session.commit()
                return await chat_service._seen_counts(session, [message])

        seen = asyncio.run(_run())
        self.assertEqual(list(seen.values())[0], 7)

    def test_all_participants_viewed_the_last_message(self):
        async def _run():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                author = await self._make_user(session, "author_todos")
                participants = [await self._make_user(session, f"participant_todos_{i}") for i in range(5)]
                conversation = await self._make_conversation(session, proposal_number="SEEN-ALLVIEWED")
                messages = [ChatMessage(conversation_id=conversation.id, author_user_id=author.id, message_type="MENSAGEM", body=f"m{i}") for i in range(3)]
                session.add_all(messages)
                await session.flush()
                last_id = messages[-1].id
                for participant in participants:
                    session.add(ChatMessageRead(conversation_id=conversation.id, user_id=participant.id, last_read_message_id=last_id))
                await session.commit()
                return await chat_service._seen_counts(session, messages), [m.id for m in messages]

        seen, message_ids = asyncio.run(_run())
        for message_id in message_ids:
            self.assertEqual(seen[message_id], 5, "todos os participantes leram ate a ultima mensagem, entao TODAS as mensagens anteriores tambem foram vistas por todos")

    def test_different_users_have_independent_read_progress(self):
        async def _run():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                author = await self._make_user(session, "author_progresso")
                early_reader = await self._make_user(session, "reader_cedo")
                late_reader = await self._make_user(session, "reader_tarde")
                conversation = await self._make_conversation(session, proposal_number="SEEN-PROGRESS")
                messages = [ChatMessage(conversation_id=conversation.id, author_user_id=author.id, message_type="MENSAGEM", body=f"m{i}") for i in range(5)]
                session.add_all(messages)
                await session.flush()
                session.add(ChatMessageRead(conversation_id=conversation.id, user_id=early_reader.id, last_read_message_id=messages[1].id))
                session.add(ChatMessageRead(conversation_id=conversation.id, user_id=late_reader.id, last_read_message_id=messages[4].id))
                await session.commit()
                return await chat_service._seen_counts(session, messages), [m.id for m in messages]

        seen, message_ids = asyncio.run(_run())
        self.assertEqual(seen[message_ids[0]], 2)  # ambos ja passaram da 1a mensagem
        self.assertEqual(seen[message_ids[1]], 2)  # early_reader leu exatamente ate aqui
        self.assertEqual(seen[message_ids[2]], 1)  # so late_reader chegou aqui
        self.assertEqual(seen[message_ids[3]], 1)
        self.assertEqual(seen[message_ids[4]], 1)

    def test_multiple_conversations_do_not_leak_seen_counts_into_each_other(self):
        async def _run():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                author = await self._make_user(session, "author_duasconversas")
                reader_a = await self._make_user(session, "reader_conversa_a")
                conv_a = await self._make_conversation(session, proposal_number="SEEN-CONVA")
                conv_b = await self._make_conversation(session, proposal_number="SEEN-CONVB")
                message_a = ChatMessage(conversation_id=conv_a.id, author_user_id=author.id, message_type="MENSAGEM", body="a")
                message_b = ChatMessage(conversation_id=conv_b.id, author_user_id=author.id, message_type="MENSAGEM", body="b")
                session.add_all([message_a, message_b])
                await session.flush()
                # reader_a so leu a conversa A
                session.add(ChatMessageRead(conversation_id=conv_a.id, user_id=reader_a.id, last_read_message_id=message_a.id))
                await session.commit()
                return await chat_service._seen_counts(session, [message_a, message_b])

        seen = asyncio.run(_run())
        values = list(seen.values())
        self.assertIn(1, values)  # message_a: visto por reader_a
        self.assertIn(0, values)  # message_b: ninguem leu (esta em outra conversa)

    def test_thousands_of_messages_are_correct_and_query_count_stays_flat(self):
        async def _run():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                author = await self._make_user(session, "author_milhares")
                readers = [await self._make_user(session, f"reader_milhares_{i}") for i in range(30)]
                conversation = await self._make_conversation(session, proposal_number="SEEN-THOUSANDS")
                messages = [ChatMessage(conversation_id=conversation.id, author_user_id=author.id, message_type="MENSAGEM", body=f"m{i}") for i in range(3000)]
                session.add_all(messages)
                await session.flush()
                message_ids = [m.id for m in messages]
                for idx, reader in enumerate(readers):
                    read_up_to = message_ids[int(len(message_ids) * (idx + 1) / len(readers)) - 1]
                    session.add(ChatMessageRead(conversation_id=conversation.id, user_id=reader.id, last_read_message_id=read_up_to))
                await session.commit()

            async with session_factory() as session:
                loaded_messages = (
                    await session.execute(select(ChatMessage).where(ChatMessage.conversation_id == conversation.id).order_by(ChatMessage.created_at))
                ).scalars().all()
                seen, queries = await self._count_queries(lambda: chat_service._seen_counts(session, loaded_messages))
            return seen, queries, [m.id for m in loaded_messages]

        seen, queries, message_ids = asyncio.run(_run())
        self.assertEqual(queries, 1, "o calculo de 3000 mensagens x 30 leitores precisa ser 1 unica consulta agregada")
        self.assertEqual(seen[message_ids[0]], 30, "a primeira mensagem foi lida por todos os 30 leitores (todos leram alem dela)")
        self.assertEqual(seen[message_ids[-1]], 1, "so o ultimo leitor (que le mais) chegou na ultima mensagem")

    def test_seen_counts_query_count_does_not_grow_with_message_count(self):
        async def _run(message_count: int):
            await self._truncate()
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                author = await self._make_user(session, f"author_grow{message_count}")
                reader = await self._make_user(session, f"reader_grow{message_count}")
                conversation = await self._make_conversation(session, proposal_number=f"SEEN-GROW-{message_count}")
                messages = [ChatMessage(conversation_id=conversation.id, author_user_id=author.id, message_type="MENSAGEM", body=f"m{i}") for i in range(message_count)]
                session.add_all(messages)
                await session.flush()
                session.add(ChatMessageRead(conversation_id=conversation.id, user_id=reader.id, last_read_message_id=messages[-1].id))
                await session.commit()

            async with session_factory() as session:
                loaded = (
                    await session.execute(select(ChatMessage).where(ChatMessage.conversation_id == conversation.id).order_by(ChatMessage.created_at))
                ).scalars().all()
                _, queries = await self._count_queries(lambda: chat_service._seen_counts(session, loaded))
            return queries

        small_queries = asyncio.run(_run(20))
        large_queries = asyncio.run(_run(2000))
        self.assertEqual(small_queries, large_queries, "o numero de consultas nao pode depender da quantidade de mensagens")
        self.assertEqual(large_queries, 1)

    def test_seen_counts_are_stable_across_repeated_calls(self):
        async def _run():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                author = await self._make_user(session, "author_estavel")
                readers = [await self._make_user(session, f"reader_estavel_{i}") for i in range(4)]
                conversation = await self._make_conversation(session, proposal_number="SEEN-STABLE")
                messages = [ChatMessage(conversation_id=conversation.id, author_user_id=author.id, message_type="MENSAGEM", body=f"m{i}") for i in range(6)]
                session.add_all(messages)
                await session.flush()
                for reader in readers:
                    session.add(ChatMessageRead(conversation_id=conversation.id, user_id=reader.id, last_read_message_id=messages[3].id))
                await session.commit()

            results = []
            for _ in range(3):
                async with session_factory() as session:
                    loaded = (
                        await session.execute(select(ChatMessage).where(ChatMessage.conversation_id == conversation.id).order_by(ChatMessage.created_at))
                    ).scalars().all()
                    seen = await chat_service._seen_counts(session, loaded)
                    results.append(tuple(sorted(seen.items())))
            return results

        results = asyncio.run(_run())
        self.assertEqual(len(set(results)), 1, f"chamadas repetidas devem devolver exatamente o mesmo resultado, obtive {results}")

    def test_list_messages_and_timeline_expose_the_sql_calculated_count_without_extra_python_step(self):
        async def _run():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                author = await self._make_user(session, "author_endpoint", is_superuser=True)
                reader = await self._make_user(session, "reader_endpoint")
                proposal = Proposal(
                    proposal_number="SEEN-ENDPOINT",
                    customer_name="Cliente Endpoint",
                    proposal_date=date(2026, 8, 1),
                    deadline_date=date(2026, 8, 20),
                    source="MANUAL",
                    version=1,
                    source_hash="seen-endpoint",
                    legacy_id=-999777,
                )
                session.add(proposal)
                await session.flush()
                proposal_id = proposal.id
                conversation = ChatConversation(kind="PROPOSTA", proposal_id=proposal_id, status="ATIVA")
                session.add(conversation)
                await session.flush()
                message = ChatMessage(conversation_id=conversation.id, author_user_id=author.id, message_type="MENSAGEM", body="oi")
                session.add(message)
                await session.flush()
                session.add(ChatMessageRead(conversation_id=conversation.id, user_id=reader.id, last_read_message_id=message.id))
                await session.commit()

            async with session_factory() as session:
                actor = (await session.execute(select(User).where(User.username == "author_endpoint"))).scalars().first()
                via_list_messages = await chat_service.list_messages(session, conversation.id, actor)
            async with session_factory() as session:
                actor = (await session.execute(select(User).where(User.username == "author_endpoint"))).scalars().first()
                via_timeline = await chat_service.get_proposal_timeline(session, proposal_id, actor)
            return via_list_messages, via_timeline

        via_list_messages, via_timeline = asyncio.run(_run())
        self.assertEqual(via_list_messages.items[0].seen_by_count, 1)
        chat_entries = [item for item in via_timeline.items if item.source == "chat"]
        self.assertEqual(chat_entries[0].seen_by_count, 1)


if __name__ == "__main__":
    unittest.main()
