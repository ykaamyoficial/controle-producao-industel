from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.updater import handshake


class HandshakeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # app.updater.paths.updater_root_dir() resolve a raiz real via
        # app.services.app_paths.get_app_data_dir() -- isolamos o teste
        # substituindo o nome ja importado no modulo de paths do updater,
        # nunca escrevendo em app/data/ de verdade durante a suite.
        patcher = patch("app.updater.paths.get_app_data_dir", return_value=Path(self._tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_wait_without_marker_times_out(self):
        self.assertFalse(handshake.wait_for_handshake("req-x", timeout_seconds=0.3, poll_interval_seconds=0.1))

    def test_write_then_wait_succeeds_immediately(self):
        handshake.write_handshake_marker("req-y")
        self.assertTrue(handshake.wait_for_handshake("req-y", timeout_seconds=0.3, poll_interval_seconds=0.1))

    def test_clear_marker_removes_it(self):
        handshake.write_handshake_marker("req-z")
        handshake.clear_handshake_marker("req-z")
        self.assertFalse(handshake.handshake_marker_path("req-z").exists())


if __name__ == "__main__":
    unittest.main()
