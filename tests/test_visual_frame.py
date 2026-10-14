from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QWidget

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.components.count_badge import format_count_badge
from app.ui.components.floating_chat_button import FloatingChatButton
from app.ui.components.login_summary_banner import LoginSummaryBanner
from app.ui.components.modern_button import ModernButton
from app.ui.components.toast_manager import InAppToast
from app.ui.icons import IconColorRole
from app.ui.sidebar import NAV_LABELS, Sidebar


class FakeService:
    def __init__(self, palette_name: str = "claro"):
        self.palette_name = palette_name
        self.palette = OFFICIAL_COLOR_PALETTES[palette_name]
        self.company = "Industel Teste"
        self.user = {"id": 1, "nome": "Usuario Teste", "login": "teste", "perfil": "usuario"}

    def visible_areas(self):
        return ["CONTROLE GERAL", "PRODUCAO", "EXPEDICAO"]


class SidebarFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_labels_are_accented_but_keys_stay_internal(self):
        self.assertEqual(NAV_LABELS["PRODUCAO"], "Produção")
        self.assertEqual(NAV_LABELS["RELATORIOS OPERACIONAIS"], "Relatórios Operacionais")
        sidebar = Sidebar(FakeService())
        self.assertIn("PRODUCAO", sidebar.buttons)
        self.assertEqual(sidebar.buttons["PRODUCAO"].text(), "Produção")

    def test_nav_counter_is_painted_and_never_changes_the_label(self):
        sidebar = Sidebar(FakeService())
        button = sidebar.buttons["PRODUCAO"]
        sidebar.set_nav_badge("PRODUCAO", 4)
        self.assertEqual(button.text(), "Produção")
        self.assertEqual(format_count_badge(button._badge_count), "4")
        button.resize(200, 40)
        self.assertFalse(button.grab().isNull())

        sidebar.set_collapsed(True)
        self.assertEqual(button.text(), "")
        self.assertEqual(format_count_badge(button._badge_count), "4")
        self.assertFalse(button.grab().isNull())

        sidebar.set_collapsed(False)
        sidebar.set_nav_badge("PRODUCAO", 0)
        self.assertEqual(button.text(), "Produção")
        self.assertEqual(format_count_badge(button._badge_count), "")

    def test_active_item_icon_switches_to_on_accent_color(self):
        sidebar = Sidebar(FakeService())
        sidebar.set_active("PRODUCAO")
        self.assertEqual(sidebar.buttons["PRODUCAO"]._color_role, IconColorRole.ON_ACCENT)
        self.assertEqual(sidebar.buttons["PRODUCAO"].property("active"), "true")
        self.assertEqual(sidebar.buttons["EXPEDICAO"]._color_role, IconColorRole.PRIMARY)

        sidebar.set_active("EXPEDICAO")
        self.assertEqual(sidebar.buttons["PRODUCAO"]._color_role, IconColorRole.PRIMARY)
        self.assertEqual(sidebar.buttons["EXPEDICAO"]._color_role, IconColorRole.ON_ACCENT)


class FrameWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_floating_chat_button_counter_is_painted_not_text(self):
        button = FloatingChatButton(FakeService())
        button.set_unread_count(120)
        self.assertEqual(button.text(), "")
        self.assertEqual(format_count_badge(button._badge_count), "99+")
        self.assertIn("120", button.toolTip())
        self.assertFalse(button.grab().isNull())
        button.set_unread_count(0)
        self.assertEqual(format_count_badge(button._badge_count), "")
        self.assertEqual(button.toolTip(), "Abrir chats")

    def test_toast_has_no_inline_stylesheet_and_one_primary_action(self):
        parent = QWidget()
        toast = InAppToast(FakeService(), parent, "Marcos - CP 1", "Mensagem", {"conversation_id": 1})
        toast._timer.stop()
        self.assertEqual(toast.objectName(), "Toast")
        self.assertEqual(toast.styleSheet(), "")
        primary = [b for b in toast.findChildren(ModernButton) if b.variant() == "primary"]
        self.assertEqual([b.text() for b in primary], ["Abrir conversa"])
        closed: list[object] = []
        toast.closed.connect(closed.append)
        toast._dismiss()
        self.assertEqual(closed, [toast])

    def test_login_summary_banner_highlights_pending_over_messages(self):
        banner = LoginSummaryBanner(FakeService(), "Maria", 5, 2, 3)
        self.assertEqual(banner.styleSheet(), "")
        variants = {b.text(): b.variant() for b in banner.findChildren(ModernButton)}
        self.assertEqual(variants, {"Ver mensagens": "secondary", "Ver pendências": "primary"})
        texts = [label.text() for label in banner.findChildren(QLabel)]
        self.assertIn("2 menções", texts)
        self.assertIn("3 pendências abertas", texts)

        only_messages = LoginSummaryBanner(FakeService(), "Maria", 1, 0, 0)
        variants = {b.text(): b.variant() for b in only_messages.findChildren(ModernButton)}
        self.assertEqual(variants, {"Ver mensagens": "primary"})


if __name__ == "__main__":
    unittest.main()
