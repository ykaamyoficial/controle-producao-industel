from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.main import confirm_post_update_handshake
from app.updater import handshake


class ConfirmPostUpdateHandshakeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = patch("app.updater.paths.get_app_data_dir", return_value=Path(self._tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_no_flag_does_nothing(self):
        confirm_post_update_handshake([])
        self.assertFalse(handshake.handshake_marker_path("anything").exists())

    def test_flag_with_request_id_writes_marker(self):
        confirm_post_update_handshake(["--post-update", "req-42"])
        self.assertTrue(handshake.handshake_marker_path("req-42").exists())

    def test_flag_without_request_id_does_not_raise(self):
        confirm_post_update_handshake(["--post-update"])  # nao deve lancar excecao


if __name__ == "__main__":
    unittest.main()
