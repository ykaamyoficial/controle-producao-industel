from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from api.app.core import error_codes
from api.app.core.config import get_settings
from api.app.core.exceptions import ApiError
from api.app.database.session import dispose_engine, get_engine, get_sessionmaker
from api.app.main import create_app
from api.app.modules.auth import repository as auth_repository
from api.app.modules.auth.models import Permission, Role, User
from api.app.modules.auth.permissions import ADMIN_PERMISSION_CODES, CHAT_SEND, CHAT_VIEW
from api.app.modules.auth.security import hash_password
from api.app.modules.auth.tokens import utcnow
from api.app.modules.chat import service as chat_service
from api.app.modules.chat.models import ChatConversation, ChatMessage, ChatMessageRead, ChatNotification


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

            patricia = User(
                username="patricia",
                display_name="Patricia Souza",
                password_hash=hash_password("Senha forte chat 123"),
                active=True,
                is_superuser=False,
                password_changed_at=utcnow(),
            )
            patricia.roles.append(chat_role)
            session.add(patricia)

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
        self.assertEqual(marked.status_code, 200, marked.text)

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

    def test_proposal_timeline_never_mixes_in_operational_activity(self):
        """O chat de uma proposta so pode conter comunicacao humana — eventos
        operacionais (mudanca de status/area) vivem exclusivamente no feed de
        Atividade (/proposals/{id}/activities), nunca no timeline de chat."""
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
        self.assertTrue(entries)
        self.assertTrue(all(item["source"] == "chat" for item in entries))
        self.assertTrue(all(item["entry_kind"] in ("MENSAGEM", "PERGUNTA", "NOTA_INTERNA") for item in entries))
        self.assertTrue(any(item["entry_kind"] == "MENSAGEM" for item in entries))

        activities = self.client.get(f"/api/v1/proposals/{proposal['id']}/activities", headers=admin_headers)
        self.assertEqual(activities.status_code, 200, activities.text)
        headlines = [item["headline"] for item in activities.json()]
        self.assertTrue(headlines)
        forbidden = ("version:", "item_version:", "from:", "to:", "payload", "proposal_id", "item_id")
        for headline in headlines:
            lowered = headline.lower()
            for token in forbidden:
                self.assertNotIn(token, lowered)

    def test_plain_message_notifies_prior_participants_and_mention_adds_specific_type(self):
        # ETAPA 3: mensagem comum passou a notificar (tipo MENSAGEM) quem ja
        # participou da conversa antes (autor de mensagem anterior) — nao so
        # quem e mencionado. "Participante" e definido pelo historico real da
        # conversa, entao quem nunca escreveu nela (carlos) continua sem
        # receber nada so por ter permissao de ver o chat.
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        carlos_headers = self._headers("carlos")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0004")
        joao_id = self._user_id("joao")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=admin_headers)
        conversation_id = timeline.json()["conversation_id"]

        # 1a mensagem da conversa: ainda nao ha participante anterior nenhum.
        first = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Abrindo a conversa desta proposta.", "message_type": "MENSAGEM"},
            headers=admin_headers,
        )
        self.assertEqual(first.status_code, 201, first.text)
        joao_notifications = self.client.get("/api/v1/chat/notifications", headers=joao_headers)
        self.assertEqual(joao_notifications.json()["total"], 0)

        # joao responde: agora ele e participante (autor de mensagem
        # anterior). A propria mensagem dele nao gera notificacao pra ele.
        joao_reply = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Recebido, vou verificar.", "message_type": "MENSAGEM"},
            headers=joao_headers,
        )
        self.assertEqual(joao_reply.status_code, 201, joao_reply.text)
        joao_notifications_after_own = self.client.get("/api/v1/chat/notifications", headers=joao_headers)
        self.assertEqual(joao_notifications_after_own.json()["total"], 0)

        # mensagem comum de admin, sem mencao: joao (participante) recebe
        # MENSAGEM; carlos (nunca escreveu aqui) continua sem nada.
        plain = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Alguma novidade por aqui?", "message_type": "MENSAGEM"},
            headers=admin_headers,
        )
        self.assertEqual(plain.status_code, 201, plain.text)
        joao_notifications_plain = self.client.get("/api/v1/chat/notifications", headers=joao_headers)
        self.assertEqual(joao_notifications_plain.json()["total"], 1)
        self.assertEqual(joao_notifications_plain.json()["items"][0]["notification_type"], "MENSAGEM")
        carlos_notifications = self.client.get("/api/v1/chat/notifications", headers=carlos_headers)
        self.assertEqual(carlos_notifications.json()["total"], 0)

        # mensagem com @mencao: o mencionado recebe MENCAO (tipo mais
        # especifico) alem da MENSAGEM anterior — nunca 2 notificacoes pelo
        # mesmo evento (dedup e por user+message+type, sao mensagens distintas).
        mentioned = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Joao consegue confirmar o peso do item?", "message_type": "MENSAGEM", "mentioned_user_id": joao_id},
            headers=admin_headers,
        )
        self.assertEqual(mentioned.status_code, 201, mentioned.text)
        joao_notifications_mentioned = self.client.get("/api/v1/chat/notifications", headers=joao_headers)
        self.assertEqual(joao_notifications_mentioned.json()["total"], 2)
        self.assertEqual(joao_notifications_mentioned.json()["items"][0]["notification_type"], "MENCAO")

        carlos_notifications_after = self.client.get("/api/v1/chat/notifications", headers=carlos_headers)
        self.assertEqual(carlos_notifications_after.json()["total"], 0)

    def test_reply_to_message_notifies_original_author(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0005")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=admin_headers)
        conversation_id = timeline.json()["conversation_id"]

        original = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Os itens ja estao prontos.", "message_type": "MENSAGEM"},
            headers=admin_headers,
        )
        original_id = original.json()["id"]

        reply = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Otimo, vou incluir na proxima carga.", "message_type": "MENSAGEM", "reply_to_message_id": original_id},
            headers=joao_headers,
        )
        self.assertEqual(reply.status_code, 201, reply.text)
        self.assertEqual(reply.json()["answered_message_id"], original_id)

        admin_notifications = self.client.get("/api/v1/chat/notifications", headers=admin_headers)
        self.assertEqual(admin_notifications.json()["total"], 1)
        self.assertEqual(admin_notifications.json()["items"][0]["notification_type"], "RESPOSTA")

    def test_internal_note_is_stored_distinctly_and_does_not_notify_without_mention(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0006")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=admin_headers)
        conversation_id = timeline.json()["conversation_id"]

        note = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Item 4 aguardando chegada do material.", "message_type": "NOTA_INTERNA", "area": "PRODUCAO"},
            headers=admin_headers,
        )
        self.assertEqual(note.status_code, 201, note.text)
        self.assertEqual(note.json()["message_type"], "NOTA_INTERNA")
        self.assertEqual(note.json()["area"], "PRODUCAO")

        joao_notifications = self.client.get("/api/v1/chat/notifications", headers=joao_headers)
        self.assertEqual(joao_notifications.json()["total"], 0)

        timeline_after = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=admin_headers)
        note_entry = next(item for item in timeline_after.json()["items"] if item["id"] == note.json()["id"])
        self.assertEqual(note_entry["entry_kind"], "NOTA_INTERNA")
        self.assertEqual(note_entry["area"], "PRODUCAO")

    def test_overdue_question_computed_and_notified_exactly_once(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0007")
        patricia_id = self._user_id("patricia")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        conversation_id = timeline.json()["conversation_id"]

        past_due = "2020-01-01T00:00:00Z"
        question = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Isso deve ser galvanizado?", "message_type": "PERGUNTA", "mentioned_user_id": patricia_id, "due_at": past_due},
            headers=joao_headers,
        )
        self.assertEqual(question.status_code, 201, question.text)
        question_id = question.json()["id"]

        # status efetivo (calculado, nunca gravado) ja aparece atrasado assim
        # que o prazo vencido e lido, sem precisar de nenhum job/varredura.
        messages = self.client.get(f"/api/v1/chat/conversations/{conversation_id}/messages", headers=patricia_headers)
        posted = next(item for item in messages.json()["items"] if item["id"] == question_id)
        self.assertEqual(posted["question_status"], "ATRASADA")

        first_check = self.client.get("/api/v1/chat/notifications", headers=patricia_headers)
        self.assertEqual(first_check.status_code, 200, first_check.text)
        types_first = [item["notification_type"] for item in first_check.json()["items"] if item["message_id"] == question_id]
        self.assertIn("PERGUNTA_ATRIBUIDA", types_first)
        self.assertIn("PERGUNTA_ATRASADA", types_first)
        self.assertEqual(types_first.count("PERGUNTA_ATRASADA"), 1)

        # repetir a consulta (poll/reconexao) nao duplica a notificacao de atraso.
        second_check = self.client.get("/api/v1/chat/notifications", headers=patricia_headers)
        types_second = [item["notification_type"] for item in second_check.json()["items"] if item["message_id"] == question_id]
        self.assertEqual(types_second.count("PERGUNTA_ATRASADA"), 1)

        unread = self.client.get("/api/v1/chat/unread-summary", headers=patricia_headers)
        self.assertEqual(unread.json()["pending_questions"], 1)

    def test_answer_marks_answered_and_notifies_author_distinctly(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0008")
        patricia_id = self._user_id("patricia")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        conversation_id = timeline.json()["conversation_id"]
        question = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Confirma o peso?", "message_type": "PERGUNTA", "mentioned_user_id": patricia_id},
            headers=joao_headers,
        )
        question_id = question.json()["id"]

        answered = self.client.post(f"/api/v1/chat/messages/{question_id}/answer", json={"body": "Sim, confirmado."}, headers=patricia_headers)
        self.assertEqual(answered.status_code, 201, answered.text)

        joao_notifications = self.client.get("/api/v1/chat/notifications", headers=joao_headers)
        types = [item["notification_type"] for item in joao_notifications.json()["items"]]
        self.assertIn("PERGUNTA_RESPONDIDA", types)
        self.assertNotIn("RESPOSTA", types)

        already_answered = self.client.post(f"/api/v1/chat/messages/{question_id}/answer", json={"body": "De novo"}, headers=patricia_headers)
        self.assertEqual(already_answered.status_code, 409)

    def test_cancel_question_permission_and_state(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0009")
        patricia_id = self._user_id("patricia")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        conversation_id = timeline.json()["conversation_id"]
        question = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Precisa retrabalho?", "message_type": "PERGUNTA", "mentioned_user_id": patricia_id},
            headers=joao_headers,
        )
        question_id = question.json()["id"]

        # o responsavel (nao autor, nao admin) nao pode cancelar a pergunta dos outros.
        denied = self.client.post(f"/api/v1/chat/messages/{question_id}/cancel", json={"reason": "teste"}, headers=patricia_headers)
        self.assertEqual(denied.status_code, 403, denied.text)

        cancelled = self.client.post(
            f"/api/v1/chat/messages/{question_id}/cancel", json={"reason": "Nao e mais necessario"}, headers=joao_headers
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["question_status"], "CANCELADA")

        blocked_answer = self.client.post(f"/api/v1/chat/messages/{question_id}/answer", json={"body": "Resposta tardia"}, headers=patricia_headers)
        self.assertEqual(blocked_answer.status_code, 409)
        self.assertEqual(blocked_answer.json()["error"]["code"], "CHAT_QUESTION_CANCELLED")

    def test_reassign_question_requires_admin_and_valid_assignee(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        carlos_headers = self._headers("carlos")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0010")
        patricia_id = self._user_id("patricia")
        carlos_id = self._user_id("carlos")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        conversation_id = timeline.json()["conversation_id"]
        question = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Quem finaliza isso?", "message_type": "PERGUNTA", "mentioned_user_id": patricia_id},
            headers=joao_headers,
        )
        question_id = question.json()["id"]

        # joao (autor, sem chat.admin) nao pode reatribuir.
        denied = self.client.patch(
            f"/api/v1/chat/messages/{question_id}/assignee",
            json={"assignee_user_id": carlos_id, "reason": "tentativa"},
            headers=joao_headers,
        )
        self.assertEqual(denied.status_code, 403, denied.text)

        # carlos so tem chat.view (nao consegue responder) — nao pode virar responsavel.
        invalid_assignee = self.client.patch(
            f"/api/v1/chat/messages/{question_id}/assignee",
            json={"assignee_user_id": carlos_id, "reason": "trocar responsavel"},
            headers=admin_headers,
        )
        self.assertEqual(invalid_assignee.status_code, 422, invalid_assignee.text)

        reassigned = self.client.patch(
            f"/api/v1/chat/messages/{question_id}/assignee",
            json={"assignee_user_id": self._user_id("joao"), "reason": "Patricia esta de ferias"},
            headers=admin_headers,
        )
        self.assertEqual(reassigned.status_code, 200, reassigned.text)
        self.assertEqual(reassigned.json()["mentioned_user_id"], self._user_id("joao"))

        joao_notifications = self.client.get("/api/v1/chat/notifications", headers=joao_headers)
        types = [item["notification_type"] for item in joao_notifications.json()["items"] if item["message_id"] == question_id]
        self.assertIn("PERGUNTA_ATRIBUIDA", types)

    def test_inactive_user_cannot_be_assignee(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0011")

        async def _deactivate_patricia():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                user = (await session.execute(select(User).where(User.username == "patricia"))).scalars().first()
                user.active = False
                await session.commit()

        asyncio.run(_deactivate_patricia())
        patricia_id = self._user_id("patricia")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        conversation_id = timeline.json()["conversation_id"]
        blocked = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Pergunta para usuario inativo", "message_type": "PERGUNTA", "mentioned_user_id": patricia_id},
            headers=joao_headers,
        )
        self.assertEqual(blocked.status_code, 422, blocked.text)
        self.assertEqual(blocked.json()["error"]["code"], "CHAT_MENTIONED_USER_INVALID")

    def test_mark_notification_read_only_by_owner(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0012")
        patricia_id = self._user_id("patricia")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        conversation_id = timeline.json()["conversation_id"]
        question = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Pergunta simples", "message_type": "PERGUNTA", "mentioned_user_id": patricia_id},
            headers=joao_headers,
        )
        question_id = question.json()["id"]

        notifications = self.client.get("/api/v1/chat/notifications", headers=patricia_headers)
        notification_id = next(item["id"] for item in notifications.json()["items"] if item["message_id"] == question_id)

        stolen = self.client.post(f"/api/v1/chat/notifications/{notification_id}/read", headers=joao_headers)
        self.assertEqual(stolen.status_code, 404, stolen.text)

        owned = self.client.post(f"/api/v1/chat/notifications/{notification_id}/read", headers=patricia_headers)
        self.assertEqual(owned.status_code, 204, owned.text)

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

    def test_proposal_chat_unread_is_per_user_and_excludes_own_messages(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0004")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        def _conversation_for(headers):
            listing = self.client.get("/api/v1/chat/conversations", headers=headers)
            self.assertEqual(listing.status_code, 200, listing.text)
            return next(item for item in listing.json()["items"] if item["id"] == conversation_id)

        message_ids = []
        for body in ["Mensagem 1", "Mensagem 2", "Mensagem 3"]:
            posted = self.client.post(
                f"/api/v1/chat/conversations/{conversation_id}/messages",
                json={"body": body, "message_type": "MENSAGEM"},
                headers=joao_headers,
            )
            self.assertEqual(posted.status_code, 201, posted.text)
            message_ids.append(posted.json()["id"])

        # joao enviou as 3 mensagens: elas nao contam como nao lidas para ele proprio.
        self.assertEqual(_conversation_for(joao_headers)["unread_count"], 0)
        # patricia nao enviou nem leu nada: as 3 mensagens estao nao lidas para ela.
        self.assertEqual(_conversation_for(patricia_headers)["unread_count"], 3)

        marked = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/read",
            json={"last_read_message_id": message_ids[1]},
            headers=patricia_headers,
        )
        self.assertEqual(marked.status_code, 200, marked.text)
        # patricia leu ate a 2a mensagem: so a 3a continua nao lida.
        self.assertEqual(_conversation_for(patricia_headers)["unread_count"], 1)
        # o cursor de patricia nao afeta o contador (proprio, sempre 0) de joao.
        self.assertEqual(_conversation_for(joao_headers)["unread_count"], 0)

        fourth = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Mensagem 4", "message_type": "MENSAGEM"},
            headers=joao_headers,
        )
        self.assertEqual(fourth.status_code, 201, fourth.text)

        # mensagem chegou depois do cursor de patricia: continua nao lida, somada a 3a.
        self.assertEqual(_conversation_for(patricia_headers)["unread_count"], 2)

    def test_mark_read_is_idempotent_and_cursor_never_regresses(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0005")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        message_ids = []
        for body in ["Um", "Dois", "Tres"]:
            posted = self.client.post(
                f"/api/v1/chat/conversations/{conversation_id}/messages",
                json={"body": body, "message_type": "MENSAGEM"},
                headers=joao_headers,
            )
            self.assertEqual(posted.status_code, 201, posted.text)
            message_ids.append(posted.json()["id"])

        def _unread_for_patricia():
            listing = self.client.get("/api/v1/chat/conversations", headers=patricia_headers)
            return next(item for item in listing.json()["items"] if item["id"] == conversation_id)["unread_count"]

        self.assertEqual(_unread_for_patricia(), 3)

        first_mark = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/read",
            json={"last_read_message_id": message_ids[-1]},
            headers=patricia_headers,
        )
        self.assertEqual(first_mark.status_code, 200, first_mark.text)
        self.assertEqual(_unread_for_patricia(), 0)

        # reenviar o mesmo cursor precisa ser idempotente: sem erro, sem mudanca.
        repeated_mark = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/read",
            json={"last_read_message_id": message_ids[-1]},
            headers=patricia_headers,
        )
        self.assertEqual(repeated_mark.status_code, 200, repeated_mark.text)
        self.assertEqual(_unread_for_patricia(), 0)

        # um cursor mais antigo que o ja registrado nao pode fazer o cursor regredir.
        stale_mark = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/read",
            json={"last_read_message_id": message_ids[0]},
            headers=patricia_headers,
        )
        self.assertEqual(stale_mark.status_code, 200, stale_mark.text)
        self.assertEqual(_unread_for_patricia(), 0)

    def test_mark_read_rejected_without_finalized_permission(self):
        admin_headers = self._headers("admin")
        carlos_headers = self._headers("carlos")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0006")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=admin_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        posted = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Mensagem antes de finalizar.", "message_type": "MENSAGEM"},
            headers=admin_headers,
        )
        self.assertEqual(posted.status_code, 201, posted.text)
        message_id = posted.json()["id"]

        # carlos tem CHAT_VIEW mas nao CHAT_VIEW_FINALIZED: enquanto ativa, ele
        # consegue marcar a conversa como lida normalmente.
        active_mark = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/read",
            json={"last_read_message_id": message_id},
            headers=carlos_headers,
        )
        self.assertEqual(active_mark.status_code, 200, active_mark.text)

        self._finalize_conversation(conversation_id)

        # depois de finalizada, marcar como lida exige a mesma permissao que ver
        # o conteudo da conversa (CHAT_VIEW_FINALIZED) — carlos nao tem.
        blocked_mark = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/read",
            json={"last_read_message_id": message_id},
            headers=carlos_headers,
        )
        self.assertEqual(blocked_mark.status_code, 403, blocked_mark.text)

        # admin e superuser: continua conseguindo marcar como lida mesmo finalizada.
        admin_mark = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/read",
            json={"last_read_message_id": message_id},
            headers=admin_headers,
        )
        self.assertEqual(admin_mark.status_code, 200, admin_mark.text)

    def test_global_unread_is_sum_of_conversations_and_updates_after_mark_read(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal_a = self._create_proposal(admin_headers, "CP-CHAT-0007")
        proposal_b = self._create_proposal(admin_headers, "CP-CHAT-0008")

        timeline_a = self.client.get(f"/api/v1/chat/proposals/{proposal_a['id']}/timeline", headers=joao_headers)
        self.assertEqual(timeline_a.status_code, 200, timeline_a.text)
        conversation_a = timeline_a.json()["conversation_id"]
        timeline_b = self.client.get(f"/api/v1/chat/proposals/{proposal_b['id']}/timeline", headers=joao_headers)
        self.assertEqual(timeline_b.status_code, 200, timeline_b.text)
        conversation_b = timeline_b.json()["conversation_id"]

        def _send(conversation_id, count):
            ids = []
            for i in range(count):
                posted = self.client.post(
                    f"/api/v1/chat/conversations/{conversation_id}/messages",
                    json={"body": f"Mensagem {i}", "message_type": "MENSAGEM"},
                    headers=joao_headers,
                )
                self.assertEqual(posted.status_code, 201, posted.text)
                ids.append(posted.json()["id"])
            return ids

        ids_a = _send(conversation_a, 2)
        _send(conversation_b, 5)

        def _unread_summary(headers):
            response = self.client.get("/api/v1/chat/unread-summary", headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        # CP1=2 + CP2=5: o total precisa ser a soma exata, nao um numero solto.
        patricia_summary = _unread_summary(patricia_headers)
        self.assertEqual(patricia_summary["total_unread"], 7)
        by_conversation = {item["conversation_id"]: item["unread_count"] for item in patricia_summary["conversations"]}
        self.assertEqual(by_conversation[conversation_a], 2)
        self.assertEqual(by_conversation[conversation_b], 5)

        # joao enviou todas as mensagens: o total dele proprio nunca aumenta.
        joao_summary = _unread_summary(joao_headers)
        self.assertEqual(joao_summary["total_unread"], 0)

        marked = self.client.post(
            f"/api/v1/chat/conversations/{conversation_a}/read",
            json={"last_read_message_id": ids_a[-1]},
            headers=patricia_headers,
        )
        self.assertEqual(marked.status_code, 200, marked.text)

        # ler as 2 da CP1 tem que derrubar o total exatamente por 2 (7 -> 5),
        # mantendo intactas as 5 nao lidas da CP2.
        patricia_summary_after = _unread_summary(patricia_headers)
        self.assertEqual(patricia_summary_after["total_unread"], 5)

    def test_global_unread_excludes_finalized_conversation_without_permission(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        carlos_headers = self._headers("carlos")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0009")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]
        posted = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Antes de finalizar.", "message_type": "MENSAGEM"},
            headers=joao_headers,
        )
        self.assertEqual(posted.status_code, 201, posted.text)

        before = self.client.get("/api/v1/chat/unread-summary", headers=carlos_headers)
        self.assertEqual(before.status_code, 200, before.text)
        self.assertEqual(before.json()["total_unread"], 1)

        self._finalize_conversation(conversation_id)

        # carlos nao tem CHAT_VIEW_FINALIZED: a conversa finalizada some do
        # total dele e da listagem — ele nunca vai conseguir marca-la como
        # lida (mark_read exige a mesma permissao), entao ela nao pode ficar
        # inflando um contador que ele nao consegue zerar.
        after = self.client.get("/api/v1/chat/unread-summary", headers=carlos_headers)
        self.assertEqual(after.status_code, 200, after.text)
        self.assertEqual(after.json()["total_unread"], 0)
        listing = self.client.get("/api/v1/chat/conversations", headers=carlos_headers)
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertNotIn(conversation_id, [item["id"] for item in listing.json()["items"]])

        # admin e superuser: continua contando e enxergando a conversa normalmente.
        admin_summary = self.client.get("/api/v1/chat/unread-summary", headers=admin_headers)
        self.assertEqual(admin_summary.status_code, 200, admin_summary.text)
        self.assertEqual(admin_summary.json()["total_unread"], 1)
        admin_listing = self.client.get("/api/v1/chat/conversations", headers=admin_headers)
        self.assertEqual(admin_listing.status_code, 200, admin_listing.text)
        self.assertIn(conversation_id, [item["id"] for item in admin_listing.json()["items"]])

    def test_global_unread_mark_read_idempotent_does_not_double_count(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0010")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        message_ids = []
        for body in ["Um", "Dois"]:
            posted = self.client.post(
                f"/api/v1/chat/conversations/{conversation_id}/messages",
                json={"body": body, "message_type": "MENSAGEM"},
                headers=joao_headers,
            )
            self.assertEqual(posted.status_code, 201, posted.text)
            message_ids.append(posted.json()["id"])

        def _total_for_patricia():
            response = self.client.get("/api/v1/chat/unread-summary", headers=patricia_headers)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()["total_unread"]

        self.assertEqual(_total_for_patricia(), 2)

        first = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/read",
            json={"last_read_message_id": message_ids[-1]},
            headers=patricia_headers,
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(_total_for_patricia(), 0)

        repeated = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/read",
            json={"last_read_message_id": message_ids[-1]},
            headers=patricia_headers,
        )
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertEqual(_total_for_patricia(), 0)

        stale = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/read",
            json={"last_read_message_id": message_ids[0]},
            headers=patricia_headers,
        )
        self.assertEqual(stale.status_code, 200, stale.text)
        # cursor nao pode retroceder: o total continua 0, nao volta a contar a
        # 1a mensagem so porque um cursor antigo foi reenviado depois.
        self.assertEqual(_total_for_patricia(), 0)

    def test_chat_message_notification_insert_is_deduplicated(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0011")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]
        posted = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Mensagem para testar deduplicacao.", "message_type": "MENSAGEM"},
            headers=joao_headers,
        )
        self.assertEqual(posted.status_code, 201, posted.text)
        message_id = posted.json()["id"]
        admin_id = self._user_id("admin")

        async def _insert_twice_and_count():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                await chat_service._insert_notification(
                    session, user_id=admin_id, conversation_id=conversation_id, message_id=message_id, notification_type="MENSAGEM"
                )
                await chat_service._insert_notification(
                    session, user_id=admin_id, conversation_id=conversation_id, message_id=message_id, notification_type="MENSAGEM"
                )
                await session.commit()
                rows = (
                    await session.execute(
                        select(ChatNotification).where(
                            ChatNotification.user_id == admin_id,
                            ChatNotification.message_id == message_id,
                            ChatNotification.notification_type == "MENSAGEM",
                        )
                    )
                ).scalars().all()
                return len(rows)

        # retry/reprocessamento da mesma notificacao (mesmo user+mensagem+tipo)
        # nao pode duplicar — a constraint unica + ON CONFLICT DO NOTHING garantem isso.
        self.assertEqual(asyncio.run(_insert_twice_and_count()), 1)

    def test_mark_read_syncs_message_notifications_respecting_cursor_and_race(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0012")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=patricia_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        # patricia entra primeiro na conversa — fica estabelecida como participante.
        intro = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Alguem pode revisar isso?", "message_type": "MENSAGEM"},
            headers=patricia_headers,
        )
        self.assertEqual(intro.status_code, 201, intro.text)

        message_ids = []
        for body in ["Um", "Dois", "Tres"]:
            posted = self.client.post(
                f"/api/v1/chat/conversations/{conversation_id}/messages",
                json={"body": body, "message_type": "MENSAGEM"},
                headers=joao_headers,
            )
            self.assertEqual(posted.status_code, 201, posted.text)
            message_ids.append(posted.json()["id"])

        def _notification_unread_for(headers):
            response = self.client.get("/api/v1/chat/unread-summary", headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()["notification_unread_count"]

        # patricia (participante) recebe as 3 notificacoes MENSAGEM de joao.
        self.assertEqual(_notification_unread_for(patricia_headers), 3)
        # joao nunca recebe notificacao das proprias mensagens — estado independente.
        self.assertEqual(_notification_unread_for(joao_headers), 0)

        marked = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/read",
            json={"last_read_message_id": message_ids[1]},
            headers=patricia_headers,
        )
        self.assertEqual(marked.status_code, 200, marked.text)
        # leu ate a 2a mensagem de joao: a notificacao correspondente vira READ,
        # sobra so a 3a.
        self.assertEqual(_notification_unread_for(patricia_headers), 1)

        # mensagem nova chega depois do cursor: nao pode ser marcada por acidente.
        fourth = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Quatro", "message_type": "MENSAGEM"},
            headers=joao_headers,
        )
        self.assertEqual(fourth.status_code, 201, fourth.text)
        self.assertEqual(_notification_unread_for(patricia_headers), 2)

        # cursor antigo reenviado nao pode "deslê" nada nem derrubar o contador.
        stale = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/read",
            json={"last_read_message_id": message_ids[0]},
            headers=patricia_headers,
        )
        self.assertEqual(stale.status_code, 200, stale.text)
        self.assertEqual(_notification_unread_for(patricia_headers), 2)

    def test_chat_message_notification_skipped_for_inactive_user(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0013")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=patricia_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        intro = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Primeira mensagem.", "message_type": "MENSAGEM"},
            headers=patricia_headers,
        )
        self.assertEqual(intro.status_code, 201, intro.text)

        async def _deactivate_patricia():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                user = (await session.execute(select(User).where(User.username == "patricia"))).scalars().first()
                user.active = False
                await session.commit()

        asyncio.run(_deactivate_patricia())

        posted = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Alguem ainda esta ai?", "message_type": "MENSAGEM"},
            headers=joao_headers,
        )
        self.assertEqual(posted.status_code, 201, posted.text)

        async def _notification_count_for_patricia():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                user = (await session.execute(select(User).where(User.username == "patricia"))).scalars().first()
                rows = (
                    await session.execute(
                        select(ChatNotification).where(
                            ChatNotification.user_id == user.id, ChatNotification.notification_type == "MENSAGEM"
                        )
                    )
                ).scalars().all()
                return len(rows)

        # patricia participou antes, mas esta inativa agora: nao recebe a
        # notificacao da mensagem nova de joao.
        self.assertEqual(asyncio.run(_notification_count_for_patricia()), 0)

    def test_mention_generates_single_notification_and_excludes_self(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0014")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=patricia_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        # patricia entra primeiro: fica participante da conversa.
        intro = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Abrindo a conversa.", "message_type": "MENSAGEM"},
            headers=patricia_headers,
        )
        self.assertEqual(intro.status_code, 201, intro.text)

        patricia_id = self._user_id("patricia")
        joao_id = self._user_id("joao")
        carlos_id = self._user_id("carlos")

        mentioned = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Patricia pode revisar este item?", "message_type": "MENSAGEM", "mentioned_user_id": patricia_id},
            headers=joao_headers,
        )
        self.assertEqual(mentioned.status_code, 201, mentioned.text)
        message_id = mentioned.json()["id"]

        async def _notifications_for(user_id, msg_id):
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                rows = (
                    await session.execute(
                        select(ChatNotification).where(ChatNotification.user_id == user_id, ChatNotification.message_id == msg_id)
                    )
                ).scalars().all()
                return rows

        # patricia foi mencionada: exatamente 1 notificacao, tipo MENCAO — nunca
        # MENCAO + MENSAGEM pelo mesmo evento.
        patricia_rows = asyncio.run(_notifications_for(patricia_id, message_id))
        self.assertEqual(len(patricia_rows), 1)
        self.assertEqual(patricia_rows[0].notification_type, "MENCAO")

        # carlos nunca participou e nao foi mencionado: nada pra ele.
        self.assertEqual(len(asyncio.run(_notifications_for(carlos_id, message_id))), 0)
        # joao e o autor: nunca recebe notificacao da propria mensagem.
        self.assertEqual(len(asyncio.run(_notifications_for(joao_id, message_id))), 0)

        # joao se automenciona numa 2a mensagem: continua sem notificacao pra si.
        self_mentioned = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Joao lembrete pra mim.", "message_type": "MENSAGEM", "mentioned_user_id": joao_id},
            headers=joao_headers,
        )
        self.assertEqual(self_mentioned.status_code, 201, self_mentioned.text)
        self.assertEqual(len(asyncio.run(_notifications_for(joao_id, self_mentioned.json()["id"]))), 0)

    def test_mention_rejected_for_invalid_or_inaccessible_user(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0015")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        # usuario inexistente.
        nonexistent = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Fulano confere isso?", "message_type": "MENSAGEM", "mentioned_user_id": 999999},
            headers=joao_headers,
        )
        self.assertEqual(nonexistent.status_code, 422, nonexistent.text)
        self.assertEqual(nonexistent.json()["error"]["code"], "CHAT_MENTIONED_USER_INVALID")

        # usuario existe mas esta desativado.
        async def _create_inactive_user():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                user = User(
                    username="inativo",
                    display_name="Usuario Inativo",
                    password_hash=hash_password("Senha forte chat 123"),
                    active=False,
                    is_superuser=False,
                    password_changed_at=utcnow(),
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)
                return user.id

        inactive_id = asyncio.run(_create_inactive_user())
        inactive_mention = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Inativo confere isso?", "message_type": "MENSAGEM", "mentioned_user_id": inactive_id},
            headers=joao_headers,
        )
        self.assertEqual(inactive_mention.status_code, 422, inactive_mention.text)
        self.assertEqual(inactive_mention.json()["error"]["code"], "CHAT_MENTIONED_USER_INVALID")

        # usuario existe, ativo, mas sem nenhuma permissao de chat.
        async def _create_user_without_chat_permission():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                user = User(
                    username="semchat",
                    display_name="Sem Chat",
                    password_hash=hash_password("Senha forte chat 123"),
                    active=True,
                    is_superuser=False,
                    password_changed_at=utcnow(),
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)
                return user.id

        no_permission_id = asyncio.run(_create_user_without_chat_permission())
        no_permission_mention = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@SemChat confere isso?", "message_type": "MENSAGEM", "mentioned_user_id": no_permission_id},
            headers=joao_headers,
        )
        self.assertEqual(no_permission_mention.status_code, 422, no_permission_mention.text)
        self.assertEqual(no_permission_mention.json()["error"]["code"], "CHAT_MENTIONED_USER_INVALID")

    def test_mark_read_syncs_mention_and_keeps_chat_bell_counts_consistent(self):
        # Reproduz o cenario de integracao completo do enunciado: joao/carlos/maria
        # na CP05240 (aqui CP-CHAT-0016), joao menciona carlos.
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        carlos_headers = self._headers("carlos")
        patricia_headers = self._headers("patricia")  # faz o papel de "maria" do enunciado
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0016")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=patricia_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        # patricia (maria) entra primeiro: fica participante.
        intro = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Abrindo a conversa da proposta.", "message_type": "MENSAGEM"},
            headers=patricia_headers,
        )
        self.assertEqual(intro.status_code, 201, intro.text)

        carlos_id = self._user_id("carlos")

        def _summary(headers):
            response = self.client.get("/api/v1/chat/unread-summary", headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        def _conversation_unread(headers):
            listing = self.client.get("/api/v1/chat/conversations", headers=headers)
            self.assertEqual(listing.status_code, 200, listing.text)
            return next(item for item in listing.json()["items"] if item["id"] == conversation_id)["unread_count"]

        mentioned = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Carlos consegue conferir o peso desta peca?", "message_type": "MENSAGEM", "mentioned_user_id": carlos_id},
            headers=joao_headers,
        )
        self.assertEqual(mentioned.status_code, 201, mentioned.text)
        mentioned_message_id = mentioned.json()["id"]

        # carlos: unread da conversa = 2 (a intro da patricia + a mencao de joao,
        # nenhuma das duas lida ainda) — mas o sino so conta a mencao (+1, nunca +2).
        self.assertEqual(_conversation_unread(carlos_headers), 2)
        carlos_summary = _summary(carlos_headers)
        self.assertEqual(carlos_summary["total_unread"], 2)
        self.assertEqual(carlos_summary["notification_unread_count"], 1)

        # patricia (participante, nao mencionada): tambem +1/+1/+1, mas tipo MENSAGEM.
        self.assertEqual(_conversation_unread(patricia_headers), 1)
        patricia_summary = _summary(patricia_headers)
        self.assertEqual(patricia_summary["total_unread"], 1)
        self.assertEqual(patricia_summary["notification_unread_count"], 1)

        # carlos visualiza a mensagem (mark-read): os 3 numeros dele caem a 0.
        marked = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/read",
            json={"last_read_message_id": mentioned_message_id},
            headers=carlos_headers,
        )
        self.assertEqual(marked.status_code, 200, marked.text)
        self.assertEqual(_conversation_unread(carlos_headers), 0)
        carlos_summary_after = _summary(carlos_headers)
        self.assertEqual(carlos_summary_after["total_unread"], 0)
        self.assertEqual(carlos_summary_after["notification_unread_count"], 0)

        # patricia ainda nao abriu: continua com os 3 numeros em 1.
        self.assertEqual(_conversation_unread(patricia_headers), 1)
        patricia_summary_after = _summary(patricia_headers)
        self.assertEqual(patricia_summary_after["total_unread"], 1)
        self.assertEqual(patricia_summary_after["notification_unread_count"], 1)

        # mensagem nova mencionando carlos, chegando depois de um mark-read com
        # cursor antigo — nao pode ser marcada por acidente (race condition).
        second_mention = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Carlos mais um item pra revisar.", "message_type": "MENSAGEM", "mentioned_user_id": carlos_id},
            headers=joao_headers,
        )
        self.assertEqual(second_mention.status_code, 201, second_mention.text)

        stale_mark = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/read",
            json={"last_read_message_id": mentioned_message_id},
            headers=carlos_headers,
        )
        self.assertEqual(stale_mark.status_code, 200, stale_mark.text)
        self.assertEqual(_conversation_unread(carlos_headers), 1)
        carlos_summary_race = _summary(carlos_headers)
        self.assertEqual(carlos_summary_race["total_unread"], 1)
        self.assertEqual(carlos_summary_race["notification_unread_count"], 1)

    def test_answer_question_rejected_for_non_assignee_allowed_for_admin(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        carlos_headers = self._headers("carlos")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0017")
        patricia_id = self._user_id("patricia")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        question = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Patricia confirma o peso?", "message_type": "PERGUNTA", "mentioned_user_id": patricia_id},
            headers=joao_headers,
        )
        self.assertEqual(question.status_code, 201, question.text)
        question_id = question.json()["id"]

        # carlos nao e o responsavel: nao pode responder no lugar de patricia.
        denied = self.client.post(
            f"/api/v1/chat/messages/{question_id}/answer", json={"body": "Tentativa indevida"}, headers=carlos_headers
        )
        self.assertEqual(denied.status_code, 403, denied.text)

        # patricia (responsavel de verdade) responde normalmente.
        answered = self.client.post(
            f"/api/v1/chat/messages/{question_id}/answer", json={"body": "Confirmado."}, headers=patricia_headers
        )
        self.assertEqual(answered.status_code, 201, answered.text)

        # admin (perfil autorizado) tambem pode responder no lugar do responsavel.
        second_question = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Patricia confirma outro item?", "message_type": "PERGUNTA", "mentioned_user_id": patricia_id},
            headers=joao_headers,
        )
        self.assertEqual(second_question.status_code, 201, second_question.text)
        second_question_id = second_question.json()["id"]
        admin_answer = self.client.post(
            f"/api/v1/chat/messages/{second_question_id}/answer", json={"body": "Confirmado pelo admin."}, headers=admin_headers
        )
        self.assertEqual(admin_answer.status_code, 201, admin_answer.text)

    def test_answer_and_cancel_race_is_atomic(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0018")
        patricia_id = self._user_id("patricia")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        question = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Patricia confirma o peso?", "message_type": "PERGUNTA", "mentioned_user_id": patricia_id},
            headers=joao_headers,
        )
        self.assertEqual(question.status_code, 201, question.text)
        question_id = question.json()["id"]

        async def _race():
            session_factory = get_sessionmaker()
            async with session_factory() as answer_session, session_factory() as cancel_session:
                patricia_row = (await answer_session.execute(select(User).where(User.username == "patricia"))).scalars().first()
                joao_row = (await cancel_session.execute(select(User).where(User.username == "joao"))).scalars().first()
                return await asyncio.gather(
                    chat_service.answer_question(answer_session, question_id, patricia_row, "Respondendo"),
                    chat_service.cancel_question(cancel_session, question_id, joao_row, "Cancelando"),
                    return_exceptions=True,
                )

        results = asyncio.run(_race())
        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]
        # exatamente uma transicao concorrente pode vencer — a outra tem que
        # falhar com um erro de conflito limpo, nunca as duas passarem
        # silenciosamente (o que corromperia o estado).
        self.assertEqual(len(successes), 1, f"esperado exatamente 1 sucesso entre respostas concorrentes, obtido: {results}")
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], ApiError)
        self.assertEqual(failures[0].code, error_codes.CHAT_QUESTION_ALREADY_ANSWERED)

        async def _final_status():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                row = await session.get(ChatMessage, question_id)
                return row.question_status

        final_status = asyncio.run(_final_status())
        self.assertIn(final_status, ("RESPONDIDA", "CANCELADA"))

    def test_pergunta_read_clears_notification_but_keeps_pending_open(self):
        # patricia (nao carlos) e a responsavel: PERGUNTA exige que o
        # responsavel tenha CHAT_SEND (precisa poder responder), e carlos so
        # tem CHAT_VIEW (role chat_view_only) — post_message ja rejeita isso.
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0019")
        patricia_id = self._user_id("patricia")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        question = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Patricia confirme o peso do item 550.", "message_type": "PERGUNTA", "mentioned_user_id": patricia_id},
            headers=joao_headers,
        )
        self.assertEqual(question.status_code, 201, question.text)
        question_id = question.json()["id"]
        self.assertEqual(question.json()["question_status"], "AGUARDANDO_RESPOSTA")

        def _summary():
            response = self.client.get("/api/v1/chat/unread-summary", headers=patricia_headers)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        def _conversation_unread():
            listing = self.client.get("/api/v1/chat/conversations", headers=patricia_headers)
            self.assertEqual(listing.status_code, 200, listing.text)
            return next(item for item in listing.json()["items"] if item["id"] == conversation_id)["unread_count"]

        async def _notification_rows_for_message(msg_id):
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                rows = (
                    await session.execute(
                        select(ChatNotification).where(ChatNotification.user_id == patricia_id, ChatNotification.message_id == msg_id)
                    )
                ).scalars().all()
                return rows

        # ESTADO INICIAL: mensagem nao lida, notificacao nao lida, pendencia aberta.
        before = _summary()
        self.assertEqual(_conversation_unread(), 1)
        self.assertEqual(before["total_unread"], 1)
        self.assertEqual(before["notification_unread_count"], 1)
        self.assertEqual(before["pending_questions"], 1)

        notification_rows = asyncio.run(_notification_rows_for_message(question_id))
        # uma unica notificacao pra esta mensagem/destinatario — nunca
        # PERGUNTA_ATRIBUIDA + MENSAGEM pelo mesmo evento.
        self.assertEqual(len(notification_rows), 1)
        self.assertEqual(notification_rows[0].notification_type, "PERGUNTA_ATRIBUIDA")
        self.assertIsNone(notification_rows[0].read_at)

        # patricia visualiza a mensagem (mark-read).
        marked = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/read",
            json={"last_read_message_id": question_id},
            headers=patricia_headers,
        )
        self.assertEqual(marked.status_code, 200, marked.text)

        # DEPOIS DE LER: mensagem lida, notificacao lida, MAS a pendencia
        # continua aberta — ler nao resolve (principio central da Etapa 5).
        after_read = _summary()
        self.assertEqual(_conversation_unread(), 0)
        self.assertEqual(after_read["total_unread"], 0)
        self.assertEqual(after_read["notification_unread_count"], 0)
        self.assertEqual(after_read["pending_questions"], 1)

        notification_rows_after = asyncio.run(_notification_rows_for_message(question_id))
        self.assertIsNotNone(notification_rows_after[0].read_at)

        question_after_read = self.client.get(f"/api/v1/chat/conversations/{conversation_id}/messages", headers=patricia_headers)
        entry = next(item for item in question_after_read.json()["items"] if item["id"] == question_id)
        self.assertEqual(entry["question_status"], "AGUARDANDO_RESPOSTA")

        # patricia resolve.
        answered = self.client.post(
            f"/api/v1/chat/messages/{question_id}/answer", json={"body": "Peso confirmado: 550kg."}, headers=patricia_headers
        )
        self.assertEqual(answered.status_code, 201, answered.text)

        after_resolve = _summary()
        self.assertEqual(after_resolve["pending_questions"], 0)

        # responder de novo e rejeitado — idempotente, sem duplicar nada.
        already_answered = self.client.post(
            f"/api/v1/chat/messages/{question_id}/answer", json={"body": "De novo"}, headers=patricia_headers
        )
        self.assertEqual(already_answered.status_code, 409, already_answered.text)
        self.assertEqual(already_answered.json()["error"]["code"], "CHAT_QUESTION_ALREADY_ANSWERED")
        self.assertEqual(_summary()["pending_questions"], 0)

    def test_pending_questions_are_independent_per_user(self):
        # os dois responsaveis precisam ter CHAT_SEND (podem responder Pergunta)
        # — admin (superuser) e patricia (role chat_user) atendem; carlos
        # (chat_view_only) nao poderia ser responsavel de uma Pergunta.
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0020")
        admin_id = self._user_id("admin")
        patricia_id = self._user_id("patricia")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        question_a = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Administradora confirma o item A?", "message_type": "PERGUNTA", "mentioned_user_id": admin_id},
            headers=joao_headers,
        )
        self.assertEqual(question_a.status_code, 201, question_a.text)
        question_a_id = question_a.json()["id"]

        question_b = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Patricia confirma o item B?", "message_type": "PERGUNTA", "mentioned_user_id": patricia_id},
            headers=joao_headers,
        )
        self.assertEqual(question_b.status_code, 201, question_b.text)

        def _pending(headers):
            response = self.client.get("/api/v1/chat/unread-summary", headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()["pending_questions"]

        self.assertEqual(_pending(admin_headers), 1)
        self.assertEqual(_pending(patricia_headers), 1)

        resolved = self.client.post(
            f"/api/v1/chat/messages/{question_a_id}/answer", json={"body": "Confirmado A."}, headers=admin_headers
        )
        self.assertEqual(resolved.status_code, 201, resolved.text)

        self.assertEqual(_pending(admin_headers), 0)
        self.assertEqual(_pending(patricia_headers), 1)

    def test_attention_summary_reports_messages_mentions_and_pending_independently(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        carlos_headers = self._headers("carlos")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0021")
        patricia_id = self._user_id("patricia")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=patricia_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        intro = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Abrindo a conversa.", "message_type": "MENSAGEM"},
            headers=patricia_headers,
        )
        self.assertEqual(intro.status_code, 201, intro.text)

        plain = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Alguma novidade?", "message_type": "MENSAGEM"},
            headers=joao_headers,
        )
        self.assertEqual(plain.status_code, 201, plain.text)

        mentioned = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Patricia confere isso?", "message_type": "MENSAGEM", "mentioned_user_id": patricia_id},
            headers=joao_headers,
        )
        self.assertEqual(mentioned.status_code, 201, mentioned.text)

        question = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Patricia confirma o peso?", "message_type": "PERGUNTA", "mentioned_user_id": patricia_id},
            headers=joao_headers,
        )
        self.assertEqual(question.status_code, 201, question.text)

        def _summary(headers):
            response = self.client.get("/api/v1/chat/unread-summary", headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        # 3 mensagens de joao (plain + mencao + pergunta) estao unread pra
        # patricia, mas so 1 e mencao e so 1 e pendencia — categorias
        # independentes, nao uma soma ingenua.
        patricia_summary = _summary(patricia_headers)
        self.assertEqual(patricia_summary["total_unread"], 3)
        self.assertEqual(patricia_summary["unread_mentions"], 1)
        self.assertEqual(patricia_summary["pending_questions"], 1)

        # carlos tem CHAT_VIEW (pode ver a conversa) entao total_unread conta
        # as 4 mensagens da conversa pra ele tambem (ETAPA 1/2: unread e por
        # permissao de visualizar, nao por ter participado) — mas ele nunca
        # foi mencionado nem atribuido, entao essas duas categorias mais
        # especificas ficam em zero.
        carlos_summary = _summary(carlos_headers)
        self.assertEqual(carlos_summary["total_unread"], 4)
        self.assertEqual(carlos_summary["unread_mentions"], 0)
        self.assertEqual(carlos_summary["pending_questions"], 0)

        # mesma logica pra admin (superusuario, tambem so visualiza).
        admin_summary = _summary(admin_headers)
        self.assertEqual(admin_summary["total_unread"], 4)
        self.assertEqual(admin_summary["unread_mentions"], 0)
        self.assertEqual(admin_summary["pending_questions"], 0)

    def test_attention_summary_categories_move_independently_after_actions(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0022")
        patricia_id = self._user_id("patricia")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        plain = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Mensagem comum.", "message_type": "MENSAGEM"},
            headers=joao_headers,
        )
        self.assertEqual(plain.status_code, 201, plain.text)

        mentioned = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Patricia da uma olhada?", "message_type": "MENSAGEM", "mentioned_user_id": patricia_id},
            headers=joao_headers,
        )
        self.assertEqual(mentioned.status_code, 201, mentioned.text)
        mentioned_id = mentioned.json()["id"]

        question_x = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Patricia confirma o item X?", "message_type": "PERGUNTA", "mentioned_user_id": patricia_id},
            headers=joao_headers,
        )
        self.assertEqual(question_x.status_code, 201, question_x.text)
        question_x_id = question_x.json()["id"]

        question_y = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Patricia confirma o item Y?", "message_type": "PERGUNTA", "mentioned_user_id": patricia_id},
            headers=joao_headers,
        )
        self.assertEqual(question_y.status_code, 201, question_y.text)
        question_y_id = question_y.json()["id"]

        def _summary():
            response = self.client.get("/api/v1/chat/unread-summary", headers=patricia_headers)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        before = _summary()
        self.assertEqual(before["total_unread"], 4)
        self.assertEqual(before["unread_mentions"], 1)
        self.assertEqual(before["pending_questions"], 2)

        # marca como lida so ate a mensagem de mencao (nao ate as perguntas).
        marked = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/read",
            json={"last_read_message_id": mentioned_id},
            headers=patricia_headers,
        )
        self.assertEqual(marked.status_code, 200, marked.text)

        # caso 3/4: mensagens e mencoes lidas caem; caso 5: pendencias
        # continuam intactas so por terem sido "vistas" via mark-read.
        after_read = _summary()
        self.assertEqual(after_read["total_unread"], 2)
        self.assertEqual(after_read["unread_mentions"], 0)
        self.assertEqual(after_read["pending_questions"], 2)

        # caso 6: resolver uma pendencia derruba so ela.
        answered = self.client.post(
            f"/api/v1/chat/messages/{question_x_id}/answer", json={"body": "Confirmado X."}, headers=patricia_headers
        )
        self.assertEqual(answered.status_code, 201, answered.text)
        after_answer = _summary()
        self.assertEqual(after_answer["pending_questions"], 1)

        # caso 7: cancelar (fluxo separado do resolve) tambem derruba, e a
        # pendencia cancelada nunca mais conta.
        cancelled = self.client.post(
            f"/api/v1/chat/messages/{question_y_id}/cancel", json={"reason": "Nao e mais necessario"}, headers=joao_headers
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        after_cancel = _summary()
        self.assertEqual(after_cancel["pending_questions"], 0)

    def test_attention_summary_never_mutates_state(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0023")
        patricia_id = self._user_id("patricia")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        mentioned = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Patricia confere isso?", "message_type": "MENSAGEM", "mentioned_user_id": patricia_id},
            headers=joao_headers,
        )
        self.assertEqual(mentioned.status_code, 201, mentioned.text)

        question = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Patricia confirma o peso?", "message_type": "PERGUNTA", "mentioned_user_id": patricia_id},
            headers=joao_headers,
        )
        self.assertEqual(question.status_code, 201, question.text)
        question_id = question.json()["id"]

        # chama duas vezes seguidas — sem mark-read, sem resolver nada.
        first = self.client.get("/api/v1/chat/unread-summary", headers=patricia_headers)
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.get("/api/v1/chat/unread-summary", headers=patricia_headers)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json()["total_unread"], second.json()["total_unread"])
        self.assertEqual(first.json()["unread_mentions"], second.json()["unread_mentions"])
        self.assertEqual(first.json()["pending_questions"], second.json()["pending_questions"])

        async def _state():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                patricia_row = (await session.execute(select(User).where(User.username == "patricia"))).scalars().first()
                read_rows = (
                    await session.execute(
                        select(ChatMessageRead).where(
                            ChatMessageRead.conversation_id == conversation_id, ChatMessageRead.user_id == patricia_row.id
                        )
                    )
                ).scalars().all()
                notification_rows = (
                    await session.execute(select(ChatNotification).where(ChatNotification.user_id == patricia_row.id))
                ).scalars().all()
                question_row = await session.get(ChatMessage, question_id)
                return read_rows, notification_rows, question_row.question_status

        read_rows, notification_rows, question_status = asyncio.run(_state())
        # so consultar o resumo nao pode criar cursor de leitura...
        self.assertEqual(len(read_rows), 0)
        # ...nem marcar nenhuma notificacao como lida...
        self.assertTrue(notification_rows)
        self.assertTrue(all(row.read_at is None for row in notification_rows))
        # ...nem mexer no status da pendencia.
        self.assertEqual(question_status, "AGUARDANDO_RESPOSTA")

    def test_websocket_rejects_missing_or_invalid_auth(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/api/v1/chat/ws"):
                pass

        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/api/v1/chat/ws", headers={"Authorization": "Bearer not-a-real-token"}):
                pass

        joao_headers = self._headers("joao")
        with self.client.websocket_connect("/api/v1/chat/ws", headers=joao_headers):
            pass

    def test_websocket_delivers_message_created_with_full_envelope(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0026")
        joao_id = self._user_id("joao")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=patricia_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]
        intro = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Abrindo a conversa.", "message_type": "MENSAGEM"},
            headers=patricia_headers,
        )
        self.assertEqual(intro.status_code, 201, intro.text)

        with self.client.websocket_connect("/api/v1/chat/ws", headers=patricia_headers) as ws:
            posted = self.client.post(
                f"/api/v1/chat/conversations/{conversation_id}/messages",
                json={"body": "Alguma novidade?", "message_type": "MENSAGEM"},
                headers=joao_headers,
            )
            self.assertEqual(posted.status_code, 201, posted.text)
            message_id = posted.json()["id"]

            event = ws.receive_json()

        self.assertEqual(event["version"], 1)
        self.assertIsInstance(event["event_id"], str)
        self.assertTrue(event["event_id"])
        self.assertEqual(event["type"], "message.created")
        self.assertIn("occurred_at", event)
        self.assertEqual(event["data"]["conversation_id"], conversation_id)
        self.assertEqual(event["data"]["message_id"], message_id)
        self.assertEqual(event["data"]["proposal_id"], proposal["id"])
        self.assertEqual(event["data"]["sender_user_id"], joao_id)

    def test_conversation_broadcast_targets_excludes_non_participants(self):
        # prova direta (sem depender de leitura bloqueante de socket) de que
        # o alvo do broadcast nunca inclui quem nao participou/nao foi
        # notificado — casos 7, 8, 18 do enunciado (nunca broadcast global
        # pra conversa privada).
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0025")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=patricia_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]
        intro = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Abrindo a conversa.", "message_type": "MENSAGEM"},
            headers=patricia_headers,
        )
        self.assertEqual(intro.status_code, 201, intro.text)

        joao_id = self._user_id("joao")
        patricia_id = self._user_id("patricia")
        carlos_id = self._user_id("carlos")

        async def _targets():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                conversation = await chat_service.get_conversation(session, conversation_id)
                joao_row = (await session.execute(select(User).where(User.username == "joao"))).scalars().first()
                return await chat_service._conversation_broadcast_targets(session, conversation, set(), joao_row)

        targets = asyncio.run(_targets())
        self.assertIn(patricia_id, targets)
        self.assertIn(joao_id, targets)
        self.assertNotIn(carlos_id, targets)

    def test_websocket_action_required_events(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0027")
        patricia_id = self._user_id("patricia")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        with self.client.websocket_connect("/api/v1/chat/ws", headers=patricia_headers) as ws:
            question = self.client.post(
                f"/api/v1/chat/conversations/{conversation_id}/messages",
                json={"body": "@Patricia confirma o peso?", "message_type": "PERGUNTA", "mentioned_user_id": patricia_id},
                headers=joao_headers,
            )
            self.assertEqual(question.status_code, 201, question.text)
            question_id = question.json()["id"]

            # ETAPA 10: patricia e a mencionada, entao alem de message.created
            # e action_required.created ela agora tambem recebe seu proprio
            # notification.created (evento individual, distinto do de
            # conversa) -- 3 eventos, nao 2.
            events = [ws.receive_json() for _ in range(3)]
            types_received = {event["type"] for event in events}
            self.assertEqual(types_received, {"message.created", "action_required.created", "notification.created"})
            created_event = next(event for event in events if event["type"] == "action_required.created")
            self.assertEqual(created_event["data"]["message_id"], question_id)
            self.assertEqual(created_event["data"]["assigned_to_user_id"], patricia_id)

            answered = self.client.post(
                f"/api/v1/chat/messages/{question_id}/answer", json={"body": "Confirmado."}, headers=patricia_headers
            )
            self.assertEqual(answered.status_code, 201, answered.text)

            # A resposta e de patricia -- quem e notificado (RESPOSTA) e joao,
            # que nao esta conectado neste socket, entao aqui continuam so os
            # 2 eventos de conversa (nao ha notification.created pra patricia
            # nesta etapa).
            third = ws.receive_json()
            fourth = ws.receive_json()
            types_after_answer = {third["type"], fourth["type"]}
            self.assertEqual(types_after_answer, {"message.created", "action_required.resolved"})
            resolved_event = third if third["type"] == "action_required.resolved" else fourth
            self.assertEqual(resolved_event["data"]["message_id"], question_id)

            second_question = self.client.post(
                f"/api/v1/chat/conversations/{conversation_id}/messages",
                json={"body": "@Patricia confirma outro item?", "message_type": "PERGUNTA", "mentioned_user_id": patricia_id},
                headers=joao_headers,
            )
            self.assertEqual(second_question.status_code, 201, second_question.text)
            second_question_id = second_question.json()["id"]
            # de novo: message.created + action_required.created + notification.created.
            ws.receive_json()
            ws.receive_json()
            ws.receive_json()

            cancelled = self.client.post(
                f"/api/v1/chat/messages/{second_question_id}/cancel", json={"reason": "Nao precisa mais"}, headers=joao_headers
            )
            self.assertEqual(cancelled.status_code, 200, cancelled.text)
            cancel_event = ws.receive_json()

        self.assertEqual(cancel_event["type"], "action_required.cancelled")
        self.assertEqual(cancel_event["data"]["message_id"], second_question_id)

    def test_websocket_conversation_read_syncs_same_user_connections(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0028")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=patricia_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        posted = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Mensagem para patricia ler.", "message_type": "MENSAGEM"},
            headers=joao_headers,
        )
        self.assertEqual(posted.status_code, 201, posted.text)
        message_id = posted.json()["id"]

        # PC A e PC B: duas conexoes com o token da MESMA patricia.
        with self.client.websocket_connect("/api/v1/chat/ws", headers=patricia_headers) as pc_a, self.client.websocket_connect(
            "/api/v1/chat/ws", headers=patricia_headers
        ) as pc_b:
            marked = self.client.post(
                f"/api/v1/chat/conversations/{conversation_id}/read",
                json={"last_read_message_id": message_id},
                headers=patricia_headers,
            )
            self.assertEqual(marked.status_code, 200, marked.text)

            event_a = pc_a.receive_json()
            event_b = pc_b.receive_json()

        for event in (event_a, event_b):
            self.assertEqual(event["type"], "conversation.read")
            self.assertEqual(event["data"]["conversation_id"], conversation_id)
            self.assertEqual(event["data"]["last_read_message_id"], message_id)

    def test_websocket_connection_manager_registers_and_cleans_up_dead_sockets(self):
        from api.app.modules.chat.ws_manager import ChatConnectionManager

        class _FakeWebSocket:
            def __init__(self, *, fail: bool = False):
                self.fail = fail
                self.sent: list[dict] = []

            async def send_json(self, payload):
                if self.fail:
                    raise RuntimeError("conexao morta simulada")
                self.sent.append(payload)

        async def _run():
            mgr = ChatConnectionManager()
            ws_a = _FakeWebSocket()
            ws_b = _FakeWebSocket()
            mgr.register(1, ws_a)
            mgr.register(1, ws_b)
            step1 = mgr.online_user_ids()

            mgr.unregister(1, ws_a)
            step2 = mgr.online_user_ids()

            mgr.unregister(1, ws_b)
            step3 = mgr.online_user_ids()

            ws_ok = _FakeWebSocket()
            ws_dead = _FakeWebSocket(fail=True)
            mgr.register(2, ws_ok)
            mgr.register(2, ws_dead)
            await mgr.broadcast({2}, {"type": "x"})
            step4 = mgr.online_user_ids()
            return step1, step2, step3, step4, ws_ok.sent

        step1, step2, step3, step4, ok_sent = asyncio.run(_run())
        # duas conexoes do mesmo usuario: as duas contam (caso 5).
        self.assertEqual(step1, {1})
        # desconectar uma nao remove a outra (caso 4).
        self.assertEqual(step2, {1})
        # desconectar a ultima remove o usuario do registro.
        self.assertEqual(step3, set())
        # broadcast pra um socket que falha ao enviar remove ele sozinho,
        # sem impedir a entrega pro socket saudavel (caso 14).
        self.assertEqual(ok_sent, [{"type": "x"}])
        self.assertEqual(step4, {2})

    def test_websocket_event_envelope_has_unique_ids_and_version(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-CHAT-0029")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=patricia_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]
        intro = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Abrindo a conversa.", "message_type": "MENSAGEM"},
            headers=patricia_headers,
        )
        self.assertEqual(intro.status_code, 201, intro.text)

        with self.client.websocket_connect("/api/v1/chat/ws", headers=patricia_headers) as ws:
            for body in ["Primeira", "Segunda"]:
                posted = self.client.post(
                    f"/api/v1/chat/conversations/{conversation_id}/messages",
                    json={"body": body, "message_type": "MENSAGEM"},
                    headers=joao_headers,
                )
                self.assertEqual(posted.status_code, 201, posted.text)

            # ETAPA 10: patricia e participante anterior, entao cada mensagem
            # de joao agora gera 2 eventos pra ela (message.created +
            # notification.created) -- 4 no total pras 2 mensagens.
            events = [ws.receive_json() for _ in range(4)]

        for event in events:
            self.assertEqual(event["version"], 1)
        message_events = [event for event in events if event["type"] == "message.created"]
        self.assertEqual(len(message_events), 2)
        self.assertNotEqual(message_events[0]["event_id"], message_events[1]["event_id"])
        notification_events = [event for event in events if event["type"] == "notification.created"]
        self.assertEqual(len(notification_events), 2)
        # todos os event_id do lote inteiro sao unicos entre si.
        self.assertEqual(len({event["event_id"] for event in events}), 4)

    # ETAPA 8 — sincronizacao no login/reconexao. A maior parte da mecanica
    # unitaria (mark-read derruba unread, cancelar/resolver derruba pending,
    # mencao conta separado, resumo e read-only e idempotente, conversa
    # finalizada sem CHAT_VIEW_FINALIZED some do total) ja esta coberta por
    # testes de etapas anteriores neste mesmo arquivo
    # (test_global_unread_excludes_finalized_conversation_without_permission,
    # test_attention_summary_never_mutates_state, entre outros). O que falta
    # e provar o CENARIO COMPOSTO — todas essas mecanicas juntas, como
    # aconteceriam de verdade num periodo offline — e que o estado de
    # leitura persiste no servidor, nao numa sessao/token especifico.

    def test_session_sync_snapshot_reflects_full_offline_weekend_scenario(self):
        """TESTE CRITICO da ETAPA 8 (fim de semana offline): joao fica
        offline; enquanto isso, chegam mensagens de dois remetentes em duas
        conversas, mencoes, pendencias novas, uma pendencia e cancelada,
        e uma pendencia PRE-EXISTENTE e resolvida por ele mesmo "em outro
        dispositivo" (outro login). O snapshot que ele busca ao "voltar"
        precisa refletir o resultado final oficial — nao um numero
        intermediario, nunca duplicado, nunca faltando nada."""
        admin_headers = self._headers("admin")
        patricia_headers = self._headers("patricia")
        joao_id = self._user_id("joao")

        proposal_a = self._create_proposal(admin_headers, "CP-ETAPA8-0001")
        proposal_b = self._create_proposal(admin_headers, "CP-ETAPA8-0002")

        timeline_a = self.client.get(f"/api/v1/chat/proposals/{proposal_a['id']}/timeline", headers=admin_headers)
        self.assertEqual(timeline_a.status_code, 200, timeline_a.text)
        conversation_a = timeline_a.json()["conversation_id"]
        timeline_b = self.client.get(f"/api/v1/chat/proposals/{proposal_b['id']}/timeline", headers=patricia_headers)
        self.assertEqual(timeline_b.status_code, 200, timeline_b.text)
        conversation_b = timeline_b.json()["conversation_id"]

        # Pendencia PRE-EXISTENTE, criada antes do periodo offline comecar.
        pre_existing = self.client.post(
            f"/api/v1/chat/conversations/{conversation_a}/messages",
            json={"body": "Pre-existente: confirma o lote antes de sexta?", "message_type": "PERGUNTA", "mentioned_user_id": joao_id},
            headers=admin_headers,
        )
        self.assertEqual(pre_existing.status_code, 201, pre_existing.text)
        pre_existing_id = pre_existing.json()["id"]

        # --- periodo offline: joao nao chama nenhum endpoint aqui ---

        for _ in range(2):
            plain = self.client.post(
                f"/api/v1/chat/conversations/{conversation_a}/messages",
                json={"body": "Mensagem comum enquanto Joao estava offline.", "message_type": "MENSAGEM"},
                headers=admin_headers,
            )
            self.assertEqual(plain.status_code, 201, plain.text)

        mention_a = self.client.post(
            f"/api/v1/chat/conversations/{conversation_a}/messages",
            json={"body": "@Joao confere isso quando voltar.", "message_type": "MENSAGEM", "mentioned_user_id": joao_id},
            headers=patricia_headers,
        )
        self.assertEqual(mention_a.status_code, 201, mention_a.text)

        question_open = self.client.post(
            f"/api/v1/chat/conversations/{conversation_a}/messages",
            json={"body": "Nova pendencia: revisar peso do item 3.", "message_type": "PERGUNTA", "mentioned_user_id": joao_id},
            headers=admin_headers,
        )
        self.assertEqual(question_open.status_code, 201, question_open.text)

        question_to_cancel = self.client.post(
            f"/api/v1/chat/conversations/{conversation_a}/messages",
            json={"body": "Pendencia que sera cancelada.", "message_type": "PERGUNTA", "mentioned_user_id": joao_id},
            headers=admin_headers,
        )
        self.assertEqual(question_to_cancel.status_code, 201, question_to_cancel.text)
        question_to_cancel_id = question_to_cancel.json()["id"]
        cancelled = self.client.post(
            f"/api/v1/chat/messages/{question_to_cancel_id}/cancel",
            json={"reason": "Nao e mais necessario."},
            headers=admin_headers,
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)

        # Joao resolve a pendencia PRE-EXISTENTE "em outro dispositivo": um
        # login independente (novo token), nao a mesma sessao que vai
        # consultar o snapshot no final.
        joao_pc_a = self._headers("joao")
        answered = self.client.post(
            f"/api/v1/chat/messages/{pre_existing_id}/answer",
            json={"body": "Confirmado, lote ok."},
            headers=joao_pc_a,
        )
        self.assertEqual(answered.status_code, 201, answered.text)

        mention_b = self.client.post(
            f"/api/v1/chat/conversations/{conversation_b}/messages",
            json={"body": "@Joao outro item pra revisar na CP-ETAPA8-0002.", "message_type": "MENSAGEM", "mentioned_user_id": joao_id},
            headers=patricia_headers,
        )
        self.assertEqual(mention_b.status_code, 201, mention_b.text)
        plain_b = self.client.post(
            f"/api/v1/chat/conversations/{conversation_b}/messages",
            json={"body": "Mais uma mensagem na CP-ETAPA8-0002.", "message_type": "MENSAGEM"},
            headers=patricia_headers,
        )
        self.assertEqual(plain_b.status_code, 201, plain_b.text)

        # --- joao "volta": login novo (PC B), consulta o snapshot oficial ---
        joao_pc_b = self._headers("joao")
        summary = self.client.get("/api/v1/chat/unread-summary", headers=joao_pc_b)
        self.assertEqual(summary.status_code, 200, summary.text)
        body = summary.json()

        # Conversa A: pre-existente(1) + 2 mensagens comuns + mencao(1) +
        # pendencia aberta(1) + pendencia cancelada(1, ainda e uma mensagem)
        # = 6. A propria resposta de Joao a pre-existente NAO conta (e dele).
        # Conversa B: mencao(1) + mensagem comum(1) = 2.
        by_conversation = {item["conversation_id"]: item["unread_count"] for item in body["conversations"]}
        self.assertEqual(by_conversation.get(conversation_a), 6)
        self.assertEqual(by_conversation.get(conversation_b), 2)
        self.assertEqual(body["total_unread"], 8)

        # 1 mencao em cada conversa = 2, nunca as mensagens comuns contadas ali.
        self.assertEqual(body["unread_mentions"], 2)

        # Pendencias: pre-existente respondida (nao conta) + nova cancelada
        # (nao conta) + nova aberta (conta) = exatamente 1, nunca 3, nunca 0.
        self.assertEqual(body["pending_questions"], 1)

        self.assertIsInstance(body.get("server_time"), str)
        self.assertTrue(body["server_time"])

    def test_session_sync_snapshot_read_state_persists_across_new_login_session(self):
        """TESTE CRITICO da ETAPA 8 (leitura em outro dispositivo): o cursor
        de leitura gravado por uma sessao (um login/token) precisa ser
        visto por uma sessao completamente nova (outro login/token) do
        mesmo usuario — a fonte e o Postgres, nunca o token/sessao."""
        admin_headers = self._headers("admin")
        joao_pc_a = self._headers("joao")
        proposal = self._create_proposal(admin_headers, "CP-ETAPA8-0003")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_pc_a)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        last_message_id = None
        for _ in range(3):
            posted = self.client.post(
                f"/api/v1/chat/conversations/{conversation_id}/messages",
                json={"body": "Mensagem para Joao ler no PC A.", "message_type": "MENSAGEM"},
                headers=admin_headers,
            )
            self.assertEqual(posted.status_code, 201, posted.text)
            last_message_id = posted.json()["id"]

        before = self.client.get("/api/v1/chat/unread-summary", headers=joao_pc_a)
        self.assertEqual(before.status_code, 200, before.text)
        by_conversation_before = {item["conversation_id"]: item["unread_count"] for item in before.json()["conversations"]}
        self.assertEqual(by_conversation_before.get(conversation_id), 3)

        marked = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/read",
            json={"last_read_message_id": last_message_id},
            headers=joao_pc_a,
        )
        self.assertEqual(marked.status_code, 200, marked.text)

        # PC B nunca chamou /read — e um login novo, token novo, sem
        # nenhum estado local. Se o cursor de leitura estivesse preso a
        # sessao/token de PC A, PC B veria as 3 mensagens como nao lidas de
        # novo. Ele tem que ver o estado ja atualizado, porque o cursor vive
        # em ChatMessageRead (Postgres), nao em nada por sessao.
        joao_pc_b = self._headers("joao")
        after = self.client.get("/api/v1/chat/unread-summary", headers=joao_pc_b)
        self.assertEqual(after.status_code, 200, after.text)
        by_conversation_after = {item["conversation_id"]: item["unread_count"] for item in after.json()["conversations"]}
        self.assertNotIn(conversation_id, by_conversation_after)
        self.assertEqual(after.json()["total_unread"], 0)

    # ETAPA 9 — consolidacao do last_read_message_id como cursor oficial.
    # A maior parte da mecanica unitaria (idempotencia, cursor nunca
    # regride sequencialmente, autorizacao, notification sync, mencao,
    # ActionRequired independente, session sync) ja esta coberta por testes
    # de etapas anteriores neste mesmo arquivo
    # (test_mark_read_is_idempotent_and_cursor_never_regresses,
    # test_mark_read_rejected_without_finalized_permission,
    # test_mark_read_syncs_message_notifications_respecting_cursor_and_race,
    # test_mark_read_syncs_mention_and_keeps_chat_bell_counts_consistent,
    # entre outros). O que faltava genuinamente: (1) provar que o endpoint
    # devolve o estado REALMENTE persistido em vez de ecoar o request, e
    # (2) provar convergencia sob CONCORRENCIA REAL (nao so chamadas
    # sequenciais em ordem controlada) -- o antigo SELECT+compara-em-Python+
    # UPDATE permitia um cursor menor sobrescrever um maior sob colisao real.

    def test_mark_read_response_reports_persisted_state_not_raw_request(self):
        """A resposta do mark-read nao pode 'mentir': se o request chega
        com um cursor mais antigo que o ja persistido, o corpo devolvido
        tem que trazer o valor REAL salvo, nao o que foi pedido."""
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        proposal = self._create_proposal(admin_headers, "CP-ETAPA9-0002")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        message_ids = []
        for body in ["Um", "Dois", "Tres"]:
            posted = self.client.post(
                f"/api/v1/chat/conversations/{conversation_id}/messages",
                json={"body": body, "message_type": "MENSAGEM"},
                headers=admin_headers,
            )
            self.assertEqual(posted.status_code, 201, posted.text)
            message_ids.append(posted.json()["id"])

        # primeira leitura: nao existe read-state ainda -- o corpo devolvido
        # bate exatamente com o que foi pedido.
        first = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/read",
            json={"last_read_message_id": message_ids[-1]},
            headers=joao_headers,
        )
        self.assertEqual(first.status_code, 200, first.text)
        first_body = first.json()
        self.assertEqual(first_body["conversation_id"], conversation_id)
        self.assertEqual(first_body["last_read_message_id"], message_ids[-1])
        self.assertTrue(first_body["last_read_at"])

        # request atrasado/mais antigo: o SERVIDOR ja tem um cursor maior.
        # A resposta tem que contar a verdade (o maior), nao o valor pedido.
        stale = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/read",
            json={"last_read_message_id": message_ids[0]},
            headers=joao_headers,
        )
        self.assertEqual(stale.status_code, 200, stale.text)
        stale_body = stale.json()
        self.assertEqual(stale_body["last_read_message_id"], message_ids[-1])
        self.assertNotEqual(stale_body["last_read_message_id"], message_ids[0])

    def test_mark_read_concurrent_requests_converge_to_highest_cursor(self):
        """TESTE CRITICO da ETAPA 9 (concorrencia): duas chamadas de
        mark-read pro MESMO usuario/conversa, executando de verdade em
        paralelo (duas AsyncSession/transacoes Postgres independentes,
        via asyncio.gather -- testado primeiro com threads batendo no
        TestClient, mas o TestClient serializa tudo num unico event loop
        por baixo dos panos, entao nao gerava colisao real; chamar o
        service diretamente com duas sessoes e o jeito que realmente
        exercita a colisao), tem que convergir pro MAIOR cursor valido --
        nunca pro que commitou por ultimo. Prova que o upsert atomico
        (ON CONFLICT ... DO UPDATE ... WHERE) protege de verdade sob
        colisao real, nao so sob chamadas sequenciais."""
        admin_headers = self._headers("admin")
        joao_id = self._user_id("joao")
        proposal = self._create_proposal(admin_headers, "CP-ETAPA9-0003")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=admin_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        message_ids = []
        for i in range(6):
            posted = self.client.post(
                f"/api/v1/chat/conversations/{conversation_id}/messages",
                json={"body": f"Mensagem {i}", "message_type": "MENSAGEM"},
                headers=admin_headers,
            )
            self.assertEqual(posted.status_code, 201, posted.text)
            message_ids.append(posted.json()["id"])

        lower_id = message_ids[2]
        higher_id = message_ids[5]

        async def _race():
            session_factory = get_sessionmaker()
            barrier = asyncio.Barrier(2)

            async def _call(session, actor, last_read_message_id):
                # sincroniza as duas corrotinas pra chegarem o mais proximo
                # possivel uma da outra no exato ponto de disputar o
                # upsert -- sem isso, uma tende a terminar (com commit e
                # tudo) antes da outra sequer comecar, o que nao exercitaria
                # a colisao de verdade.
                await barrier.wait()
                return await chat_service.mark_read(session, conversation_id, actor, last_read_message_id)

            async with session_factory() as session_a, session_factory() as session_b:
                joao_a = await auth_repository.get_user_by_id(session_a, joao_id)
                joao_b = await auth_repository.get_user_by_id(session_b, joao_id)
                # Nao existe read-state ainda para esta conversa: as duas
                # transacoes disputam o mesmo INSERT ... ON CONFLICT pela
                # primeira vez (CASO CONCORRENTE 3), a colisao mais dificil.
                return await asyncio.gather(
                    _call(session_a, joao_a, higher_id),
                    _call(session_b, joao_b, lower_id),
                )

        result_higher, result_lower = asyncio.run(_race())

        # A chamada com o cursor MAIOR sempre tem que ver o proprio valor
        # persistido, veio antes ou depois da outra: ou ela criou/avancou o
        # cursor pra higher_id diretamente, ou chegou depois de "lower" e
        # o WHERE do upsert rejeitou o menor, mantendo/confirmando higher_id.
        self.assertEqual(result_higher.last_read_message_id, higher_id)
        # A chamada com o cursor MENOR pode legitimamente ver o proprio
        # valor (se ela comitou primeiro, antes de "higher" sequer rodar --
        # nesse instante 3 ERA a verdade) ou ja ver higher_id (se rodou
        # depois). O que importa e o estado FINAL apos as duas terminarem,
        # checado abaixo direto no banco -- nao qual delas venceu a corrida.
        self.assertIn(result_lower.last_read_message_id, {lower_id, higher_id})

        async def _read_state_rows():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                return (
                    await session.execute(
                        select(ChatMessageRead).where(
                            ChatMessageRead.conversation_id == conversation_id, ChatMessageRead.user_id == joao_id
                        )
                    )
                ).scalars().all()

        rows = asyncio.run(_read_state_rows())
        # exatamente UM registro por user+conversa -- a colisao de INSERT
        # concorrente nao pode ter gerado linha duplicada nem erro de
        # unique constraint.
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].last_read_message_id, higher_id)

    def test_mark_read_cursor_advances_over_own_message_but_excludes_it_from_unread(self):
        """Mensagem propria nunca conta como unread para o autor, mas o
        cursor pode avancar por cima dela normalmente -- ela ainda faz
        parte da sequencia oficial da conversa."""
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        proposal = self._create_proposal(admin_headers, "CP-ETAPA9-0004")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        first = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "De outra pessoa.", "message_type": "MENSAGEM"},
            headers=admin_headers,
        )
        self.assertEqual(first.status_code, 201, first.text)

        own = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Mensagem do proprio Joao.", "message_type": "MENSAGEM"},
            headers=joao_headers,
        )
        self.assertEqual(own.status_code, 201, own.text)
        own_id = own.json()["id"]

        # Joao marca ate a PROPRIA mensagem -- o cursor tem que avancar
        # normalmente, mesmo apontando pra uma mensagem que ele mesmo escreveu.
        marked = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/read",
            json={"last_read_message_id": own_id},
            headers=joao_headers,
        )
        self.assertEqual(marked.status_code, 200, marked.text)
        self.assertEqual(marked.json()["last_read_message_id"], own_id)

        # e nao havia nada unread pra ele mesmo antes disso: a mensagem
        # propria nunca teria contado.
        summary = self.client.get("/api/v1/chat/unread-summary", headers=joao_headers)
        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertEqual(summary.json()["total_unread"], 0)

    def test_mark_read_message_from_another_conversation_is_rejected(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        proposal_a = self._create_proposal(admin_headers, "CP-ETAPA9-0005")
        proposal_b = self._create_proposal(admin_headers, "CP-ETAPA9-0006")

        timeline_a = self.client.get(f"/api/v1/chat/proposals/{proposal_a['id']}/timeline", headers=admin_headers)
        self.assertEqual(timeline_a.status_code, 200, timeline_a.text)
        conversation_a = timeline_a.json()["conversation_id"]
        timeline_b = self.client.get(f"/api/v1/chat/proposals/{proposal_b['id']}/timeline", headers=admin_headers)
        self.assertEqual(timeline_b.status_code, 200, timeline_b.text)
        conversation_b = timeline_b.json()["conversation_id"]

        message_in_b = self.client.post(
            f"/api/v1/chat/conversations/{conversation_b}/messages",
            json={"body": "Mensagem da conversa B.", "message_type": "MENSAGEM"},
            headers=admin_headers,
        )
        self.assertEqual(message_in_b.status_code, 201, message_in_b.text)
        message_in_b_id = message_in_b.json()["id"]

        # Joao tenta marcar a conversa A como lida usando o id de uma
        # mensagem que pertence a conversa B -- tem que ser rejeitado.
        rejected = self.client.post(
            f"/api/v1/chat/conversations/{conversation_a}/read",
            json={"last_read_message_id": message_in_b_id},
            headers=joao_headers,
        )
        self.assertEqual(rejected.status_code, 404, rejected.text)

        nonexistent = self.client.post(
            f"/api/v1/chat/conversations/{conversation_a}/read",
            json={"last_read_message_id": 9_999_999},
            headers=joao_headers,
        )
        self.assertEqual(nonexistent.status_code, 404, nonexistent.text)

    # ETAPA 10 — Notification Center. A maior parte da mecanica unitaria de
    # geracao/tipo/dedup de Notification ja esta coberta por etapas
    # anteriores (ver test_mark_notification_read_only_by_owner e os testes
    # de mencao/pergunta). O que faltava genuinamente: filtro unread no
    # backend, paginacao real (total/has_more), mark-all sem teste nenhum,
    # a garantia explicita de "nunca apaga ao ler", o vazamento de
    # conversa finalizada na listagem, e os 3 eventos realtime novos.

    def test_list_notifications_unread_filter_and_all_filter(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-ETAPA10-0001")
        patricia_id = self._user_id("patricia")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        first = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Patricia primeira mencao.", "message_type": "MENSAGEM", "mentioned_user_id": patricia_id},
            headers=joao_headers,
        )
        self.assertEqual(first.status_code, 201, first.text)
        second = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Patricia segunda mencao.", "message_type": "MENSAGEM", "mentioned_user_id": patricia_id},
            headers=joao_headers,
        )
        self.assertEqual(second.status_code, 201, second.text)

        all_before = self.client.get("/api/v1/chat/notifications", headers=patricia_headers)
        self.assertEqual(all_before.status_code, 200, all_before.text)
        self.assertEqual(len(all_before.json()["items"]), 2)

        first_notification_id = next(
            item["id"] for item in all_before.json()["items"] if item["message_id"] == first.json()["id"]
        )
        marked = self.client.post(f"/api/v1/chat/notifications/{first_notification_id}/read", headers=patricia_headers)
        self.assertEqual(marked.status_code, 204, marked.text)

        unread = self.client.get("/api/v1/chat/notifications?status=unread", headers=patricia_headers)
        self.assertEqual(unread.status_code, 200, unread.text)
        unread_ids = [item["id"] for item in unread.json()["items"]]
        self.assertEqual(len(unread_ids), 1)
        self.assertNotIn(first_notification_id, unread_ids)

        # "ALL" continua trazendo as duas -- a que ja foi lida nao some.
        all_after = self.client.get("/api/v1/chat/notifications", headers=patricia_headers)
        self.assertEqual(all_after.status_code, 200, all_after.text)
        self.assertEqual(len(all_after.json()["items"]), 2)

    def test_list_notifications_pagination_total_and_has_more(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-ETAPA10-0002")
        joao_id = self._user_id("joao")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=patricia_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        for i in range(5):
            posted = self.client.post(
                f"/api/v1/chat/conversations/{conversation_id}/messages",
                json={"body": f"@Joao mencao {i}.", "message_type": "MENSAGEM", "mentioned_user_id": joao_id},
                headers=patricia_headers,
            )
            self.assertEqual(posted.status_code, 201, posted.text)

        first_page = self.client.get("/api/v1/chat/notifications?limit=2&offset=0", headers=joao_headers)
        self.assertEqual(first_page.status_code, 200, first_page.text)
        first_body = first_page.json()
        self.assertEqual(len(first_body["items"]), 2)
        self.assertEqual(first_body["total"], 5)
        self.assertTrue(first_body["has_more"])

        last_page = self.client.get("/api/v1/chat/notifications?limit=2&offset=4", headers=joao_headers)
        self.assertEqual(last_page.status_code, 200, last_page.text)
        last_body = last_page.json()
        self.assertEqual(len(last_body["items"]), 1)
        self.assertEqual(last_body["total"], 5)
        self.assertFalse(last_body["has_more"])

        # paginas nao se sobrepoem: os ids da primeira pagina nao aparecem
        # de novo mais adiante.
        first_ids = {item["id"] for item in first_body["items"]}
        last_ids = {item["id"] for item in last_body["items"]}
        self.assertEqual(first_ids & last_ids, set())

    def test_notification_stays_in_history_after_being_read(self):
        """TESTE CRITICO da ETAPA 10 (nao deletar): marcar uma Notification
        como lida nunca remove o registro -- ela continua aparecendo em
        ALL, so com read_at preenchido."""
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-ETAPA10-0003")
        patricia_id = self._user_id("patricia")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        posted = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Patricia confere isso.", "message_type": "MENSAGEM", "mentioned_user_id": patricia_id},
            headers=joao_headers,
        )
        self.assertEqual(posted.status_code, 201, posted.text)

        listing = self.client.get("/api/v1/chat/notifications", headers=patricia_headers)
        notification_id = listing.json()["items"][0]["id"]
        self.assertIsNone(listing.json()["items"][0]["read_at"])

        marked = self.client.post(f"/api/v1/chat/notifications/{notification_id}/read", headers=patricia_headers)
        self.assertEqual(marked.status_code, 204, marked.text)

        after = self.client.get("/api/v1/chat/notifications", headers=patricia_headers)
        self.assertEqual(after.status_code, 200, after.text)
        item = next(item for item in after.json()["items"] if item["id"] == notification_id)
        self.assertIsNotNone(item["read_at"])

    def test_mark_all_notifications_read_is_batch_idempotent_and_scoped_to_owner(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        patricia_headers = self._headers("patricia")
        proposal = self._create_proposal(admin_headers, "CP-ETAPA10-0004")
        joao_id = self._user_id("joao")
        patricia_id = self._user_id("patricia")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=admin_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        # 3 notificacoes pra joao, 1 pra patricia -- mark-all de joao nao
        # pode tocar a de patricia.
        for i in range(3):
            posted = self.client.post(
                f"/api/v1/chat/conversations/{conversation_id}/messages",
                json={"body": f"@Joao mencao {i}.", "message_type": "MENSAGEM", "mentioned_user_id": joao_id},
                headers=admin_headers,
            )
            self.assertEqual(posted.status_code, 201, posted.text)
        pending = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "Pergunta pra Patricia.", "message_type": "PERGUNTA", "mentioned_user_id": patricia_id},
            headers=admin_headers,
        )
        self.assertEqual(pending.status_code, 201, pending.text)
        pending_question_id = pending.json()["id"]

        mark_all = self.client.post("/api/v1/chat/notifications/mark-all-read", headers=joao_headers)
        self.assertEqual(mark_all.status_code, 204, mark_all.text)

        joao_unread = self.client.get("/api/v1/chat/notifications?status=unread", headers=joao_headers)
        self.assertEqual(joao_unread.json()["items"], [])

        # patricia nao foi tocada.
        patricia_unread = self.client.get("/api/v1/chat/notifications?status=unread", headers=patricia_headers)
        self.assertEqual(len(patricia_unread.json()["items"]), 1)

        # idempotente: chamar de novo nao da erro nem muda nada.
        mark_all_again = self.client.post("/api/v1/chat/notifications/mark-all-read", headers=joao_headers)
        self.assertEqual(mark_all_again.status_code, 204, mark_all_again.text)

        # mark-all NUNCA mexe em ActionRequired (question_status) nem no
        # cursor de leitura do chat (ETAPA 9) -- so em Notification.read_at.
        async def _state():
            session_factory = get_sessionmaker()
            async with session_factory() as session:
                question = await session.get(ChatMessage, pending_question_id)
                patricia_row = (await session.execute(select(User).where(User.username == "patricia"))).scalars().first()
                read_state = (
                    await session.execute(
                        select(ChatMessageRead).where(
                            ChatMessageRead.conversation_id == conversation_id, ChatMessageRead.user_id == patricia_row.id
                        )
                    )
                ).scalars().first()
                return question.question_status, read_state

        question_status, read_state = asyncio.run(_state())
        self.assertEqual(question_status, "AGUARDANDO_RESPOSTA")
        self.assertIsNone(read_state)

    def test_list_notifications_excludes_finalized_conversation_without_permission(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        carlos_headers = self._headers("carlos")
        proposal = self._create_proposal(admin_headers, "CP-ETAPA10-0005")
        carlos_id = self._user_id("carlos")
        admin_id = self._user_id("admin")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=joao_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        # joao (autor) menciona carlos (sem CHAT_VIEW_FINALIZED) e admin
        # (superusuario) na mesma conversa -- cada um recebe sua propria
        # notificacao.
        to_carlos = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Carlos confere isso.", "message_type": "MENSAGEM", "mentioned_user_id": carlos_id},
            headers=joao_headers,
        )
        self.assertEqual(to_carlos.status_code, 201, to_carlos.text)
        to_admin = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Administradora confere tambem.", "message_type": "MENSAGEM", "mentioned_user_id": admin_id},
            headers=joao_headers,
        )
        self.assertEqual(to_admin.status_code, 201, to_admin.text)

        before = self.client.get("/api/v1/chat/notifications", headers=carlos_headers)
        self.assertEqual(before.status_code, 200, before.text)
        self.assertEqual(len(before.json()["items"]), 1)

        self._finalize_conversation(conversation_id)

        # carlos nao tem CHAT_VIEW_FINALIZED: a notificacao antiga dessa
        # conversa nao pode continuar vazando corpo de mensagem/autor numa
        # listagem que ele ainda consegue chamar.
        after = self.client.get("/api/v1/chat/notifications", headers=carlos_headers)
        self.assertEqual(after.status_code, 200, after.text)
        self.assertEqual(after.json()["items"], [])

        # admin e superuser: continua vendo a propria notificacao normalmente.
        admin_view = self.client.get("/api/v1/chat/notifications", headers=admin_headers)
        self.assertEqual(admin_view.status_code, 200, admin_view.text)
        self.assertEqual(len(admin_view.json()["items"]), 1)

    def test_websocket_notification_created_event(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        proposal = self._create_proposal(admin_headers, "CP-ETAPA10-0006")
        joao_id = self._user_id("joao")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=admin_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        with self.client.websocket_connect("/api/v1/chat/ws", headers=joao_headers) as ws:
            posted = self.client.post(
                f"/api/v1/chat/conversations/{conversation_id}/messages",
                json={"body": "@Joao confere isso.", "message_type": "MENSAGEM", "mentioned_user_id": joao_id},
                headers=admin_headers,
            )
            self.assertEqual(posted.status_code, 201, posted.text)

            events = [ws.receive_json(), ws.receive_json()]

        types = {event["type"] for event in events}
        self.assertIn("message.created", types)
        self.assertIn("notification.created", types)
        notification_event = next(event for event in events if event["type"] == "notification.created")
        self.assertEqual(notification_event["version"], 1)
        self.assertTrue(notification_event["event_id"])
        self.assertEqual(notification_event["data"]["conversation_id"], conversation_id)

    def test_websocket_notification_read_and_read_all_sync_same_user_connections(self):
        admin_headers = self._headers("admin")
        joao_headers = self._headers("joao")
        proposal = self._create_proposal(admin_headers, "CP-ETAPA10-0007")
        joao_id = self._user_id("joao")

        timeline = self.client.get(f"/api/v1/chat/proposals/{proposal['id']}/timeline", headers=admin_headers)
        self.assertEqual(timeline.status_code, 200, timeline.text)
        conversation_id = timeline.json()["conversation_id"]

        first = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Joao mencao um.", "message_type": "MENSAGEM", "mentioned_user_id": joao_id},
            headers=admin_headers,
        )
        self.assertEqual(first.status_code, 201, first.text)
        second = self.client.post(
            f"/api/v1/chat/conversations/{conversation_id}/messages",
            json={"body": "@Joao mencao dois.", "message_type": "MENSAGEM", "mentioned_user_id": joao_id},
            headers=admin_headers,
        )
        self.assertEqual(second.status_code, 201, second.text)

        listing = self.client.get("/api/v1/chat/notifications", headers=joao_headers)
        notification_id = listing.json()["items"][0]["id"]

        # PC A e PC B: duas conexoes com o token do MESMO joao.
        with self.client.websocket_connect("/api/v1/chat/ws", headers=joao_headers) as pc_a, self.client.websocket_connect(
            "/api/v1/chat/ws", headers=joao_headers
        ) as pc_b:
            marked = self.client.post(f"/api/v1/chat/notifications/{notification_id}/read", headers=joao_headers)
            self.assertEqual(marked.status_code, 204, marked.text)

            read_event_a = pc_a.receive_json()
            read_event_b = pc_b.receive_json()

        for event in (read_event_a, read_event_b):
            self.assertEqual(event["type"], "notification.read")
            self.assertEqual(event["data"]["notification_id"], notification_id)

        with self.client.websocket_connect("/api/v1/chat/ws", headers=joao_headers) as pc_a, self.client.websocket_connect(
            "/api/v1/chat/ws", headers=joao_headers
        ) as pc_b:
            mark_all = self.client.post("/api/v1/chat/notifications/mark-all-read", headers=joao_headers)
            self.assertEqual(mark_all.status_code, 204, mark_all.text)

            read_all_event_a = pc_a.receive_json()
            read_all_event_b = pc_b.receive_json()

        for event in (read_all_event_a, read_all_event_b):
            self.assertEqual(event["type"], "notification.read_all")


if __name__ == "__main__":
    unittest.main()
