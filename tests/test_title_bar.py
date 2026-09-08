from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication, QPushButton

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.components.count_badge import format_count_badge
from app.ui.components.title_bar import TitleBar
from app.ui.sidebar import Sidebar


class FakeService:
    def __init__(self, palette_name: str = "claro"):
        self.palette_name = palette_name
        self.palette = OFFICIAL_COLOR_PALETTES[palette_name]
        self.company = "Industel Teste"
        self.user = {"id": 1, "nome": "Usuario Teste", "login": "teste", "perfil": "usuario"}

    def visible_areas(self):
        return ["PRODUCAO"]

    def chat_notifications(self, limit=30):
        return []


class TitleBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _build_title_bar(self) -> TitleBar:
        service = FakeService()
        bar = TitleBar(service)
        bar.resize(900, 40)
        return bar

    def test_topbar_has_unique_actions(self):
        bar = self._build_title_bar()
        action_buttons = [bar.chat_btn, bar.notification_bell, bar.theme_btn, bar.settings_btn, bar.profile_btn]
        self.assertEqual(len(action_buttons), len(set(id(b) for b in action_buttons)))
        self.assertFalse(hasattr(bar, "quick_indicator_messages"))
        self.assertFalse(hasattr(bar, "quick_indicator_questions"))
        self.assertFalse(hasattr(bar, "quick_indicator_observations"))
        self.assertFalse(hasattr(bar, "help_btn"))

    def test_maximize_button_changes_to_restore(self):
        bar = self._build_title_bar()
        bar.set_maximized(True)
        self.assertEqual(bar.maximize_btn.toolTip(), "Restaurar")
        bar.set_maximized(False)
        self.assertEqual(bar.maximize_btn.toolTip(), "Maximizar")

    def test_topbar_signals_are_emitted_once(self):
        bar = self._build_title_bar()
        calls = []
        bar.chat_requested.connect(lambda: calls.append(1))
        bar.chat_btn.click()
        self.assertEqual(len(calls), 1)

    def test_theme_toggle_signal_emitted_once(self):
        bar = self._build_title_bar()
        calls = []
        bar.theme_toggle_requested.connect(lambda: calls.append(1))
        bar.theme_btn.click()
        self.assertEqual(len(calls), 1)

    def test_settings_signal_emitted_once(self):
        bar = self._build_title_bar()
        calls = []
        bar.settings_requested.connect(lambda: calls.append(1))
        bar.settings_btn.click()
        self.assertEqual(len(calls), 1)

    def test_chat_unread_badge_hidden_when_zero(self):
        # O contador e pintado no paintEvent, nunca via setText (assim o
        # botao nao muda de tamanho quando o badge aparece/some) - ver
        # AppIconButton.set_badge_count.
        bar = self._build_title_bar()
        bar.set_chat_unread_count(5)
        self.assertEqual(format_count_badge(bar.chat_btn._badge_count), "5")
        bar.set_chat_unread_count(0)
        self.assertEqual(format_count_badge(bar.chat_btn._badge_count), "")

    def test_window_buttons_are_registered_interactive(self):
        bar = self._build_title_bar()
        bar.show()
        bar.layout().activate()
        for button in (bar.minimize_btn, bar.maximize_btn, bar.close_btn, bar.chat_btn, bar.settings_btn):
            center = button.geometry().center()
            self.assertTrue(bar.is_over_interactive_widget(center))


class SidebarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_settings_removed_from_sidebar(self):
        sidebar = Sidebar(FakeService())
        self.assertNotIn("CONFIGURACOES", sidebar.buttons)

    def test_theme_button_removed_from_sidebar(self):
        sidebar = Sidebar(FakeService())
        self.assertFalse(hasattr(sidebar, "theme_button"))
        self.assertFalse(hasattr(sidebar, "theme_toggle_requested"))

    def test_chats_removed_from_sidebar(self):
        # Chats deixou de ser um item da barra lateral — o acesso e exclusivo
        # pelo icone de conversa da barra superior (TitleBar.chat_btn).
        sidebar = Sidebar(FakeService())
        self.assertNotIn("CHATS", sidebar.buttons)
        from app.ui.sidebar import NAV_LABELS

        self.assertNotIn("CHATS", NAV_LABELS)


if __name__ == "__main__":
    unittest.main()
