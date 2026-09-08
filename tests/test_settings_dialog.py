from __future__ import annotations

import os
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from app.services.backend_adapter import OFFICIAL_COLOR_PALETTES
from app.ui.settings_dialog import SettingsDialog
from app.ui.main_window import MainWindow
from app.ui.settings_page import SettingsPage


class FakeSettingsService:
    palettes = OFFICIAL_COLOR_PALETTES
    palette_name = "claro"
    palette = OFFICIAL_COLOR_PALETTES["claro"]
    company = "Industel"
    config = {"desktop_api": {"enabled": True, "base_url": "http://127.0.0.1:8000"}}

    def __init__(self, admin: bool = True, manage_users: bool = True):
        self.admin = admin
        self.manage_users = manage_users
        self.user_rows_calls = 0

    def can_admin(self):
        return self.admin

    def can_edit(self, area: str):
        if area == "users_permissions":
            return self.manage_users
        return area == "settings"

    def official_proposals_enabled(self):
        return True

    def user_name(self):
        return "Administrador" if self.admin else "Operador"

    def user_profile(self):
        return "Administrador" if self.admin else "Usuario"

    def user_rows(self):
        self.user_rows_calls += 1
        return [
            {"id": 1, "nome": "Administrador", "login": "admin", "perfil_label": "Administrador", "ativo_label": "Sim"},
            {"id": 2, "nome": "Operador", "login": "operador", "perfil_label": "Usuario", "ativo_label": "Nao"},
        ]


class SettingsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_is_modal_resizable_and_reopens(self):
        parent = QWidget()
        parent.resize(1200, 760)

        for _ in range(2):
            dialog = SettingsDialog(FakeSettingsService(), parent=parent)
            self.assertTrue(dialog.isModal())
            self.assertGreaterEqual(dialog.minimumWidth(), 920)
            self.assertGreaterEqual(dialog.minimumHeight(), 600)
            self.assertTrue(dialog.isSizeGripEnabled())
            dialog.show()
            self.app.processEvents()
            self.assertTrue(dialog.isVisible())
            dialog.close()
            self.app.processEvents()
            self.assertFalse(dialog.isVisible())

    def test_only_selected_category_is_current(self):
        service = FakeSettingsService()
        page = SettingsPage(service)
        self.assertEqual(page.stack.count(), 9)
        self.assertIs(page.stack.currentWidget(), page.category_pages["appearance"])
        self.assertEqual(service.user_rows_calls, 0)

        page.select_category("api_database")

        self.assertIs(page.stack.currentWidget(), page.category_pages["api_database"])
        self.assertEqual(page.category_buttons["api_database"].property("active"), "true")
        self.assertEqual(page.category_buttons["appearance"].property("active"), "false")

        page.select_category("users")
        self.assertEqual(service.user_rows_calls, 1)
        self.assertEqual(page.users_management.model.rowCount(), 2)

        page.select_category("appearance")
        page.select_category("users")
        self.assertEqual(service.user_rows_calls, 1)

    def test_admin_only_categories_and_actions_keep_existing_visibility(self):
        admin_page = SettingsPage(FakeSettingsService(admin=True))
        user_page = SettingsPage(FakeSettingsService(admin=False, manage_users=False))

        self.assertIn("nomus", admin_page.category_pages)
        self.assertNotIn("nomus", user_page.category_pages)
        self.assertIsNotNone(admin_page.users_management)
        self.assertIsNone(user_page.users_management)

        admin_buttons = {button.text() for button in admin_page.findChildren(QPushButton)}
        user_buttons = {button.text() for button in user_page.findChildren(QPushButton)}
        for text in ("Testar conexao", "Salvar", "Diagnostico da API", "Consultar propostas na API"):
            self.assertIn(text, admin_buttons)
            self.assertNotIn(text, user_buttons)

    def test_existing_action_buttons_keep_their_callbacks(self):
        callbacks = {
            "Aplicar visual": "apply_palette",
            "Diagnostico API/PostgreSQL": "open_api_diagnostic",
            "Diagnostico da API": "open_api_diagnostic",
            "Consultar propostas na API": "open_api_proposals",
            "Verificar atualizacoes": "check_updates",
            "Testar servidor de atualizacao": "test_update_server",
            "Abrir pasta de logs": "open_logs_folder",
        }
        with ExitStack() as stack:
            mocks = {
                method: stack.enter_context(patch.object(SettingsPage, method))
                for method in set(callbacks.values())
            }
            page = SettingsPage(FakeSettingsService())
            buttons = {button.text(): button for button in page.findChildren(QPushButton)}

            for text, method in callbacks.items():
                before = mocks[method].call_count
                buttons[text].click()
                self.assertEqual(mocks[method].call_count, before + 1, text)

    def test_main_window_opens_the_same_dialog_from_settings_action(self):
        host = Mock()
        host._can_view.return_value = True
        host.service = FakeSettingsService()
        host.apply_theme = Mock()
        host._settings_dialog = None

        with patch("app.ui.main_window.SettingsDialog") as dialog_class:
            dialog = dialog_class.return_value
            MainWindow.open_settings(host)

        dialog_class.assert_called_once_with(host.service, host.apply_theme, host)
        dialog.exec.assert_called_once_with()
        self.assertIsNone(host._settings_dialog)


if __name__ == "__main__":
    unittest.main()
