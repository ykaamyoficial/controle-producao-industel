from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.ui.main_window import MainWindow


class _DeadThread:
    def isRunning(self):
        raise RuntimeError("libshiboken: Internal C++ object (PySide6.QtCore.QThread) already deleted.")


class WorkerRunningTests(unittest.TestCase):
    def _check(self, thread):
        holder = SimpleNamespace(_notification_poll_thread=thread)
        return MainWindow._worker_running(holder, "_notification_poll_thread"), holder

    def test_no_thread_is_not_running(self):
        self.assertEqual(self._check(None)[0], False)

    def test_live_thread_reports_its_state(self):
        self.assertTrue(self._check(SimpleNamespace(isRunning=lambda: True))[0])
        self.assertFalse(self._check(SimpleNamespace(isRunning=lambda: False))[0])

    def test_destroyed_thread_is_treated_as_finished_and_forgotten(self):
        running, holder = self._check(_DeadThread())
        self.assertFalse(running)
        self.assertIsNone(holder._notification_poll_thread)

    def test_missing_attribute_is_not_running(self):
        self.assertFalse(MainWindow._worker_running(SimpleNamespace(), "_notification_poll_thread"))


if __name__ == "__main__":
    unittest.main()
