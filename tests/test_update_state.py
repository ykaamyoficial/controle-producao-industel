from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import update_state


class UpdateStateTests(unittest.TestCase):
    def test_pending_update_is_completed_when_current_version_reaches_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending_path = Path(tmp) / "pending_update.json"
            with patch.object(update_state, "pending_update_path", return_value=pending_path):
                update_state.write_pending_update(
                    target_version="2.5.1",
                    current_version="2.5.0",
                    installer_path=Path(tmp) / "setup.exe",
                    sha256="abc",
                    backup_path=None,
                )
                result = update_state.evaluate_pending_update("2.5.1")
                self.assertEqual(result["status"], "completed")
                self.assertFalse(pending_path.exists())

    def test_pending_update_is_reported_when_version_did_not_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            pending_path = Path(tmp) / "pending_update.json"
            with patch.object(update_state, "pending_update_path", return_value=pending_path):
                update_state.write_pending_update(
                    target_version="2.5.2",
                    current_version="2.5.1",
                    installer_path=Path(tmp) / "setup.exe",
                )
                result = update_state.evaluate_pending_update("2.5.1")
                self.assertEqual(result["status"], "failed_or_incomplete")
                self.assertEqual(result["target_version"], "2.5.2")
                self.assertTrue(pending_path.exists())


if __name__ == "__main__":
    unittest.main()
