from __future__ import annotations

import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from app.updater import versions as v
from app.updater.contract import UpdateRequest
from app.updater.lock import UpdaterLock
from app.updater.status import PHASE_ACTIVATING, PHASE_FAILED, PHASE_ROLLED_BACK, PHASE_STAGED, PHASE_SUCCESS, read_status, write_status as real_write_status
from app.updater.versioned import VersionedConfig, VersionedUpdater
from tests.test_updater_versions import folder_without_create_permission


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
            config=VersionedConfig(min_free_space_mb=1, rename_retries=1, rename_retry_delay_seconds=0, closing_grace_seconds=0),
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

    def test_activate_works_without_permission_to_create_files_in_install_root(self):
        request, _ = self._stage()
        with folder_without_create_permission(self.root):
            status = self._updater().activate(request)
        self.assertEqual(status.phase, PHASE_SUCCESS)
        self.assertEqual(v.read_pointer(self.root).version, "2.9.0")

    def test_rollback_restores_pointer_without_permission_to_create_files_in_install_root(self):
        request, _ = self._stage()
        self.handshake.return_value = False
        with folder_without_create_permission(self.root):
            status = self._updater().activate(request)
        self.assertEqual(status.phase, PHASE_ROLLED_BACK)
        self.assertEqual(v.read_pointer(self.root).version, "2.8.0")

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

    # -- activate: ponteiro nao gravavel, elevacao, ordem, rollback ---------------

    def _pointer_bytes(self) -> bytes:
        return v.pointer_path(self.root).read_bytes()

    def test_activate_pointer_not_writable_fails_without_closing_the_app(self):
        request, _ = self._stage()
        before = self._pointer_bytes()
        with mock.patch("app.updater.versioned.quit_signal") as quit_signal,                 mock.patch("app.updater.versioned.versions.write_pointer", side_effect=PermissionError("negado")):
            status = self._updater().activate(request)
        self.assertEqual(status.phase, PHASE_FAILED)
        self.assertIn("continua aberto", status.message)
        self.assertIn("current.json", status.message)
        self.assertIn("negado", status.error)
        quit_signal.request_quit.assert_not_called()
        self.stopper.assert_not_called()
        self.launch.assert_not_called()
        self.assertEqual(self._pointer_bytes(), before)
        self.assertEqual(read_status("req1", directory=self.status_dir).phase, PHASE_FAILED)

    def test_activate_fails_when_pointer_does_not_reflect_target_after_write(self):
        request, _ = self._stage()
        with mock.patch("app.updater.versioned.quit_signal") as quit_signal,                 mock.patch("app.updater.versioned.versions.write_pointer"):
            status = self._updater().activate(request)
        self.assertEqual(status.phase, PHASE_FAILED)
        quit_signal.request_quit.assert_not_called()
        self.stopper.assert_not_called()

    def test_activate_direct_write_fallback_still_works_when_temp_cannot_be_created(self):
        request, _ = self._stage()
        with folder_without_create_permission(self.root):
            status = self._updater().activate(request)
        self.assertEqual(status.phase, PHASE_SUCCESS)
        self.assertEqual(v.read_pointer(self.root).version, "2.9.0")

    def test_activate_elevates_as_last_resort_and_releases_lock_without_failed(self):
        request, _ = self._stage()
        seen: dict = {}

        def elevate():
            # Faz o que o processo elevado faz: adquirir o MESMO lock. Com o lock preso, falharia.
            with UpdaterLock(self.tmp / ".lock", timeout_seconds=0.5):
                seen["lock"] = True
            seen["status"] = read_status("req1", directory=self.status_dir)
            return True

        with mock.patch("app.updater.versioned.quit_signal") as quit_signal,                 mock.patch("app.updater.versioned.versions.write_pointer", side_effect=PermissionError("negado")):
            status = self._updater(elevate=elevate).activate(request)
        self.assertTrue(seen["lock"])
        self.assertEqual((seen["status"].phase, seen["status"].percent), (PHASE_ACTIVATING, 5))  # gravado ANTES de elevar
        self.assertEqual(status.phase, PHASE_ACTIVATING)
        self.assertIn("administrador", status.message)
        self.assertFalse(status.is_failure)
        quit_signal.request_quit.assert_not_called()
        self.stopper.assert_not_called()

    def test_activate_fails_when_elevation_is_declined(self):
        request, _ = self._stage()
        elevate = mock.Mock(return_value=False)
        with mock.patch("app.updater.versioned.versions.write_pointer", side_effect=PermissionError("negado")):
            status = self._updater(elevate=elevate).activate(request)
        elevate.assert_called_once_with()
        self.assertEqual(status.phase, PHASE_FAILED)

    def test_activate_does_not_elevate_when_pointer_is_written(self):
        request, _ = self._stage()
        elevate = mock.Mock(return_value=True)
        self.assertEqual(self._updater(elevate=elevate).activate(request).phase, PHASE_SUCCESS)
        elevate.assert_not_called()

    def test_activate_writes_pointer_before_asking_the_app_to_quit_and_reports_phases_in_order(self):
        request, _ = self._stage()
        calls: list[str] = []
        phases: list[str] = []
        real_write_pointer = v.write_pointer

        def write_pointer(*args, **kwargs):
            calls.append("pointer")
            return real_write_pointer(*args, **kwargs)

        def write_status(status, **kwargs):
            phases.append(status.phase)
            return real_write_status(status, **kwargs)

        with mock.patch("app.updater.versioned.quit_signal") as quit_signal,                 mock.patch("app.updater.versioned.versions.write_pointer", side_effect=write_pointer),                 mock.patch("app.updater.versioned.write_status", side_effect=write_status):
            quit_signal.request_quit.side_effect = lambda *_: calls.append("quit")
            self.stopper.side_effect = lambda *a, **k: calls.append("stop") or []
            self.launch.side_effect = lambda *a, **k: calls.append("launch") or 1
            status = self._updater().activate(request)
        self.assertEqual(status.phase, PHASE_SUCCESS)
        self.assertEqual(calls, ["pointer", "quit", "stop", "launch"])
        self.assertEqual(phases, [PHASE_ACTIVATING, "CLOSING", "RESTARTING", PHASE_SUCCESS])

    def test_closing_is_reported_then_grace_sleep_then_quit_request(self):
        request, _ = self._stage()
        calls: list[str] = []
        with mock.patch("app.updater.versioned.quit_signal") as quit_signal,                 mock.patch("app.updater.versioned.write_status", side_effect=lambda status, **_: calls.append(status.phase)):
            quit_signal.request_quit.side_effect = lambda *_: calls.append("quit")
            sleep = mock.Mock(side_effect=lambda seconds: calls.append(f"sleep={seconds}"))
            updater = self._updater(sleep=sleep, config=VersionedConfig(min_free_space_mb=1, closing_grace_seconds=1.0))
            updater.activate(request)
        self.assertEqual(calls[calls.index("CLOSING"):calls.index("CLOSING") + 3], ["CLOSING", "sleep=1.0", "quit"])

    def test_quit_request_failure_restores_pointer_and_leaves_app_open(self):
        request, _ = self._stage()
        with mock.patch("app.updater.versioned.quit_signal") as quit_signal:
            quit_signal.request_quit.side_effect = PermissionError("sem acesso")
            status = self._updater().activate(request)
        self.assertEqual(status.phase, PHASE_FAILED)
        self.assertIn("continua aberto", status.message)
        self.assertIn("sem acesso", status.error)
        self.assertEqual(v.read_pointer(self.root).version, "2.8.0")
        self.stopper.assert_not_called()
        self.launch.assert_not_called()
        self.assertEqual(read_status("req1", directory=self.status_dir).phase, PHASE_FAILED)

    def test_handshake_marker_failure_restores_pointer_and_never_asks_the_app_to_quit(self):
        request, _ = self._stage()
        with mock.patch("app.updater.versioned.quit_signal") as quit_signal,                 mock.patch("app.updater.versioned.clear_handshake_marker", side_effect=OSError("marcador preso")):
            status = self._updater().activate(request)
        self.assertEqual(status.phase, PHASE_FAILED)
        self.assertIn("marcador preso", status.error)
        self.assertEqual(v.read_pointer(self.root).version, "2.8.0")
        quit_signal.request_quit.assert_not_called()
        self.stopper.assert_not_called()

    def test_rollback_status_is_written_before_the_old_app_is_relaunched(self):
        request, _ = self._stage()
        self.handshake.return_value = False
        at_launch: list = []

        def launch(*args, **kwargs):
            at_launch.append(read_status("req1", directory=self.status_dir))
            return 1

        self.launch.side_effect = launch
        status = self._updater().activate(request)
        self.assertEqual(status.phase, PHASE_ROLLED_BACK)
        self.assertEqual(len(at_launch), 2)  # nova versao, depois a antiga
        self.assertEqual(at_launch[0].phase, "RESTARTING")
        self.assertEqual(at_launch[1].phase, PHASE_ROLLED_BACK)  # a versao antiga ja encontra o aviso

    def test_rollback_without_handshake_restores_pointer_relaunches_old_app_and_explains(self):
        request, _ = self._stage()
        self.handshake.return_value = False
        status = self._updater().activate(request)
        self.assertEqual(status.phase, PHASE_ROLLED_BACK)
        self.assertEqual(v.read_pointer(self.root).version, "2.8.0")
        self.assertIn("a versao 2.8.0 foi restaurada", status.message)
        self.assertIn("nao abriu corretamente", status.message)
        self.assertIn("handshake", status.error)
        self.assertNotIn("--post-update", self.launch.call_args.args[1])  # reabre a versao anterior, sem handshake
        self.assertEqual(read_status("req1", directory=self.status_dir).phase, PHASE_ROLLED_BACK)

    def test_rollback_with_unwritable_pointer_reports_failed_instead_of_raising(self):
        request, _ = self._stage()
        self.handshake.return_value = False
        real = v.write_pointer
        outcomes = iter([None, PermissionError("negado")])

        def write_pointer(*args, **kwargs):
            failure = next(outcomes)
            if failure:
                raise failure
            return real(*args, **kwargs)

        with mock.patch("app.updater.versioned.versions.write_pointer", side_effect=write_pointer):
            status = self._updater().activate(request)
        self.assertEqual(status.phase, PHASE_FAILED)
        self.assertIn("restaurar a versao anterior", status.message)
        self.assertIn("negado", status.error)
        self.assertEqual(v.read_pointer(self.root).version, "2.9.0")  # ponteiro como esta


if __name__ == "__main__":
    unittest.main()
