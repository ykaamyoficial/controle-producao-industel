from __future__ import annotations

import time
import unittest

from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.components.timeline_entries import TimelineDaySeparator
from app.ui.proposal_chat_dialog import ChatConversationPanel


class FakeService:
    def __init__(self):
        self.palette = OFFICIAL_COLOR_PALETTES["claro"]
        self.palette_name = "claro"
        self.company = "Industel Teste"
        self.user = {"id": 1, "nome": "Eu", "login": "eu", "perfil": "usuario"}
        self.timeline_items: list[dict] = []
        self.mark_read_calls: list[tuple[int, int]] = []
        self.sent_messages: list[dict] = []

    def chat_mentionable_users(self):
        return [{"id": 1, "display_name": "Eu", "sector": "Controle Geral"}, {"id": 2, "display_name": "Carlos", "sector": "Almoxarifado"}]

    def get_process_dict(self, proposal_id):
        return {"proposta": "CP05280", "cliente": "ENERGY SYSTEM", "obra_site": "Obra X", "prazo_entrega": "10/10/2026", "peso": "120"}

    def current_location(self, proposal):
        return ("PRODUCAO", "Producao", "EM_PRODUCAO")

    def status_label(self, status):
        return status or "-"

    def chat_proposal_timeline(self, proposal_id, **filters):
        return {"conversation_id": 1, "items": list(self.timeline_items), "has_more": False}

    def chat_mark_read(self, conversation_id, last_id):
        self.mark_read_calls.append((conversation_id, last_id))

    def chat_mark_question_viewed(self, message_id):
        pass

    def chat_send_message(
        self,
        conversation_id,
        body,
        message_type="MENSAGEM",
        mentioned_user_id=None,
        reply_to_message_id=None,
        area=None,
        due_at=None,
        is_important=False,
        client_message_id=None,
    ):
        message = {
            "id": 900 + len(self.sent_messages),
            "conversation_id": conversation_id,
            "author_user_id": self.user["id"],
            "author_name": "Eu",
            "message_type": message_type,
            "body": body,
            "mentioned_user_id": mentioned_user_id,
            "mentioned_user_name": None,
            "question_status": None,
            "client_message_id": client_message_id,
            "answered_message_id": reply_to_message_id,
            "area": area,
            "due_at": due_at,
            "viewed_at": None,
            "cancelled_at": None,
            "cancellation_reason": None,
            "is_important": is_important,
            "created_at": "2026-08-04T10:10:00Z",
            "seen_by_count": 0,
        }
        self.sent_messages.append(message)
        self.timeline_items.append(_entry(message["id"], body=body, created_at=message["created_at"]))
        return message

    def can_admin_chat(self):
        return False


def _entry(entry_id, kind="MENSAGEM", author=1, body="mensagem", created_at="2026-08-04T10:00:00Z", **extra):
    row = {
        "id": entry_id, "source": "chat", "entry_kind": kind, "author_user_id": author,
        "author_name": "Eu" if author == 1 else "Carlos", "mentioned_user_id": None,
        "mentioned_user_name": None, "question_status": None, "answered_message_id": None,
            "body": body, "area": None,
            "created_at": created_at, "seen_by_count": 0, "attachments": [],
    }
    row.update(extra)
    return row


class ChatTimelineLayoutTests(unittest.TestCase):
    """Regressao do bug de sobreposicao: app/ui/animations.py::slide_fade_in
    animava QPropertyAnimation(widget, b"pos") num widget filho de QVBoxLayout
    — o layout reposiciona os itens a cada insercao/remocao (o que acontece a
    cada refresh/push), e a animacao em voo "puxava" o widget de volta pra uma
    coordenada que o layout ja tinha abandonado, sobrepondo quem estava la."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _build_panel(self, entries: list[dict]) -> ChatConversationPanel:
        service = FakeService()
        service.timeline_items = entries
        panel = ChatConversationPanel(service, proposal_id=123)
        panel.resize(700, 900)
        panel.show()
        # refresh() usa uma QThread real (start_worker); processa o loop de
        # eventos ate a chamada sincrona de chat_proposal_timeline() completar
        # e _refresh_success() rodar na GUI thread. processEvents() sozinho e
        # CPU-bound e nao cede tempo real de CPU pra outra thread rodar — com
        # varios testes no mesmo processo (mais threads/objetos vivos), 200
        # iteracoes instantaneas podem nao ser suficientes; um sleep minimo
        # por iteracao da ao SO uma chance real de agendar a outra thread.
        deadline_iterations = 200
        while not panel.entries and deadline_iterations > 0:
            self.app.processEvents()
            time.sleep(0.003)
            deadline_iterations -= 1
        for _ in range(10):
            self.app.processEvents()
        panel.feed_layout.activate()
        for _ in range(10):
            self.app.processEvents()
        return panel

    def _rendered_rows(self, panel: ChatConversationPanel) -> list:
        rows = []
        for i in range(panel.feed_layout.count()):
            item = panel.feed_layout.itemAt(i)
            widget = item.widget()
            if widget is not None:
                rows.append(widget)
        return rows

    def _rendered_message_rows(self, panel: ChatConversationPanel) -> list:
        return [row for row in self._rendered_rows(panel) if not isinstance(row, TimelineDaySeparator)]

    def test_messages_do_not_overlap(self):
        entries = [
            _entry(1, body="curta", created_at="2026-08-04T10:00:00Z"),
            _entry(2, author=2, body="palavra " * 80, created_at="2026-08-04T10:01:00Z"),
            _entry(3, kind="NOTA_INTERNA", body="nota interna qualquer", area="PRODUCAO", created_at="2026-08-04T10:02:00Z"),
            _entry(4, kind="PERGUNTA", author=2, mentioned_user_id=1, mentioned_user_name="Eu", body="tudo certo?", created_at="2026-08-04T10:03:00Z"),
        ]
        panel = self._build_panel(entries)
        rows = self._rendered_rows(panel)
        self.assertGreater(len(rows), 0)

        previous_bottom = -1
        for widget in rows:
            geometry = widget.geometry()
            self.assertGreaterEqual(
                geometry.top(), previous_bottom,
                f"widget {widget} overlaps the previous row (top={geometry.top()}, previous_bottom={previous_bottom})",
            )
            previous_bottom = geometry.bottom()

    def test_long_message_expands_bubble(self):
        entries = [
            _entry(1, body="oi", created_at="2026-08-04T10:00:00Z"),
            _entry(2, body="palavra " * 100, created_at="2026-08-04T10:05:00Z"),
        ]
        panel = self._build_panel(entries)
        rows = self._rendered_message_rows(panel)
        heights = [row.geometry().height() for row in rows]
        self.assertGreater(max(heights), min(heights) * 2)

    def test_message_added_only_once(self):
        entries = [_entry(1), _entry(2, author=2, body="oi de volta")]
        panel = self._build_panel(entries)
        panel._render_entries()
        panel._render_entries()
        panel._render_entries()
        self.assertEqual(len(panel._entry_widgets), 2)
        rows = self._rendered_message_rows(panel)
        self.assertEqual(len(rows), 2)

    def test_resize_recalculates_without_overlap(self):
        entries = [_entry(i, body="palavra " * 30, created_at=f"2026-08-04T10:0{i}:00Z") for i in range(5)]
        panel = self._build_panel(entries)
        panel.resize(1200, 900)
        self.app.processEvents()
        panel.resize(420, 900)
        self.app.processEvents()

        rows = self._rendered_rows(panel)
        previous_bottom = -1
        for widget in rows:
            geometry = widget.geometry()
            self.assertGreaterEqual(geometry.top(), previous_bottom)
            previous_bottom = geometry.bottom()

    def test_question_and_answer_have_independent_geometry(self):
        entries = [
            _entry(1, kind="PERGUNTA", author=2, mentioned_user_id=1, mentioned_user_name="Eu", body="confirma?", question_status="RESPONDIDA", created_at="2026-08-04T10:00:00Z"),
            _entry(2, body="confirmado", answered_message_id=1, created_at="2026-08-04T10:01:00Z"),
        ]
        panel = self._build_panel(entries)
        rows = self._rendered_message_rows(panel)
        self.assertEqual(len(rows), 2)
        self.assertLess(rows[0].geometry().bottom(), rows[1].geometry().top() + 1)

    def test_date_separator_is_not_duplicated(self):
        entries = [_entry(i, created_at=f"2026-08-04T1{i}:00:00Z") for i in range(4)]
        panel = self._build_panel(entries)
        panel._render_entries()
        panel._render_entries()
        self.assertEqual(len(panel._day_separator_widgets), 1)

    def _row_texts(self, row) -> str:
        return " ".join(label.text() for label in row.findChildren(QLabel))

    def test_overdue_question_shows_atrasada_badge(self):
        entries = [
            _entry(
                1, kind="PERGUNTA", author=2, mentioned_user_id=1, mentioned_user_name="Eu",
                body="confirma?", question_status="ATRASADA", due_at="2020-01-01T00:00:00Z",
                created_at="2026-08-04T10:00:00Z",
            ),
        ]
        panel = self._build_panel(entries)
        rows = self._rendered_message_rows(panel)
        self.assertEqual(len(rows), 1)
        texts = self._row_texts(rows[0])
        self.assertIn("Atrasada", texts)
        self.assertIn("Prazo:", texts)

    def test_cancelled_question_shows_cancelada_badge_and_reason(self):
        entries = [
            _entry(
                1, kind="PERGUNTA", author=1, mentioned_user_id=2, mentioned_user_name="Carlos",
                body="ainda precisa?", question_status="CANCELADA", cancellation_reason="Nao e mais necessario",
                created_at="2026-08-04T10:00:00Z",
            ),
        ]
        panel = self._build_panel(entries)
        rows = self._rendered_message_rows(panel)
        texts = self._row_texts(rows[0])
        self.assertIn("Cancelada", texts)
        self.assertIn("Nao e mais necessario", texts)

    def test_important_internal_note_shows_badge(self):
        entries = [
            _entry(1, kind="NOTA_INTERNA", body="Material atrasado", area="PRODUCAO", is_important=True, created_at="2026-08-04T10:00:00Z"),
        ]
        panel = self._build_panel(entries)
        rows = self._rendered_message_rows(panel)
        texts = self._row_texts(rows[0])
        self.assertIn("IMPORTANTE", texts)

    def test_answer_button_hidden_for_cancelled_question(self):
        entries = [
            _entry(
                1, kind="PERGUNTA", author=2, mentioned_user_id=1, mentioned_user_name="Eu",
                body="confirma?", question_status="CANCELADA", cancellation_reason="sem motivo",
                created_at="2026-08-04T10:00:00Z",
            ),
        ]
        panel = self._build_panel(entries)
        rows = self._rendered_message_rows(panel)
        self.assertFalse(rows[0]._answer_btn.isVisible())

    def test_refresh_does_not_mark_the_same_cursor_read_repeatedly(self):
        panel = self._build_panel([_entry(1), _entry(2, author=2)])
        self.assertEqual(panel.service.mark_read_calls, [(1, 2)])

        panel.refresh()
        for _ in range(200):
            self.app.processEvents()
            if not panel._refresh_in_flight:
                break
            time.sleep(0.003)

        self.assertEqual(panel.service.mark_read_calls, [(1, 2)])

    def _message_out(self, message_id, body, author=1, **extra):
        message = {
            "id": message_id, "conversation_id": 1, "author_user_id": author,
            "client_message_id": None,
            "author_name": "Eu" if author == 1 else "Carlos", "message_type": "MENSAGEM",
            "body": body, "mentioned_user_id": None, "mentioned_user_name": None,
            "question_status": None, "answered_message_id": None, "area": None,
            "due_at": None, "viewed_at": None, "cancelled_at": None, "cancellation_reason": None,
            "is_important": False, "created_at": "2026-08-04T10:05:00Z", "seen_by_count": 0, "attachments": [],
        }
        message.update(extra)
        return message

    def test_append_sent_message_shows_immediately_without_refresh(self):
        panel = self._build_panel([_entry(1)])
        initial_rows = len(self._rendered_message_rows(panel))

        panel._append_sent_message(self._message_out(2, "mensagem nova"))

        rows = self._rendered_message_rows(panel)
        self.assertEqual(len(rows), initial_rows + 1)
        self.assertIn("mensagem nova", self._row_texts(rows[-1]))

    def test_message_attachments_render_inside_bubble(self):
        entries = [
            _entry(
                1,
                body="segue anexo",
                attachments=[
                    {
                        "id": 301,
                        "message_id": 1,
                        "original_filename": "torre_rev02.dwg",
                        "category": "cad",
                        "size": 4928307,
                        "sha256": "c" * 64,
                    }
                ],
            )
        ]
        panel = self._build_panel(entries)
        rows = self._rendered_message_rows(panel)
        texts = self._row_texts(rows[0])

        # A bolha agora se molda ao anexo (compacta), entao o nome do arquivo
        # pode ser elidido visualmente -- o nome completo continua acessivel
        # via tooltip (mesma garantia da Fase 3).
        name_labels = rows[0].findChildren(QLabel, "FileCardName")
        self.assertTrue(name_labels)
        self.assertEqual(name_labels[0].toolTip(), "torre_rev02.dwg")
        self.assertIn("DWG", texts)

    def test_own_image_message_uses_same_blue_bubble_as_documents(self):
        entries = [
            _entry(
                1,
                body="[Anexo]",
                attachments=[
                    {
                        "id": 501,
                        "message_id": 1,
                        "original_filename": "foto.png",
                        "category": "image",
                        "file_size": 100,
                    }
                ],
            )
        ]
        panel = self._build_panel(entries)
        rows = self._rendered_message_rows(panel)
        bubbles = [frame for frame in rows[0].findChildren(QFrame) if frame.objectName() == "BubbleOwn"]

        self.assertTrue(bubbles)
        self.assertNotIn("transparent", bubbles[0].styleSheet())
        self.assertIn("border-radius", bubbles[0].styleSheet())

    def test_realtime_attachment_event_merges_without_duplicate(self):
        entries = [_entry(1, body="segue", attachments=[{"id": 10, "message_id": 1, "original_filename": "a.pdf", "category": "document", "file_size": 10, "sha256": "a" * 64}])]
        panel = self._build_panel(entries)

        payload = {
            "conversation_id": 1,
            "message_id": 1,
            "attachment": {"id": 11, "message_id": 1, "original_filename": "b.pdf", "category": "document", "file_size": 20, "sha256": "b" * 64},
        }
        panel.apply_realtime_event("attachment.created", payload)
        panel.apply_realtime_event("attachment.created", payload)
        panel.apply_realtime_event(
            "attachment.deleted",
            {
                "conversation_id": 1,
                "message_id": 1,
                "attachment": {
                    "id": 11,
                    "message_id": 1,
                    "original_filename": "b.pdf",
                    "category": "document",
                    "file_size": 20,
                    "sha256": "b" * 64,
                    "deleted_at": "2026-08-20T15:00:00Z",
                },
            },
        )

        self.assertEqual([item["id"] for item in panel.entries[0]["attachments"]], [10, 11])
        texts = self._row_texts(self._rendered_message_rows(panel)[0])
        self.assertIn("Anexo removido", texts)

    def test_send_message_survives_optimistic_render_failure(self):
        panel = self._build_panel([_entry(1)])
        panel.compose_bar.text_edit.setPlainText("mensagem que deve enviar")
        original_render = panel._render_entries

        def fail_once(*args, **kwargs):
            panel._render_entries = original_render
            raise RuntimeError("falha simulada no render otimista")

        panel._render_entries = fail_once
        panel.send_message()
        self._pump_ms(300)

        self.assertEqual(len(panel.service.sent_messages), 1)
        self.assertEqual(panel.service.sent_messages[0]["body"], "mensagem que deve enviar")

    def test_append_sent_message_is_not_duplicated_by_a_later_refresh(self):
        panel = self._build_panel([_entry(1)])
        panel._append_sent_message(self._message_out(2, "mensagem nova"))

        panel.service.timeline_items = [_entry(1), _entry(2, body="mensagem nova", created_at="2026-08-04T10:05:00Z")]
        panel.refresh()
        for _ in range(200):
            self.app.processEvents()
            if not panel._refresh_in_flight:
                break
            time.sleep(0.003)

        rows = self._rendered_message_rows(panel)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(panel._entry_widgets), 2)

    def _pump_ms(self, ms: int):
        deadline = time.monotonic() + ms / 1000.0
        while time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)

    def test_sending_own_message_scrolls_to_the_bottom(self):
        # Regressao: a bolha recem-inserida as vezes so ganha a altura final
        # (texto quebrado em varias linhas) um instante DEPOIS da animacao de
        # rolagem comecar -- sem acompanhar o rangeChanged do scrollbar, a
        # rolagem parava alguns pixels antes do fundo de verdade.
        entries = [_entry(i, body="palavra " * 20, created_at=f"2026-08-20T09:{i:02d}:00Z") for i in range(20)]
        panel = self._build_panel(entries)
        bar = panel.scroll.verticalScrollBar()
        # usa o proprio _scroll_to_bottom() do painel (com o mecanismo de
        # catch-up) pra descer, em vez de so setValue(maximum()) -- sob a
        # suite inteira rodando, o layout do feed pode nao ter se assentado
        # ainda no momento de montar o cenario do teste.
        panel._scroll_to_bottom()
        self._pump_ms(700)
        self.assertTrue(panel._is_scrolled_to_bottom())

        panel._append_sent_message(
            {
                "id": 21, "conversation_id": 1, "author_user_id": 1, "author_name": "Eu",
                "message_type": "MENSAGEM", "body": "minha mensagem nova", "mentioned_user_id": None,
                "mentioned_user_name": None, "question_status": None, "answered_message_id": None,
                "area": None, "due_at": None, "viewed_at": None, "cancelled_at": None,
                "cancellation_reason": None, "is_important": False,
                "created_at": "2026-08-20T10:00:00Z", "seen_by_count": 0,
            }
        )
        self._pump_ms(1000)

        self.assertEqual(bar.value(), bar.maximum())
        self.assertTrue(panel._is_scrolled_to_bottom())
        self.assertFalse(panel._new_messages_btn.isVisible())

    def test_message_from_others_shows_jump_button_that_scrolls_down_on_click(self):
        entries = [_entry(i, body="palavra " * 20, created_at=f"2026-08-20T09:{i:02d}:00Z") for i in range(20)]
        panel = self._build_panel(entries)
        bar = panel.scroll.verticalScrollBar()
        bar.setValue(0)
        self.app.processEvents()
        self.assertFalse(panel._is_scrolled_to_bottom())

        panel.service.timeline_items = entries + [_entry(20, author=2, body="mensagem do carlos", created_at="2026-08-20T10:00:00Z")]
        panel.refresh()
        for _ in range(300):
            self.app.processEvents()
            if not panel._refresh_in_flight:
                break
            time.sleep(0.003)
        self._pump_ms(100)

        self.assertFalse(panel._is_scrolled_to_bottom())
        self.assertTrue(panel._new_messages_btn.isVisible())

        panel._new_messages_btn.click()
        self._pump_ms(1000)

        self.assertTrue(panel._is_scrolled_to_bottom())
        self.assertFalse(panel._new_messages_btn.isVisible())

    def test_animations_module_has_no_pos_or_geometry_animation(self):
        import inspect

        from app.ui import animations

        source = inspect.getsource(animations)
        self.assertNotIn('b"pos"', source)
        self.assertNotIn('b"geometry"', source)
        self.assertFalse(hasattr(animations, "slide_fade_in"))


if __name__ == "__main__":
    unittest.main()
