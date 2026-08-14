from __future__ import annotations

import os
import unittest
from datetime import datetime
from dataclasses import replace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QMessageBox, QPushButton

from app.services.nomus_api_config import NomusApiSettings, NomusConnectionTestResult
from app.ui.nomus_api_settings_dialog import NomusApiSettingsDialog, NomusIntegrationSettingsWidget
from app.ui.settings_page import SettingsPage


class FakeNomusStore:
    def __init__(self, settings: NomusApiSettings):
        self.settings = settings
        self.test_calls = []
        self.load_calls = 0
        self.saved_keys = []
        self.settings_calls = []
        self.delete_calls = 0

    def load_settings(self):
        self.load_calls += 1
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

    def save_api_key(self, value):
        self.saved_keys.append(value)
        self.settings = replace(self.settings, api_key_configured=True, masked_api_key="************1234")

    def delete_api_key(self):
        self.delete_calls += 1
        self.settings = replace(self.settings, api_key_configured=False, masked_api_key=None)

    def save_settings(self, *, enabled, base_url):
        self.settings_calls.append({"enabled": enabled, "base_url": base_url})
        self.settings = replace(self.settings, enabled=enabled, base_url=base_url)
        return self.settings


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

        widget = NomusIntegrationSettingsWidget(store=FakeNomusStore(settings))

        self.assertEqual(widget.base_url.text(), "https://example.nomus.com.br/rest")
        self.assertIn("1234", widget.key_status.text())
        self.assertEqual(widget.api_key.text(), "")
        self.assertEqual(widget.api_key.echoMode(), QLineEdit.Password)
        self.assertTrue(widget.enabled_check.isChecked())

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
        widget = NomusIntegrationSettingsWidget(store=store)
        widget._run_background = lambda operation, on_success, _on_error: on_success(operation())
        widget._show_test_result = lambda _result: None

        widget.test_connection()

        self.assertEqual(len(store.test_calls), 1)
        self.assertEqual(store.test_calls[0]["base_url"], "https://example.nomus.com.br/rest")

    def test_settings_page_shows_nomus_section_only_for_admin(self):
        admin_page = SettingsPage(FakeSettingsService(admin=True))
        user_page = SettingsPage(FakeSettingsService(admin=False))

        admin_buttons = [button.text() for button in admin_page.findChildren(QPushButton)]
        user_buttons = [button.text() for button in user_page.findChildren(QPushButton)]

        self.assertIsNotNone(admin_page.nomus_settings)
        self.assertIsNone(user_page.nomus_settings)
        self.assertIn("Testar conexao", admin_buttons)
        self.assertIn("Salvar", admin_buttons)
        self.assertIn("Diagnostico da API", admin_buttons)
        self.assertIn("Consultar propostas na API", admin_buttons)
        self.assertNotIn("Testar conexao", user_buttons)
        self.assertNotIn("Diagnostico da API", user_buttons)
        self.assertNotIn("Consultar propostas na API", user_buttons)

    def test_embedded_widget_loads_only_when_nomus_category_is_first_selected(self):
        settings = NomusApiSettings(False, "https://example.nomus.com.br/rest", False, None, None, None, None)
        store = FakeNomusStore(settings)
        page = SettingsPage(FakeSettingsService(admin=True))
        page.nomus_settings.store = store

        self.assertEqual(store.load_calls, 0)
        page.select_category("nomus")
        self.assertEqual(store.load_calls, 1)
        self.assertIs(page.stack.currentWidget(), page.category_pages["nomus"])

        page.select_category("appearance")
        page.select_category("nomus")
        self.assertEqual(store.load_calls, 1)

    def test_legacy_dialog_wraps_the_same_widget(self):
        settings = NomusApiSettings(False, "https://example.nomus.com.br/rest", False, None, None, None, None)
        dialog = NomusApiSettingsDialog(store=FakeNomusStore(settings))

        self.assertIsInstance(dialog.content, NomusIntegrationSettingsWidget)
        cancel_buttons = [button for button in dialog.findChildren(QPushButton) if button.text() == "Cancelar"]
        self.assertEqual(len(cancel_buttons), 1)

    def test_embedded_save_preserves_key_and_settings_store_calls(self):
        settings = NomusApiSettings(False, "https://example.nomus.com.br/rest", False, None, None, None, None)
        store = FakeNomusStore(settings)
        widget = NomusIntegrationSettingsWidget(store=store)
        widget.api_key.setText("segredo-1234")
        widget.api_key.textEdited.emit("segredo-1234")
        widget.enabled_check.setChecked(True)

        with patch("app.ui.nomus_api_settings_dialog.QMessageBox.information"):
            widget.save()

        self.assertEqual(store.saved_keys, ["segredo-1234"])
        self.assertEqual(store.settings_calls, [{"enabled": True, "base_url": "https://example.nomus.com.br/rest"}])
        self.assertEqual(widget.api_key.text(), "")
        self.assertIn("1234", widget.key_status.text())

    def test_remove_key_remains_pending_until_save(self):
        settings = NomusApiSettings(False, "https://example.nomus.com.br/rest", True, "************1234", None, None, None)
        store = FakeNomusStore(settings)
        widget = NomusIntegrationSettingsWidget(store=store)

        with patch("app.ui.nomus_api_settings_dialog.QMessageBox.question", return_value=QMessageBox.Yes):
            widget.remove_key()
        self.assertEqual(store.delete_calls, 0)
        self.assertIn("marcada para remocao", widget.key_status.text())

        with patch("app.ui.nomus_api_settings_dialog.QMessageBox.information"):
            widget.save()
        self.assertEqual(store.delete_calls, 1)
        self.assertFalse(widget.remove_key_btn.isEnabled())

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

        self.assertNotIn("Usuarios e permissoes", buttons)
        self.assertIsNotNone(page.users_management)


if __name__ == "__main__":
    unittest.main()
