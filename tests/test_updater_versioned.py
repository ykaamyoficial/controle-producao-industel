from __future__ import annotations

import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from app.updater import versions as v
from app.updater.contract import UpdateRequest
from app.updater.status import PHASE_FAILED, PHASE_ROLLED_BACK, PHASE_STAGED, PHASE_SUCCESS, read_status
from app.updater.versioned import VersionedConfig, VersionedUpdater


def _make_zip(path: Path, version: str, *, with_exe: bool = True, marker: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        if with_exe:
            archive.writestr(v.APP_EXECUTABLE_NAME, "exe")
        archive.writestr("_internal/lib.dll", "dll")
        archive.writestr("VERSION", (marker or version) + "\n")
    return path


class VersionedUpdaterTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "install"
        old = self.root / "versions" / "2.8.0"
        old.mkdir(parents=True)
        (old / v.APP_EXECUTABLE_NAME).write_text("old")
        (self.root / "ControleProducao.exe").write_text("launcher")
        v.write_pointer(self.root, "2.8.0")
        self.status_dir = self.tmp / "status"
        self.downloads = self.tmp / "downloads"
        self.launch = mock.Mock(return_value=1234)
        self.stopper = mock.Mock(return_value=[])
        self.handshake = mock.Mock(return_value=True)

    def _request(self, package: Path, **overrides) -> UpdateRequest:
        data = dict(
            request_id="req1", current_version="2.8.0", target_version="2.9.0",
            package_url_or_source=str(package), install_dir=str(self.root),
            executable_path=str(self.root / "ControleProducao.exe"), parent_pid=4321,
            package_expected_hash=hashlib.sha256(package.read_bytes()).hexdigest(),
            package_expected_size=package.stat().st_size,
        )
        data.update(overrides)
        return UpdateRequest(**data)

    def _updater(self, **overrides) -> VersionedUpdater:
        kwargs = dict(
            lock_path=self.tmp / ".lock", status_directory=self.status_dir,
            config=VersionedConfig(min_free_space_mb=1, rename_retries=1, rename_retry_delay_seconds=0),
            process_stopper=self.stopper, process_launch=self.launch, handshake_waiter=self.handshake,
        )
        kwargs.update(overrides)
        return VersionedUpdater(**kwargs)

    def _stage(self, package: Path | None = None, **request_overrides):
        package = package or _make_zip(self.tmp / "pkg.zip", "2.9.0")
        request = self._request(package, **request_overrides)
        return request, self._updater().stage(request, download_dir=self.downloads)

    # -- stage -----------------------------------------------------------

    def test_stage_installs_new_version_without_touching_active_one(self):
        request, status = self._stage()
        self.assertEqual(status.phase, PHASE_STAGED)
        self.assertTrue(v.app_executable(self.root, "2.9.0").is_file())
        self.assertEqual(v.read_pointer(self.root).version, "2.8.0")
        self.assertTrue(v.app_executable(self.root, "2.8.0").is_file())
        self.assertFalse(v.pending_version_dir(self.root, "2.9.0").exists())
        self.assertEqual(read_status("req1", directory=self.status_dir).phase, PHASE_STAGED)
        self.stopper.assert_not_called()
        self.launch.assert_not_called()

    def test_stage_rejects_hash_mismatch(self):
        package = _make_zip(self.tmp / "pkg.zip", "2.9.0")
        _, status = self._stage(package, package_expected_hash="0" * 64)
        self.assertEqual(status.phase, PHASE_FAILED)
        self.assertIn("INVALID_HASH", status.error)
        self.assertFalse(v.version_dir(self.root, "2.9.0").exists())

    def test_stage_rejects_legacy_flat_package_without_app_executable(self):
        package = _make_zip(self.tmp / "legacy.zip", "2.9.0", with_exe=False)
        _, status = self._stage(package)
        self.assertEqual(status.phase, PHASE_FAILED)
        self.assertIn(v.APP_EXECUTABLE_NAME, status.error)
        self.assertEqual(v.list_installed_versions(self.root), ["2.8.0"])
        self.assertFalse(v.pending_version_dir(self.root, "2.9.0").exists())

    def test_stage_rejects_version_marker_mismatch(self):
        package = _make_zip(self.tmp / "pkg.zip", "2.9.0", marker="2.7.0")
        _, status = self._stage(package)
        self.assertEqual(status.phase, PHASE_FAILED)
        self.assertIn("diverge", status.error)

    def test_stage_fails_when_disk_is_full(self):
        package = _make_zip(self.tmp / "pkg.zip", "2.9.0")
        request = self._request(package)
        usage = mock.Mock(return_value=mock.Mock(free=1024))
        status = self._updater(disk_usage_fn=usage, config=VersionedConfig(min_free_space_mb=400)).stage(request, download_dir=self.downloads)
        self.assertEqual(status.phase, PHASE_FAILED)
        self.assertIn("Espaco livre insuficiente", status.error)

    def test_stage_is_idempotent_when_version_already_present(self):
        self._stage()
        _, status = self._stage()
        self.assertEqual(status.phase, PHASE_STAGED)

    def test_stage_replaces_stale_pending_directory(self):
        stale = v.pending_version_dir(self.root, "2.9.0")
        stale.mkdir(parents=True)
        (stale / "lixo.txt").write_text("x")
        _, status = self._stage()
        self.assertEqual(status.phase, PHASE_STAGED)
        self.assertFalse((v.version_dir(self.root, "2.9.0") / "lixo.txt").exists())

    # -- activate --------------------------------------------------------

    def test_activate_flips_pointer_stops_processes_and_confirms(self):
        request, _ = self._stage()
        status = self._updater().activate(request)
        self.assertEqual(status.phase, PHASE_SUCCESS)
        pointer = v.read_pointer(self.root)
        self.assertEqual((pointer.version, pointer.previous_version), ("2.9.0", "2.8.0"))
        self.assertEqual(self.stopper.call_args.args[0], self.root)
        launched = self.launch.call_args.args
        self.assertEqual(launched[0], self.root / "ControleProducao.exe")
        self.assertEqual(launched[1][:2], ["--post-update", "req1"])
        self.assertIn("2.8.0", v.list_installed_versions(self.root))

    def test_activate_succeeds_even_if_a_process_refuses_to_die(self):
        request, _ = self._stage()
        self.stopper.return_value = [999]
        self.assertEqual(self._updater().activate(request).phase, PHASE_SUCCESS)
        self.assertEqual(v.read_pointer(self.root).version, "2.9.0")

    def test_activate_rolls_back_pointer_when_handshake_missing(self):
        request, _ = self._stage()
        self.handshake.return_value = False
        status = self._updater().activate(request)
        self.assertEqual(status.phase, PHASE_ROLLED_BACK)
        self.assertEqual(v.read_pointer(self.root).version, "2.8.0")
        self.assertEqual(self.launch.call_count, 2)
        self.assertEqual(self.stopper.call_args.args[0], v.version_dir(self.root, "2.9.0"))

    def test_activate_rolls_back_when_launch_fails(self):
        request, _ = self._stage()
        self.launch.side_effect = [OSError("boom"), 99]
        status = self._updater().activate(request)
        self.assertEqual(status.phase, PHASE_ROLLED_BACK)
        self.assertEqual(v.read_pointer(self.root).version, "2.8.0")

    def test_activate_fails_cleanly_when_version_not_staged(self):
        package = _make_zip(self.tmp / "pkg.zip", "2.9.0")
        status = self._updater().activate(self._request(package))
        self.assertEqual(status.phase, PHASE_FAILED)
        self.assertEqual(v.read_pointer(self.root).version, "2.8.0")
        self.stopper.assert_not_called()

    def test_activate_clears_quit_request_afterwards(self):
        request, _ = self._stage()
        with mock.patch("app.updater.versioned.quit_signal") as quit_signal:
            self._updater().activate(request)
        quit_signal.request_quit.assert_called_once_with("req1")
        quit_signal.clear_quit_request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
