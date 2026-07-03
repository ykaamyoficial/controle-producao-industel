from __future__ import annotations

import tempfile
import threading
import time
import unittest
import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from app.services.backend_adapter import BackendService
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

    def test_database_switch_validates_candidate_and_backs_up_current_first(self):
        with tempfile.TemporaryDirectory() as temp:
            current = Path(temp) / "current.db"
            candidate = Path(temp) / "candidate.db"
            current.touch()
            candidate.touch()
            service = BackendService.__new__(BackendService)
            service.config = {"db_path": str(current), "backup_dir": str(Path(temp) / "backups")}
            with patch("app.services.backend_adapter.require_healthy_database") as validate, patch(
                "app.services.backend_adapter.safe_backup"
            ) as backup, patch("app.services.backend_adapter.save_app_config") as save:
                service.choose_database(str(candidate))
            validate.assert_called_once_with(candidate, require_schema=True)
            backup.assert_called_once()
            save.assert_called_once()
            self.assertEqual(service.config["db_path"], str(candidate))


if __name__ == "__main__":
    unittest.main()
