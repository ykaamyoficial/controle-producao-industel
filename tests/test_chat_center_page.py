from __future__ import annotations

import time
import unittest

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.chat_center_page import ChatCenterPage


class FakeService:
    """Cobre so o que ChatCenterPage/ChatConversationPanel tocam pra abrir
    uma conversa alvo (proposal_id/conversation_id/message_id) - unico ponto
    de entrada de chat do app depois da remocao do ProposalChatDialog."""

    def __init__(self):
        self.palette = OFFICIAL_COLOR_PALETTES["claro"]
        self.palette_name = "claro"
        self.company = "Industel Teste"
        self.user = {"id": 1, "nome": "Eu", "login": "eu", "perfil": "usuario"}
        self.conversations: list[dict] = []
        self.timeline_items: list[dict] = []

    def chat_conversations_page(self, params: dict):
        status = params.get("status")
        conversation_id = params.get("conversation_id")
        rows = [row for row in self.conversations if row.get("status", "ATIVA") == status]
        if conversation_id is not None:
            rows = [row for row in rows if row.get("id") == conversation_id]
        limit = params.get("limit") or len(rows)
        return {"items": rows[:limit], "total": len(rows), "has_more": len(rows) > limit}

    def chat_mentionable_users(self):
        return []

    def get_process_dict(self, proposal_id):
        return {"proposta": "CP05280", "cliente": "ENERGY SYSTEM", "obra_site": "Obra X", "prazo_entrega": "10/10/2026", "peso": "120"}

    def current_location(self, proposal):
        return ("PRODUCAO", "Producao", "EM_PRODUCAO")

    def status_label(self, status):
        return status or "-"

    def chat_proposal_timeline(self, proposal_id, **filters):
        return {"conversation_id": 7, "items": list(self.timeline_items), "has_more": False}

    def chat_mark_read(self, conversation_id, last_id):
        pass

    def chat_mark_question_viewed(self, message_id):
        pass

    def can_admin_chat(self):
        return False


def _conversation(conversation_id, proposal_id, status="ATIVA", **extra):
    row = {
        "id": conversation_id,
        "kind": "PROPOSTA",
        "proposal_id": proposal_id,
        "proposal_number": f"CP{proposal_id}",
        "customer_name": "Cliente Teste",
        "status": status,
        "last_activity_at": "2026-08-06T14:35:00Z",
        "last_message_preview": None,
        "last_message_author": None,
        "unread_count": 0,
        "proposal_status": None,
        "proposal_area": None,
    }
    row.update(extra)
    return row


class ChatCenterPageTargetTests(unittest.TestCase):
    """Toda notificacao/"Ver mensagens"/icone de chat na linha da proposta
    agora abre ChatCenterDialog (unico ponto de entrada) com um alvo — este
    teste cobre que o alvo realmente abre a conversa certa e seleciona o
    card correspondente na lista assim que ela carrega."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._pages: list[ChatCenterPage] = []

    def tearDown(self):
        # mesmo motivo do test_notification_center_panel.py: refresh() spina
        # QThread real via start_worker, precisa terminar antes do widget
        # ser coletado ou pode segfaultar testes seguintes.
        for page in self._pages:
            for thread in page.findChildren(QThread):
                thread.quit()
                thread.wait(2000)
            self.app.processEvents()
        self._pages.clear()

    def _build_page(self, service, **target) -> ChatCenterPage:
        page = ChatCenterPage(service, **target)
        self._pages.append(page)
        return page

    def _pump(self, page: ChatCenterPage, cycles: int = 40):
        for _ in range(cycles):
            self.app.processEvents()
            time.sleep(0.003)

    def test_opening_with_proposal_id_shows_panel_immediately(self):
        service = FakeService()
        page = self._build_page(service, proposal_id=42)
        self.assertIsNotNone(page.panel)
        self.assertEqual(page.panel.proposal_id, 42)

    def test_opening_with_proposal_id_selects_matching_card_after_refresh(self):
        service = FakeService()
        service.conversations = [_conversation(1, 10), _conversation(2, 42)]
        page = self._build_page(service, proposal_id=42)
        self._pump(page)
        self.assertIsNotNone(page.selected_conversation)
        self.assertEqual(page.selected_conversation.get("proposal_id"), 42)
        self.assertIsNotNone(page.conversation_list.currentItem())

    def test_opening_with_message_id_schedules_pending_focus(self):
        service = FakeService()
        page = self._build_page(service, proposal_id=42, message_id=99)
        self.assertEqual(page.panel._pending_focus_message_id, 99)

    def test_opening_without_target_shows_empty_state(self):
        service = FakeService()
        page = self._build_page(service)
        self.assertIsNone(page.panel)


if __name__ == "__main__":
    unittest.main()
