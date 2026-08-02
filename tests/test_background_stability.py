from __future__ import annotations

import threading
import time
import unittest
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from app.services.backend_adapter import AppError, BackendService
from app.ui.background_worker import start_worker


class BackgroundStabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_slow_operation_does_not_block_main_event_loop(self):
        loop = QEventLoop()
        main_thread = threading.get_ident()
        observed = {"timer": False, "worker_thread": main_thread}

        def slow_operation():
            observed["worker_thread"] = threading.get_ident()
            time.sleep(0.08)
            return "ok"

        QTimer.singleShot(10, lambda: observed.__setitem__("timer", True))
        thread = start_worker(self.app, slow_operation, lambda _value: loop.quit(), lambda _error: loop.quit())
        QTimer.singleShot(2000, loop.quit)
        loop.exec()
        thread.quit()
        thread.wait(1000)
        self.assertTrue(observed["timer"])
        self.assertNotEqual(observed["worker_thread"], main_thread)

    def test_database_switch_is_disabled_in_postgresql_only_runtime(self):
        service = BackendService.__new__(BackendService)
        service.config = {"desktop_api": {"base_url": "http://127.0.0.1:8000"}}

        with self.assertRaisesRegex(AppError, "API/PostgreSQL"):
            service.choose_database("candidate.db")


if __name__ == "__main__":
    unittest.main()
