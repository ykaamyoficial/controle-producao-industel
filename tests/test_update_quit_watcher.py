from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.services.update_quit_watcher import install_quit_watcher  # noqa: E402


def _spin(milliseconds: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


class QuitWatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_calls_on_quit_once_when_request_appears(self):
        calls: list[int] = []
        state = {"requested": False}
        timer = install_quit_watcher(self.app, lambda: calls.append(1), interval_ms=10, started_at=0.0, checker=lambda _t: state["requested"])
        self.addCleanup(timer.stop)
        _spin(60)
        self.assertEqual(calls, [])
        state["requested"] = True
        _spin(120)
        self.assertEqual(calls, [1])

    def test_passes_process_start_time_to_checker(self):
        seen: list[float] = []
        timer = install_quit_watcher(self.app, lambda: None, interval_ms=10, started_at=123.5, checker=lambda t: seen.append(t) or False)
        self.addCleanup(timer.stop)
        _spin(60)
        self.assertEqual(set(seen), {123.5})


if __name__ == "__main__":
    unittest.main()
