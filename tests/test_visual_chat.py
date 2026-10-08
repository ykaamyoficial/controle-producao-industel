from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame, QLabel, QWidget

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.components.chat_message_attachments import ChatAttachmentsView
from app.ui.components.mention_compose_bar import MentionComposeBar
from app.ui.components.proposal_activity_panel import ActivityRow
from app.ui.components.style_state import StatusDot, set_style_state
from app.ui.components.timeline_entries import (
    CurrentUserMessageWidget,
    DirectedQuestionWidget,
    InternalNoteWidget,
    OtherUserMessageWidget,
    ReplyMessageWidget,
    TimelineDaySeparator,
    _BubbleBodyLabel,
)
from app.ui.proposal_chat_dialog import ChatTabButton
from app.ui.styles import app_stylesheet

PALETTE = OFFICIAL_COLOR_PALETTES["claro"]


class FakeService:
    def __init__(self, palette_name: str = "claro"):
        self.palette = OFFICIAL_COLOR_PALETTES[palette_name]
        self.user = {"id": 1, "nome": "Eu"}

    def can_admin_chat(self):
        return False


def _entry(entry_id, body, author=2, **extra):
    row = {
        "id": entry_id, "source": "chat", "entry_kind": "MENSAGEM", "author_user_id": author,
        "author_name": "Eu" if author == 1 else "Carlos", "author_sector": "Almoxarifado",
        "mentioned_user_id": None, "mentioned_user_name": None, "question_status": None,
        "answered_message_id": None, "body": body, "area": None,
        "created_at": "2026-10-07T10:20:00Z", "seen_by_count": 0, "attachments": [],
    }
    row.update(extra)
    return row


def _inline_styles(root: QWidget) -> list[str]:
    found = []
    for widget in [root, *root.findChildren(QWidget)]:
        if widget.styleSheet():
            found.append(f"{type(widget).__name__}#{widget.objectName()}")
    return found


class ChatBubbleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.service = FakeService()
        cls.app.setStyleSheet(app_stylesheet(PALETTE))

    def _build(self, factory, entry, grouped=False):
        widget = factory(entry, self.service, 1, ["Eu", "Carlos"], grouped)
        widget.resize(520, widget.sizeHint().height() or 80)
        return widget

    def test_every_timeline_entry_is_styled_by_the_stylesheet_only(self):
        reply = _entry(7, "resposta", 1, answered_message_id=1, _reply_original=_entry(1, "original"))
        question = _entry(8, "pergunta?", 1, entry_kind="PERGUNTA", mentioned_user_id=2, mentioned_user_name="Carlos",
                          question_status="AGUARDANDO_RESPOSTA", due_at="2026-10-08T17:00:00Z")
        note = _entry(9, "nota", 1, entry_kind="NOTA_INTERNA", area="EXPEDICAO", is_important=True)
        cases = [
            (OtherUserMessageWidget, _entry(1, "oi")),
            (OtherUserMessageWidget, _entry(2, "de novo")),
            (CurrentUserMessageWidget, _entry(3, "meu texto", 1, seen_by_count=2)),
            (ReplyMessageWidget, reply),
            (DirectedQuestionWidget, question),
            (InternalNoteWidget, note),
        ]
        for factory, entry in cases:
            with self.subTest(factory=factory.__name__):
                widget = self._build(factory, entry)
                self.assertEqual(_inline_styles(widget), [])
                self.assertFalse(widget.grab().isNull())
        separator = TimelineDaySeparator("Hoje", self.service)
        self.assertEqual(_inline_styles(separator), [])
        self.assertEqual(separator._label.objectName(), "ChatDayChip")

    def test_own_and_other_bubbles_carry_the_tone_that_picks_text_color(self):
        own = self._build(CurrentUserMessageWidget, _entry(3, "meu", 1))
        other = self._build(OtherUserMessageWidget, _entry(1, "dele"))
        self.assertEqual(own.objectName(), "BubbleOwn")
        own_labels = {lbl.objectName(): lbl.property("tone") for lbl in own.findChildren(QLabel)}
        other_labels = {lbl.objectName(): lbl.property("tone") for lbl in other.findChildren(QLabel)}
        self.assertEqual(own_labels["BubbleBody"], "own")
        self.assertEqual(own_labels["BubbleTime"], "own")
        self.assertEqual(other_labels["BubbleBody"], "other")
        self.assertEqual(other_labels["BubbleTime"], "other")

    def test_mention_of_the_current_user_is_a_property_not_a_border_string(self):
        mention = self._build(OtherUserMessageWidget, _entry(4, "oi @Eu", mentioned_user_id=1))
        plain = self._build(OtherUserMessageWidget, _entry(5, "oi"))
        bubble = next(f for f in mention.findChildren(QFrame) if f.objectName() == "BubbleOther")
        self.assertTrue(bubble.property("mentionsMe"))
        self.assertFalse(next(f for f in plain.findChildren(QFrame) if f.objectName() == "BubbleOther").property("mentionsMe"))

    def test_bubble_width_follows_the_text_and_is_capped(self):
        short = self._build(OtherUserMessageWidget, _entry(1, "ok"))
        long_text = "palavra " * 80
        long = self._build(OtherUserMessageWidget, _entry(2, long_text))
        short_label = short.findChildren(_BubbleBodyLabel)[0]
        long_label = long.findChildren(_BubbleBodyLabel)[0]
        self.assertLess(short_label.sizeHint().width(), 80)
        self.assertEqual(long_label.sizeHint().width(), _BubbleBodyLabel.MAX_NATURAL_WIDTH)
        # Texto longo quebra em varias linhas em vez de ficar numa linha so.
        self.assertGreater(long_label.sizeHint().height(), short_label.sizeHint().height() * 2)

    def test_stylesheet_has_the_bubble_rules_for_both_palettes(self):
        for name, palette in OFFICIAL_COLOR_PALETTES.items():
            with self.subTest(theme=name):
                sheet = app_stylesheet(palette)
                own = sheet.split("QFrame#BubbleOwn {", 1)[1].split("}", 1)[0]
                self.assertIn(f"background: {palette['accent']}", own)
                self.assertIn('QFrame#BubbleOther[mentionsMe="true"]', sheet)
                self.assertIn('QLabel#BubbleBody[tone="own"] { color: ' + palette["accent_text"], sheet)
        app_stylesheet(PALETTE)  # deixa o tema claro como paleta ativa dos pintados


class ChatStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(app_stylesheet(PALETTE))

    def test_tab_button_switches_by_property_without_stylesheet(self):
        button = ChatTabButton("Conversa", "chat", PALETTE)
        self.assertFalse(button.property("active"))
        button.set_active(True)
        self.assertTrue(button.property("active"))
        self.assertEqual(button.styleSheet(), "")
        button.set_active(False)
        self.assertFalse(button.property("active"))

    def test_set_style_state_updates_properties(self):
        widget = QFrame()
        set_style_state(widget, flash=True, dropActive=False)
        self.assertTrue(widget.property("flash"))
        self.assertFalse(widget.property("dropActive"))

    def test_compose_bar_drop_state_is_a_property(self):
        bar = MentionComposeBar(FakeService())
        self.assertEqual(_inline_styles(bar), [])
        bar._set_drag_active(True)
        self.assertTrue(bar.property("dropActive"))
        self.assertEqual(bar.toolTip(), "Solte os arquivos para anexar")
        self.assertEqual(bar.styleSheet(), "")
        bar._set_drag_active(False)
        self.assertFalse(bar.property("dropActive"))
        self.assertEqual(bar.toolTip(), "")

    def test_activity_row_has_no_inline_style_and_paints_the_area_bar(self):
        service = FakeService()
        row = ActivityRow({"area": "PRODUCAO", "occurred_at": "2026-10-07T10:20:00Z", "headline": "Produção iniciada"}, service)
        row.resize(400, row.sizeHint().height())
        self.assertEqual(_inline_styles(row), [])
        self.assertFalse(row.grab().isNull())
        badges = [lbl.text() for lbl in row.findChildren(QLabel)]
        self.assertIn("Produção iniciada", badges)

    def test_status_dot_paints(self):
        dot = StatusDot(PALETTE["success"])
        self.assertEqual((dot.width(), dot.height()), (8, 8))
        self.assertFalse(dot.grab().isNull())

    def test_document_attachment_card_has_no_inline_style(self):
        view = ChatAttachmentsView(
            [{"id": 1, "message_id": 1, "original_filename": "projeto.pdf", "category": "document", "file_size": 2048}],
            PALETTE, compact=True, can_delete=lambda _a: False, service=FakeService(),
        )
        view.resize(320, 120)
        self.assertEqual(_inline_styles(view), [])
        self.assertFalse(view.grab().isNull())


if __name__ == "__main__":
    unittest.main()
