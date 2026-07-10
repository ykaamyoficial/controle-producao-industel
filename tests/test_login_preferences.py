from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.services.login_preferences import (
    get_login_preferences_path,
    load_login_preferences,
    save_login_preferences,
)
from app.ui.login_dialog import LoginDialog


class FakeAuthService:
    def __init__(self, valid_login: str = "joao"):
        self.valid_login = valid_login
        self.calls: list[tuple[str, str]] = []

    def authenticate(self, login: str, password: str) -> bool:
        self.calls.append((login, password))
        return login == self.valid_login and password == "123"


class LoginPreferencesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_data_dir = os.environ.get("CONTROLE_PRODUCAO_DATA_DIR")
        os.environ["CONTROLE_PRODUCAO_DATA_DIR"] = self.temp_dir.name
        save_login_preferences("", False)

    def tearDown(self):
        if self.old_data_dir is None:
            os.environ.pop("CONTROLE_PRODUCAO_DATA_DIR", None)
        else:
            os.environ["CONTROLE_PRODUCAO_DATA_DIR"] = self.old_data_dir
        self.temp_dir.cleanup()

    def test_first_open_does_not_prefill_admin_or_password(self):
        dialog = LoginDialog(FakeAuthService())
        self.assertEqual(dialog.login.text(), "")
        self.assertEqual(dialog.password.text(), "")
        self.assertFalse(dialog.remember_user.isChecked())

    def test_successful_login_with_remember_user_saves_only_login(self):
        dialog = LoginDialog(FakeAuthService(valid_login="maria"))
        dialog.login.setText("maria")
        dialog.password.setText("senha-nao-salvar")
        self.assertFalse(dialog.service.authenticate("maria", "senha-nao-salvar"))
        dialog.password.setText("123")
        dialog.remember_user.setChecked(True)

        dialog.try_login()

        saved = load_login_preferences()
        self.assertTrue(saved["remember_user"])
        self.assertEqual(saved["last_user"], "maria")
        self.assertNotIn("123", get_login_preferences_path().read_text(encoding="utf-8"))

        next_dialog = LoginDialog(FakeAuthService(valid_login="maria"))
        self.assertEqual(next_dialog.login.text(), "maria")
        self.assertEqual(next_dialog.password.text(), "")
        self.assertTrue(next_dialog.remember_user.isChecked())

    def test_successful_login_without_remember_user_clears_previous_login(self):
        save_login_preferences("usuario_antigo", True)
        self.assertTrue(get_login_preferences_path().exists())

        dialog = LoginDialog(FakeAuthService(valid_login="carlos"))
        dialog.login.setText("carlos")
        dialog.password.setText("123")
        dialog.remember_user.setChecked(False)

        dialog.try_login()

        self.assertFalse(get_login_preferences_path().exists())
        next_dialog = LoginDialog(FakeAuthService(valid_login="carlos"))
        self.assertEqual(next_dialog.login.text(), "")
        self.assertEqual(next_dialog.password.text(), "")
        self.assertFalse(next_dialog.remember_user.isChecked())

    def test_failed_login_does_not_change_saved_user(self):
        save_login_preferences("usuario_salvo", True)

        dialog = LoginDialog(FakeAuthService(valid_login="correto"))
        dialog.login.setText("errado")
        dialog.password.setText("123")
        dialog.remember_user.setChecked(False)

        dialog.try_login()

        saved = load_login_preferences()
        self.assertEqual(saved["last_user"], "usuario_salvo")
        self.assertTrue(saved["remember_user"])


if __name__ == "__main__":
    unittest.main()
