from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.services.backend_adapter import AppError
from app.ui import date_warnings


def _warning(*messages) -> AppError:
    warnings = [{"code": "X", "field": "f", "message": m} for m in messages]
    return AppError("Há avisos", error_code="DATE_CONFIRMATION_REQUIRED", details={"warnings": warnings})


class DateWarningsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_messages_come_from_details(self):
        self.assertEqual(date_warnings.date_warning_messages(_warning("a", "b")), ["a", "b"])
        self.assertEqual(date_warnings.date_warning_messages(AppError("Há avisos", error_code="DATE_CONFIRMATION_REQUIRED")), ["Há avisos"])
        self.assertIsNone(date_warnings.date_warning_messages(AppError("x", error_code="OUTRO")))
        self.assertIsNone(date_warnings.date_warning_messages(ValueError("x")))

    def test_confirm_resends_and_decline_calls_back(self):
        resent, declined = [], []
        with patch.object(date_warnings, "ask_date_confirmation", return_value=True) as ask:
            self.assertTrue(date_warnings.handle_date_warning(None, _warning("a"), lambda: resent.append(1), lambda: declined.append(1)))
        ask.assert_called_once_with(None, ["a"])
        self.assertEqual((resent, declined), ([1], []))
        with patch.object(date_warnings, "ask_date_confirmation", return_value=False):
            self.assertTrue(date_warnings.handle_date_warning(None, _warning("a"), lambda: resent.append(2), lambda: declined.append(2)))
        self.assertEqual((resent, declined), ([1], [2]))

    def test_other_errors_are_not_handled(self):
        with patch.object(date_warnings, "ask_date_confirmation") as ask:
            self.assertFalse(date_warnings.handle_date_warning(None, AppError("x", error_code="OUTRO"), lambda: None))
        ask.assert_not_called()

    def test_box_has_the_two_buttons_and_reports_the_choice(self):
        seen = {}

        def fake_exec(box):
            seen["texts"] = [b.text() for b in box.buttons()]
            seen["body"] = box.text()
            seen["default"] = box.defaultButton().text()
            box.done(0)
            return 0

        with patch.object(date_warnings.QMessageBox, "exec", fake_exec):
            self.assertFalse(date_warnings.ask_date_confirmation(None, ["Domingo.", "Feriado."]))
        self.assertEqual(seen["texts"], ["Marcar mesmo assim", "Escolher outra data"])
        self.assertEqual(seen["default"], "Escolher outra data")
        self.assertIn("Domingo.", seen["body"])
        self.assertIn("Feriado.", seen["body"])


if __name__ == "__main__":
    unittest.main()
