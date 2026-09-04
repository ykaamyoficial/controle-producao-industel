from __future__ import annotations

import time
import unittest

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QFrame

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.components.notification_center_panel import NotificationCenterPanel


class FakeService:
    def __init__(self):
        self.palette = OFFICIAL_COLOR_PALETTES["claro"]
        self.notifications: list[dict] = []
        self.marked_read: list[int] = []
        self.mark_all_calls = 0
        self.call_count = 0
        self.last_status: str | None = "UNSET"
        self.last_offset: int | None = None

    def chat_notifications_page(self, *, status=None, limit=30, offset=0):
        self.call_count += 1
        self.last_status = status
        self.last_offset = offset
        page = self.notifications[offset : offset + limit]
        return {
            "items": page,
            "total": len(self.notifications),
            "has_more": offset + len(page) < len(self.notifications),
        }

    def chat_mark_notification_read(self, notification_id):
        self.marked_read.append(notification_id)

    def chat_mark_all_notifications_read(self):
        self.mark_all_calls += 1


def _notification(notification_id, notification_type="MENCAO", read_at=None, **extra):
    row = {
        "id": notification_id,
        "notification_type": notification_type,
        "priority": "atencao",
        "conversation_id": 1,
        "kind": "PROPOSTA",
        "proposal_id": 5,
        "proposal_number": "CP05237",
        "customer_name": "Cliente Teste",
        "message_id": 10 + notification_id,
        "message_body": "conteudo da notificacao",
        "question_status": None,
        "area": None,
        "author_name": "Carlos",
        "created_at": "2026-08-06T14:35:00Z",
        "read_at": read_at,
    }
    row.update(extra)
    return row


class NotificationCenterPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._panels: list[NotificationCenterPanel] = []

    def tearDown(self):
        # NotificationCenterPanel.refresh()/_load_more() spinam QThread reais
        # (start_worker, app/ui/background_worker.py) parented ao painel. Se o
        # painel for coletado (fim do teste, variavel local `panel` fora de
        # escopo) antes da QThread realmente terminar, o Qt destroi uma
        # QThread "em execucao" -- isso e undefined behavior no C++ do Qt e
        # pode segfaultar o processo inteiro, em QUALQUER teste rodando depois
        # (o crash nao aponta pro teste culpado). Mesmo padrao ja usado em
        # tests/test_background_stability.py: quit()+wait() explicito antes
        # do teste liberar o objeto.
        for panel in self._panels:
            for thread in panel.findChildren(QThread):
                thread.quit()
                thread.wait(2000)
            self.app.processEvents()
        self._panels.clear()

    def _build_panel(self, notifications, on_open_conversation=None) -> NotificationCenterPanel:
        service = FakeService()
        service.notifications = notifications
        panel = NotificationCenterPanel(service, on_open_conversation=on_open_conversation)
        self._panels.append(panel)
        self._pump_until(panel, expected_calls=1)
        return panel

    def _pump_until(self, panel: NotificationCenterPanel, expected_calls: int):
        deadline = 400
        while panel.service.call_count < expected_calls and deadline > 0:
            self.app.processEvents()
            time.sleep(0.003)
            deadline -= 1
        for _ in range(20):
            self.app.processEvents()
            time.sleep(0.002)

    def _visible_row_count(self, panel: NotificationCenterPanel) -> int:
        # ETAPA 10: agrupamento por data insere QLabel de cabecalho entre os
        # cards, entao "total de itens no layout - 1 (stretch)" nao e mais
        # igual a "quantidade de notificacoes" -- conta so os cards de
        # verdade pelo objectName ("Panel", ver _build_row), nao por
        # isinstance(_, QFrame): QLabel tambem e QFrame em Qt, entao isso
        # contaria os cabecalhos de data junto.
        count = 0
        for index in range(panel.list_layout.count()):
            widget = panel.list_layout.itemAt(index).widget()
            if isinstance(widget, QFrame) and widget.objectName() == "Panel":
                count += 1
        return count

    def test_only_unread_requested_by_default(self):
        # O painel so mostra nao lidas -- nao ha mais filtro "Todas": o
        # primeiro refresh ja manda status=unread pro backend de verdade
        # (o FakeService simula o backend filtrando, exatamente como o
        # servico real faz).
        panel = self._build_panel([_notification(1)])
        self.assertEqual(panel.service.last_status, "unread")

    def test_open_invokes_callback_and_marks_read_after(self):
        captured = {}

        def on_open(proposal_id, conversation_id, message_id):
            captured["args"] = (proposal_id, conversation_id, message_id)

        panel = self._build_panel([_notification(1)], on_open_conversation=on_open)
        notification = panel.notifications[0]
        panel._open(notification)
        self.assertEqual(captured["args"], (5, None, 11))
        self.assertIn(1, panel.service.marked_read)

    def test_mark_all_read_calls_service(self):
        panel = self._build_panel([_notification(1)])
        panel._mark_all_read()
        self._pump_until(panel, expected_calls=2)
        self.assertEqual(panel.service.mark_all_calls, 1)

    def test_pagination_load_more_appends_next_page_and_hides_button_when_exhausted(self):
        panel = self._build_panel([_notification(i) for i in range(1, 4)])
        # simula uma primeira pagina de 2 (has_more=True) via novo refresh
        # controlado pelo teste, reaproveitando o mesmo FakeService.
        panel.notifications = panel.notifications[:2]
        panel._has_more = True
        panel._render()
        self.assertTrue(hasattr(panel, "_load_more_btn"))

        panel._load_more()
        # o worker roda numa thread -- da tempo dele terminar antes de checar.
        deadline = 400
        while panel._loading_more and deadline > 0:
            self.app.processEvents()
            time.sleep(0.003)
            deadline -= 1
        self.assertEqual(len(panel.notifications), 3)
        self.assertFalse(panel._has_more)

    def test_pending_chip_reflects_question_status(self):
        panel = self._build_panel(
            [
                _notification(1, notification_type="PERGUNTA_ATRIBUIDA", question_status="AGUARDANDO_RESPOSTA"),
                _notification(2, notification_type="PERGUNTA_ATRIBUIDA", question_status="RESPONDIDA"),
                _notification(3, notification_type="PERGUNTA_ATRIBUIDA", question_status="CANCELADA"),
            ]
        )
        chip_1 = panel._build_pending_chip(panel.notifications[0])
        chip_2 = panel._build_pending_chip(panel.notifications[1])
        chip_3 = panel._build_pending_chip(panel.notifications[2])
        self.assertEqual(chip_1.text(), "Pendente")
        self.assertEqual(chip_2.text(), "Resolvida")
        self.assertEqual(chip_3.text(), "Cancelada")


if __name__ == "__main__":
    unittest.main()
