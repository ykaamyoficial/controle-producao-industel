from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from app.services import notifier_credentials as creds
from app.ui.notifier_status_widget import NotifierStatusWidget, describe_status


def _ts(day: int, hour: int, minute: int) -> float:
    return datetime(2026, 10, day, hour, minute).timestamp()


class DescribeStatusTests(unittest.TestCase):
    def test_not_running(self):
        text = describe_status(False, {"owner": "Joao"})
        self.assertIn("desligados", text)
        self.assertNotIn("Joao", text)

    def test_running_without_owner_waits_for_login(self):
        self.assertIn("aguardando um login", describe_status(True, {}))

    def test_running_with_owner_unread_and_last_toast_today(self):
        text = describe_status(
            True,
            {"owner": "Joao", "unread": 3, "last_toast_at": _ts(13, 14, 10)},
            now=_ts(13, 16, 0),
        )
        self.assertIn("ligados para Joao", text)
        self.assertIn("3 nao lida(s)", text)
        self.assertIn("ultimo aviso as 14:10", text)

    def test_last_toast_on_another_day_shows_the_date(self):
        text = describe_status(True, {"owner": "Joao", "last_toast_at": _ts(10, 9, 5)}, now=_ts(13, 16, 0))
        self.assertIn("10/10 09:05", text)
        self.assertIn("nenhuma nao lida", text)

    def test_no_toast_yet(self):
        self.assertIn("nenhum aviso mostrado ainda", describe_status(True, {"owner": "Joao"}))


class NotifierStatusWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_shows_status_file_and_hides_button_when_running(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {creds.NOTIFIER_DIR_ENV: temp_dir}
        ), patch("app.services.notifier_agent.is_notifier_running", return_value=True):
            creds.write_status(running=True, owner="Maria", unread=2)
            widget = NotifierStatusWidget()
            self.assertIn("ligados para Maria", widget.label.text())
            self.assertTrue(widget.turn_on_btn.isHidden())

    def test_offers_turn_on_when_stopped(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ, {creds.NOTIFIER_DIR_ENV: temp_dir}
        ), patch("app.services.notifier_agent.is_notifier_running", return_value=False):
            widget = NotifierStatusWidget()
            self.assertIn("desligados", widget.label.text())
            self.assertFalse(widget.turn_on_btn.isHidden())


if __name__ == "__main__":
    unittest.main()
