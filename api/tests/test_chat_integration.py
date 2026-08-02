from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from api.app.core.config import get_settings
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker
from api.app.main import create_app
from api.app.modules.auth.models import Permission, Role, User
from api.app.modules.auth.permissions import ADMIN_PERMISSION_CODES, CHAT_SEND, CHAT_VIEW
from api.app.modules.auth.security import hash_password
from api.app.modules.auth.tokens import utcnow
from api.app.modules.chat.models import ChatConversation


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
class ChatIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous = {"DATABASE_URL": os.environ.get("DATABASE_URL"), "APP_ENV": os.environ.get("APP_ENV"), "SECRET_KEY": os.environ.get("SECRET_KEY")}
        os.environ["APP_ENV"] = "test"
        os.environ["DATABASE_URL"] = TEST_DATABASE_URL
        os.environ["SECRET_KEY"] = os.environ.get("SECRET_KEY") or "chat-integration-secret-key-more-than-32-chars"
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
        asyncio.run(self._seed_users())
        self.client = TestClient(create_app())

    async def _seed_users(self):
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "TRUNCATE TABLE chat_notifications, chat_message_reads, chat_messages, chat_conversations, "
                    "security_events, auth_sessions, fiscal_events, fiscal_invoice_items, fiscal_invoices, "
                    "fiscal_items, fiscal_records, expedition_events, expedition_items, galvanization_load_events, "
                    "galvanization_load_items, galvanization_loads, proposal_events, proposal_items, proposals, "
                    "sync_runs, role_permissions, user_roles, users, roles RESTART IDENTITY CASCADE"
                )
            )
        session_factory = get_sessionmaker()
        async with session_factory() as session:
            admin_permissions = (await session.execute(select(Permission).where(Permission.code.in_(ADMIN_PERMISSION_CODES)))).scalars().all()
            admin_role = Role(code="admin", name="Administrador", active=True, system_role=True)
            admin_role.permissions.extend(admin_permissions)
            admin = User(
                username="admin",
                display_name="Administradora",
                password_hash=hash_password("Senha forte chat 123"),
                active=True,
                is_superuser=True,
                password_changed_at=utcnow(),
            )
            admin.roles.append(admin_role)
            session.add(admin)

            chat_permissions = (await session.execute(select(Permission).where(Permission.code.in_([CHAT_VIEW, CHAT_SEND])))).scalars().all()
            chat_role = Role(code="chat_user", name="Usuario de chat", active=True, system_role=False)
            chat_role.permissions.extend(chat_permissions)
            joao = User(
                username="joao",
                display_name="Joao Silva",
                password_hash=hash_password("Senha forte chat 123"),
                active=True,
                is_superuser=False,
                password_changed_at=utcnow(),
            )
            joao.roles.append(chat_role)
            session.add(joao)

            view_only_role = Role(code="chat_view_only", name="Usuario so leitura de chat", active=True, system_role=False)
            view_only_permission = next(p for p in chat_permissions if p.code == CHAT_VIEW)
            view_only_role.permissions.append(view_only_permission)
            carlos = User(
                username="carlos",
                display_name="Carlos Almeida",
                password_hash=hash_password("Senha forte chat 123"),
                active=True,
                is_superuser=False,
                password_changed_at=utcnow(),
            )
            carlos.roles.append(view_only_role)
            session.add(carlos)

            await session.commit()

    def _headers(self, username: str) -> dict:
        login = self.client.post("/api/v1/auth/login", json={"username": username, "password": "Senha forte chat 123"})
        self.assertEqual(login.status_code, 200, login.text)
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    def _user_id(self, username: str) -> int:
        async def _fetch():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                user = (await session.execute(select(User).where(User.username == username))).scalars().first()
                return user.id

        return asyncio.run(_fetch())

    def _create_proposal(self, headers: dict, proposal_number: str) -> dict:
        payload = {
            "proposal_number": proposal_number,
            "customer_name": "Cliente Chat",
            "project_name": "Site Chat",
            "purchase_order": "PC-CHAT",
            "batch_reference": "L-CHAT",
            "proposal_date": "2026-08-01",
            "deadline_date": "2026-08-10",
            "source": "MANUAL",
            "notes": "Criada para teste de chat",
            "items": [
                {
                    "item_number": "1",
                    "product_code": "COD-CHAT",
                    "description": "Item de teste",
                    "quantity": "2.0000",
                    "unit": "un",
                    "unit_weight": "3.5000",
                    "total_weight": "7.0000",
                    "produce_internally": True,
                    "requires_galvanization": True,
                }
            ],
        }
        created = self.client.post("/api/v1/proposals", json=payload, headers=headers)
        self.assertEqual(created.status_code, 201, created.text)
        return created.json()

    def test_general_chat_message_and_unread_and_mark_read(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")

        conversations = self.client.get("/api/v1/chat/conversations", headers=admin_headers)
        self.assertEqual(conversations.status_code, 200, conversations.text)
        general = next(item for item in conversations.json()["items"] if item["kind"] == "GERAL")
        self.assertEqual(general["unread_count"], 0)

        posted = self.client.post(
            f"/api/v1/chat/conversations/{general['id']}/messages",
            json={"body": "Bom dia a todos!", "message_type": "MENSAGEM"},
            headers=admin_headers,
        )
        self.assertEqual(posted.status_code, 201, posted.text)
        message_id = posted.json()["id"]
        self.assertEqual(posted.json()["author_name"], "Administradora")

        joao_view = self.client.get("/api/v1/chat/conversations", headers=joao_headers)
        joao_general = next(item for item in joao_view.json()["items"] if item["kind"] == "GERAL")
        self.assertEqual(joao_general["unread_count"], 1)

        marked = self.client.post(
            f"/api/v1/chat/conversations/{general['id']}/read",
            json={"last_read_message_id": message_id},
            headers=joao_headers,
        )
        self.assertEqual(marked.status_code, 204, marked.text)

        joao_view_after = self.client.get("/api/v1/chat/conversations", headers=joao_headers)
        joao_general_after = next(item for item in joao_view_after.json()["items"] if item["kind"] == "GERAL")
        self.assertEqual(joao_general_after["unread_count"], 0)

    def test_directed_question_generates_mention_notification_and_answer_marks_responded(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0001")
        joao_id = self._user_id("joao")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=admin_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        question = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Pode confirmar se o material ja foi separado?", "message_type": "PERGUNTA", "mentioned_user_id": joao_id},
            headers=admin_headers,
        )
        self.assertEqual(question.status_code, 201, question.text)
        self.assertEqual(question.json()["question_status"], "AGUARDANDO_RESPOSTA")
        self.assertEqual(question.json()["mentioned_user_name"], "Joao Silva")
        question_id = question.json()["id"]

        unread = self.client.get("/api/v1/chat/unread-summary", headers=joao_headers)
        self.assertEqual(unread.status_code, 200, unread.text)
        self.assertEqual(unread.json()["total_unread"], 1)
        self.assertEqual(unread.json()["conversations"][0]["conversation_id"], conversation_id)

        answer = self.client.post(
            f"/api/v1/chat/messages/{question_id}/answer",
            json={"body": "Sim, separacao concluida."},
            headers=joao_headers,
        )
        self.assertEqual(answer.status_code, 201, answer.text)
        self.assertEqual(answer.json()["answered_message_id"], question_id)

        timeline_after = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=admin_headers)
        entries = timeline_after.json()["items"]
        question_entry = next(item for item in entries if item["id"] == question_id and item["source"] == "chat")
        self.assertEqual(question_entry["question_status"], "RESPONDIDA")

        already_answered = self.client.post(
            f"/api/v1/chat/messages/{question_id}/answer",
            json={"body": "Outra resposta"},
            headers=joao_headers,
        )
        self.assertEqual(already_answered.status_code, 409)
        self.assertEqual(already_answered.json()["error"]["code"], "CHAT_QUESTION_ALREADY_ANSWERED")

    def test_proposal_timeline_merges_chat_messages_with_area_observations(self):
        admin_headers = self._headers("admin")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0002")

        released = self.client.post(
            f"/api/v1/proposals/{proposal['id']}/status",
            json={"version": proposal["version"], "to_area": "PRODUCAO", "to_status": "LIBERADO_PRODUCAO", "reason": "Necessario trocar uma chapa"},
            headers=admin_headers,
        )
        self.assertEqual(released.status_code, 200, released.text)

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=admin_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Vou acompanhar essa proposta.", "message_type": "MENSAGEM"},
            headers=admin_headers,
        )

        timeline_after = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=admin_headers)
        entries = timeline_after.json()["items"]
        self.assertEqual(entries, sorted(entries, key=lambda item: item["created_at"]))

        chat_entries = [item for item in entries if item["source"] == "chat"]
        area_entries = [item for item in entries if item["source"] != "chat"]
        self.assertTrue(any(item["entry_kind"] == "MENSAGEM" for item in chat_entries))
        self.assertTrue(any(item["entry_kind"] == "OBSERVACAO" and item["body"] == "Necessario trocar uma chapa" for item in area_entries))

    def test_permission_gates_send_and_finalized_visibility(self):
        joao_headers = self._headers("joao")
        carlos_headers = self._headers("carlos")

        conversations = self.client.get("/api/v1/chat/conversations", headers=joao_headers)
        general_id = next(item for item in conversations.json()["items"] if item["kind"] == "GERAL")["id"]

        blocked = self.client.post(
            f"/api/v1/chat/conversations/{general_id}/messages",
            json={"body": "Nao deveria conseguir enviar.", "message_type": "MENSAGEM"},
            headers=carlos_headers,
        )
        self.assertEqual(blocked.status_code, 403)

        blocked_finalized = self.client.get("/api/v1/chat/conversations?status=FINALIZADA", headers=joao_headers)
        self.assertEqual(blocked_finalized.status_code, 403)

    def _finalize_conversation(self, conversation_id: int) -> None:
        async def _update():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                conversation = await session.get(ChatConversation, conversation_id)
                conversation.status = "FINALIZADA"
                await session.commit()

        asyncio.run(_update())

    def test_finalized_conversation_content_is_blocked_without_permission(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0003")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=admin_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Mensagem antes de finalizar.", "message_type": "MENSAGEM"},
            headers=admin_headers,
        )

        # joao tem CHAT_VIEW mas nao CHAT_VIEW_FINALIZED: enquanto a conversa
        # esta ativa, ele consegue ler normalmente.
        active_messages = self.client.get(f"/api/v1/chat/conversations/{conversation_id}/messages", headers=joao_headers)
        self.assertEqual(active_messages.status_code, 200, active_messages.text)

        self._finalize_conversation(conversation_id)

        # depois de finalizada, o acesso direto por ID (nao so a listagem
        # filtrada) tem que ser bloqueado para quem nao tem a permissao.
        blocked_messages = self.client.get(f"/api/v1/chat/conversations/{conversation_id}/messages", headers=joao_headers)
        self.assertEqual(blocked_messages.status_code, 403, blocked_messages.text)

        blocked_timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        self.assertEqual(blocked_timeline.status_code, 403, blocked_timeline.text)

        # admin e superuser: continua enxergando o conteudo normalmente.
        admin_messages = self.client.get(f"/api/v1/chat/conversations/{conversation_id}/messages", headers=admin_headers)
        self.assertEqual(admin_messages.status_code, 200, admin_messages.text)


if __name__ == "__main__":
    unittest.main()
