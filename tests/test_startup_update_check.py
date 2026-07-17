from __future__ import annotations

import unittest
from unittest.mock import patch

from app.main import run_startup_update_check


class DummyDialog:
    calls: list[dict] = []

    def __init__(self, update_info: dict, parent=None):
        self.update_info = update_info
        self.parent = parent
        DummyDialog.calls.append(update_info)

    def exec(self):
        return 0


class StartupUpdateCheckTests(unittest.TestCase):
    def setUp(self):
        DummyDialog.calls.clear()
        self.pending_patcher = patch("app.main.evaluate_pending_update", return_value={"has_pending": False, "status": "none"})
        self.pending_patcher.start()

    def tearDown(self):
        self.pending_patcher.stop()

    def test_startup_update_check_does_not_raise_on_network_error(self):
        def failing_checker(*, timeout: int):
            raise OSError("sem internet")

        self.assertTrue(run_startup_update_check(checker=failing_checker, dialog_factory=DummyDialog))
        self.assertEqual(DummyDialog.calls, [])

    def test_startup_update_check_ignores_error_result(self):
        def checker(*, timeout: int):
            return {"update_available": False, "error": "ssl", "error_kind": "ssl"}

        self.assertTrue(run_startup_update_check(checker=checker, dialog_factory=DummyDialog))
        self.assertEqual(DummyDialog.calls, [])

    def test_startup_update_check_opens_dialog_when_update_is_available(self):
        def checker(*, timeout: int):
            return {"update_available": True, "latest_version": "2.5.0", "current_version": "2.4.9"}

        self.assertTrue(run_startup_update_check(checker=checker, dialog_factory=DummyDialog))
        self.assertEqual(DummyDialog.calls[0]["latest_version"], "2.5.0")

    def test_startup_update_check_skips_dialog_when_system_is_current(self):
        def checker(*, timeout: int):
            return {"update_available": False, "latest_version": "2.4.9", "current_version": "2.4.9"}

        self.assertTrue(run_startup_update_check(checker=checker, dialog_factory=DummyDialog))
        self.assertEqual(DummyDialog.calls, [])


if __name__ == "__main__":
    unittest.main()
