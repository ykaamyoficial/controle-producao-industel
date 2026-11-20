from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.main import show_pending_update_failure_notice
from app.services.update_outcome_notice import pending_update_failure_notice
from app.updater.status import (
    PHASE_FAILED, PHASE_ROLLED_BACK, PHASE_STAGED, PHASE_SUCCESS, UpdateStatus, write_status,
)


class PendingUpdateFailureNoticeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _write(self, request_id, phase, percent=100, message="msg", error=None, mtime=None):
        write_status(UpdateStatus(request_id, phase, percent, message, error), directory=self.dir)
        if mtime is not None:
            path = self.dir / f"{request_id}.json"
            os.utime(path, (mtime, mtime))

    def test_rolled_back_is_reported_once_with_message_and_error(self):
        self._write("r1", PHASE_ROLLED_BACK, message="A nova versao nao abriu corretamente; a versao 2.8.0 foi restaurada.", error="handshake ausente")
        text = pending_update_failure_notice(self.dir)
        self.assertIn("a versao 2.8.0 foi restaurada", text)
        self.assertIn("handshake ausente", text)
        self.assertTrue((self.dir / "r1.shown").exists())
        self.assertIsNone(pending_update_failure_notice(self.dir))

    def test_failure_after_app_closed_is_reported(self):
        self._write("r1", PHASE_FAILED, 100, message="Sem como restaurar.")
        self.assertIn("Sem como restaurar", pending_update_failure_notice(self.dir))

    def test_failure_with_app_still_open_was_already_shown_by_the_dialog(self):
        self._write("r1", PHASE_FAILED, 5, message="sem permissao")
        self.assertIsNone(pending_update_failure_notice(self.dir))

    def test_success_and_staged_are_not_reported(self):
        self._write("r1", PHASE_SUCCESS)
        self.assertIsNone(pending_update_failure_notice(self.dir))
        self._write("r2", PHASE_STAGED)
        self.assertIsNone(pending_update_failure_notice(self.dir))

    def test_old_status_is_ignored(self):
        self._write("r1", PHASE_ROLLED_BACK, mtime=1000.0)
        self.assertIsNone(pending_update_failure_notice(self.dir, now=1000.0 + 901, max_age_seconds=900))
        self.assertIsNotNone(pending_update_failure_notice(self.dir, now=1000.0 + 899, max_age_seconds=900))

    def test_only_the_newest_status_counts(self):
        self._write("old", PHASE_ROLLED_BACK, mtime=1000.0)
        self._write("new", PHASE_SUCCESS, mtime=1100.0)
        self.assertIsNone(pending_update_failure_notice(self.dir, now=1200.0))

    def test_missing_or_empty_directory(self):
        self.assertIsNone(pending_update_failure_notice(self.dir))
        self.assertIsNone(pending_update_failure_notice(self.dir / "nao-existe"))


class ShowPendingNoticeTests(unittest.TestCase):
    def test_warns_with_notice_text(self):
        warn = mock.Mock()
        self.assertTrue(show_pending_update_failure_notice("janela", notice_provider=lambda: "texto", warn=warn))
        warn.assert_called_once_with("janela", "Atualizacao do sistema", "texto")

    def test_silent_without_notice(self):
        warn = mock.Mock()
        self.assertFalse(show_pending_update_failure_notice(notice_provider=lambda: None, warn=warn))
        warn.assert_not_called()

    def test_never_raises(self):
        def boom():
            raise RuntimeError("x")

        self.assertFalse(show_pending_update_failure_notice(notice_provider=boom, warn=mock.Mock()))

    def test_default_provider_is_skipped_when_not_packaged(self):
        with mock.patch("app.services.app_paths.is_packaged", return_value=False), \
                mock.patch("app.services.update_outcome_notice.pending_update_failure_notice") as provider:
            self.assertFalse(show_pending_update_failure_notice(warn=mock.Mock()))
        provider.assert_not_called()


class MainNoticeOrderTests(unittest.TestCase):
    def test_notice_is_shown_before_bootstrap_compatibility_gate_and_login(self):
        import sys

        import app.main as main_module

        calls: list[tuple] = []
        saved_hook = sys.excepthook
        self.addCleanup(lambda: setattr(sys, "excepthook", saved_hook))
        with mock.patch.object(main_module, "configure_logging"),                 mock.patch.object(main_module, "confirm_post_update_handshake"),                 mock.patch.object(main_module, "configure_windows_taskbar_icon"),                 mock.patch.object(main_module, "QApplication"),                 mock.patch.object(main_module, "app_icon"),                 mock.patch("app.services.notifier_agent.acquire_main_app_mutex"),                 mock.patch("app.ui.fonts.load_app_fonts"),                 mock.patch("app.ui.wheel_guard.install_combo_wheel_guard"),                 mock.patch("app.ui.components.floating_chrome.install_floating_chrome"),                 mock.patch("app.ui.components.message_boxes.install_message_boxes", side_effect=lambda: calls.append(("boxes",))),                 mock.patch.object(main_module, "show_pending_update_failure_notice", side_effect=lambda *a, **k: calls.append(("notice", a))),                 mock.patch.object(main_module, "run_startup_bootstrap", side_effect=lambda: calls.append(("bootstrap",)) or False):
            self.assertEqual(main_module.main(), 0)
        self.assertEqual(calls, [("boxes",), ("notice", (None,)), ("bootstrap",)])


if __name__ == "__main__":
    unittest.main()
