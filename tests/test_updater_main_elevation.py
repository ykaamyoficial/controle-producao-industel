from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from app.updater import __main__ as updater_main
from app.updater import versions as v
from app.updater.status import PHASE_ACTIVATING, PHASE_SUCCESS, UpdateStatus


class CanWritePointerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_writable_pointer_is_true_and_content_is_untouched(self):
        v.write_pointer(self.root, "2.8.0")
        before = v.pointer_path(self.root).read_bytes()
        self.assertTrue(updater_main._can_write_pointer(self.root))
        self.assertEqual(v.pointer_path(self.root).read_bytes(), before)

    def test_missing_pointer_falls_back_to_directory_check(self):
        self.assertTrue(updater_main._can_write_pointer(self.root))
        self.assertFalse(updater_main._can_write_pointer(self.root / "nao-existe" / "x"))

    def test_read_only_pointer_is_false(self):
        v.write_pointer(self.root, "2.8.0")
        pointer = v.pointer_path(self.root)
        pointer.chmod(stat.S_IREAD)
        self.addCleanup(lambda: pointer.chmod(stat.S_IWRITE | stat.S_IREAD))
        self.assertFalse(updater_main._can_write_pointer(self.root))

    @unittest.skipUnless(os.name == "nt", "ACL do Windows")
    def test_pointer_denied_by_acl_is_false_even_though_os_access_says_yes(self):
        v.write_pointer(self.root, "2.8.0")
        pointer = v.pointer_path(self.root)
        user = os.environ.get("USERNAME", "")
        denied = subprocess.run(["icacls", str(pointer), "/deny", f"{user}:(W,WD,AD,DC)"], capture_output=True, text=True)
        if denied.returncode != 0:
            self.skipTest(f"icacls indisponivel: {denied.stdout}{denied.stderr}")
        self.addCleanup(lambda: subprocess.run(["icacls", str(pointer), "/remove:d", user], capture_output=True))
        self.assertFalse(updater_main._can_write_pointer(self.root))


class RunVersionedElevationTests(unittest.TestCase):
    def setUp(self):
        self.request = mock.Mock(install_dir="C:/instalacao", request_id="req1")
        self.updater_cls = mock.Mock()
        self.updater_cls.return_value.activate.return_value = UpdateStatus("req1", PHASE_SUCCESS, 100, "ok")
        patcher = mock.patch.multiple(
            updater_main, VersionedUpdater=self.updater_cls, lock_path=mock.Mock(return_value=Path("x.lock")),
            download_dir=mock.Mock(return_value=Path("dl")),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, *, admin: bool, can_write: bool, no_elevate: bool, relaunch=True, stage=False, call_elevate=False):
        args = Namespace(
            stage=stage, activate=not stage, no_elevate=no_elevate,
            app_exit_timeout_seconds=60.0, handshake_timeout_seconds=30.0,
        )
        argv = ["--request", "r.json", "--activate"]
        with mock.patch.object(updater_main, "is_admin", return_value=admin), \
                mock.patch.object(updater_main, "_can_write_pointer", return_value=can_write), \
                mock.patch.object(updater_main, "is_writable", return_value=can_write), \
                mock.patch.object(updater_main, "relaunch_elevated", return_value=relaunch) as relaunch_mock:
            code = updater_main._run_versioned(self.request, args, argv, mock.Mock())
            if call_elevate:  # a lambda resolve relaunch_elevated na hora da chamada: tem de ser dentro do patch
                self.elevate_result = self.updater_cls.call_args.kwargs["elevate"]()
        return code, relaunch_mock

    def test_precheck_elevates_when_not_admin_and_cannot_write(self):
        code, relaunch = self._run(admin=False, can_write=False, no_elevate=False)
        self.assertEqual(code, 0)
        relaunch.assert_called_once_with(["--request", "r.json", "--activate"])
        self.updater_cls.assert_not_called()

    def test_no_elevate_disables_precheck_and_last_resort(self):
        code, relaunch = self._run(admin=False, can_write=False, no_elevate=True)
        relaunch.assert_not_called()
        self.assertIsNone(self.updater_cls.call_args.kwargs["elevate"])
        self.assertEqual(code, 0)

    def test_admin_has_no_last_resort_elevation(self):
        _, relaunch = self._run(admin=True, can_write=False, no_elevate=False)
        relaunch.assert_not_called()
        self.assertIsNone(self.updater_cls.call_args.kwargs["elevate"])

    def test_non_admin_with_writable_pointer_gets_last_resort_elevation_with_same_argv(self):
        _, relaunch = self._run(admin=False, can_write=True, no_elevate=False, call_elevate=True)
        self.assertTrue(self.elevate_result)
        relaunch.assert_called_once_with(["--request", "r.json", "--activate"])

    def test_waiting_for_elevated_process_is_not_a_failure_exit(self):
        self.updater_cls.return_value.activate.return_value = UpdateStatus("req1", PHASE_ACTIVATING, 5, "Aguardando permissao de administrador")
        code, _ = self._run(admin=False, can_write=True, no_elevate=False)
        self.assertEqual(code, 0)


class NoElevateFlagTests(unittest.TestCase):
    def _main(self, extra: list[str]) -> Namespace:
        captured = {}

        def fake_run(request, args, argv, log):
            captured["args"] = args
            return 0

        with mock.patch.object(updater_main, "_configure_logging", return_value=mock.Mock()), \
                mock.patch.object(updater_main.UpdateRequest, "load", return_value=mock.Mock(install_dir="x")), \
                mock.patch.object(updater_main, "_run_versioned", side_effect=fake_run):
            self.assertEqual(updater_main.main(["--request", "r.json", "--activate", *extra]), 0)
        return captured["args"]

    def test_flag_parsed(self):
        self.assertTrue(self._main(["--no-elevate"]).no_elevate)

    def test_flag_defaults_to_off(self):
        self.assertFalse(self._main([]).no_elevate)

    def test_flag_blocks_legacy_elevation_too(self):
        with mock.patch.object(updater_main, "_configure_logging", return_value=mock.Mock()), \
                mock.patch.object(updater_main.UpdateRequest, "load", return_value=mock.Mock(install_dir="x")), \
                mock.patch.object(updater_main, "is_admin", return_value=False), \
                mock.patch.object(updater_main, "is_writable", return_value=False), \
                mock.patch.object(updater_main, "relaunch_elevated") as relaunch, \
                mock.patch.object(updater_main, "UpdateJournalStore", side_effect=RuntimeError("parou aqui")):
            with self.assertRaises(RuntimeError):
                updater_main.main(["--request", "r.json", "--no-elevate"])
        relaunch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
