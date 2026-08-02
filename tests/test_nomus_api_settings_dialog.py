from __future__ import annotations

import os
import unittest
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from app.services.nomus_api_config import NomusApiSettings, NomusConnectionTestResult
from app.ui.nomus_api_settings_dialog import NomusApiSettingsDialog
from app.ui.settings_page import SettingsPage


class FakeNomusStore:
    def __init__(self, settings: NomusApiSettings):
        self.settings = settings
        self.test_calls = []

    def load_settings(self):
        return self.settings

    def test_authenticated_connection(self, **kwargs):
        self.test_calls.append(kwargs)
        return NomusConnectionTestResult(
            success=True,
            status_code=200,
            category="success",
            user_message="ok",
            technical_message=None,
            tested_at=datetime(2026, 7, 14, 12, 1, 0),
            duration_ms=1,
            endpoint="produtos",
            content_type="application/json",
            authentication_confirmed=True,
        )


class FakeSettingsService:
    palettes = {"light": {"label": "Claro"}}
    palette_name = "light"
    config = {
        "desktop_api": {
            "enabled": True,
            "base_url": "http://127.0.0.1:8000",
            "connect_timeout": 3,
            "read_timeout": 10,
        }
    }
    company = "Industel"

    def __init__(self, admin: bool):
        self.admin = admin

    def can_admin(self):
        return self.admin

    def can_edit(self, area: str):
        return area in {"settings", "users_permissions"}

    def official_proposals_enabled(self):
        return True

    def user_name(self):
        return "Administrador" if self.admin else "Operador"

    def user_profile(self):
        return "Administrador" if self.admin else "Usuario"


class NomusApiSettingsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_shows_mask_without_loading_real_key_into_field(self):
        settings = NomusApiSettings(
            enabled=True,
            base_url="https://example.nomus.com.br/rest",
            api_key_configured=True,
            masked_api_key="••••••••••••1234",
            last_tested_at=datetime(2026, 7, 14, 12, 0, 0),
            last_test_status="success",
            last_test_message="Conexao validada",
        )

        dialog = NomusApiSettingsDialog(store=FakeNomusStore(settings))

        self.assertEqual(dialog.base_url.text(), "https://example.nomus.com.br/rest")
        self.assertIn("1234", dialog.key_status.text())
        self.assertEqual(dialog.api_key.text(), "")
        self.assertTrue(dialog.enabled_check.isChecked())

    def test_dialog_test_button_uses_authenticated_client_path(self):
        settings = NomusApiSettings(
            enabled=False,
            base_url="https://example.nomus.com.br/rest",
            api_key_configured=True,
            masked_api_key="************1234",
            last_tested_at=None,
            last_test_status=None,
            last_test_message=None,
        )
        store = FakeNomusStore(settings)
        dialog = NomusApiSettingsDialog(store=store)
        dialog._run_background = lambda operation, on_success, _on_error: on_success(operation())
        dialog._show_test_result = lambda _result: None

        dialog.test_connection()

        self.assertEqual(len(store.test_calls), 1)
        self.assertEqual(store.test_calls[0]["base_url"], "https://example.nomus.com.br/rest")

    def test_settings_page_shows_nomus_section_only_for_admin(self):
        admin_page = SettingsPage(FakeSettingsService(admin=True))
        user_page = SettingsPage(FakeSettingsService(admin=False))

        admin_buttons = [button.text() for button in admin_page.findChildren(QPushButton)]
        user_buttons = [button.text() for button in user_page.findChildren(QPushButton)]

        self.assertIn("Configurar API Nomus", admin_buttons)
        self.assertIn("Diagnostico da API", admin_buttons)
        self.assertIn("Consultar propostas na API", admin_buttons)
        self.assertNotIn("Configurar API Nomus", user_buttons)
        self.assertNotIn("Diagnostico da API", user_buttons)
        self.assertNotIn("Consultar propostas na API", user_buttons)

    def test_settings_page_no_longer_shows_sqlite_controls(self):
        page = SettingsPage(FakeSettingsService(admin=True))
        visible_texts = [widget.text() for widget in page.findChildren(QPushButton)]
        visible_texts.extend(label.text() for label in page.findChildren(QLabel))
        combined = "\n".join(visible_texts)

        self.assertNotIn("SQLite", combined)
        self.assertNotIn(".db", combined)
        self.assertIn("Diagnostico API/PostgreSQL", combined)

    def test_settings_page_enables_user_management_in_official_postgresql_mode(self):
        page = SettingsPage(FakeSettingsService(admin=True))
        buttons = {button.text(): button for button in page.findChildren(QPushButton)}

        self.assertIn("Usuarios e permissoes", buttons)
        self.assertTrue(buttons["Usuarios e permissoes"].isEnabled())


if __name__ == "__main__":
    unittest.main()
