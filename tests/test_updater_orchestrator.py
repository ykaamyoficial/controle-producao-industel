from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from app.updater.contract import (
    InvalidUpdateRequestError,
    UpdateJournal,
    UpdateRequest,
    UpdateState,
)
from app.updater.exceptions import ConcurrentUpdateError, UpdateFailedError
from app.updater.extraction import PathTraversalError
from app.updater.journal_store import UpdateJournalStore
from app.updater.lock import UpdaterLock
from app.updater.orchestrator import OrchestratorConfig, UpdaterOrchestrator
from app.updater.validation import sha256_file


def _build_package(path: Path, *, exe_content: bytes = b"new build", version: str = "1.1.0", extra: dict[str, bytes] | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ControleProducao.exe", exe_content)
        archive.writestr("VERSION", version)
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
    return path


class _OrchestratorTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

        self.install_dir = self.tmp / "install"
        self.install_dir.mkdir()
        self.executable_path = self.install_dir / "ControleProducao.exe"
        self.executable_path.write_text("old build")
        (self.install_dir / "config").mkdir()
        (self.install_dir / "config" / "controle_producao_config.json").write_text('{"real": true}')

        self.package_path = self.tmp / "package.zip"
        _build_package(self.package_path)

        self.journal_store = UpdateJournalStore(self.tmp / "journal")
        self.lock_path = self.tmp / ".updater.lock"

        self._launched_handshakes: list[str] = []

    def _orchestrator(self, **config_overrides) -> UpdaterOrchestrator:
        defaults = dict(app_exit_timeout_seconds=1.0, app_exit_poll_interval_seconds=0.1, handshake_timeout_seconds=1.0)
        defaults.update(config_overrides)
        config = OrchestratorConfig(**defaults)
        orchestrator = UpdaterOrchestrator(journal_store=self.journal_store, lock_path=self.lock_path, config=config)
        orchestrator._wait_for_exit = lambda pid, timeout_seconds, poll_interval_seconds: True

        def fake_launch(executable_path, args=None, cwd=None):
            if args and "--post-update" in args:
                from app.updater.handshake import write_handshake_marker
                write_handshake_marker(args[args.index("--post-update") + 1])
            return 999
        orchestrator._launch = fake_launch
        return orchestrator

    def _request(self, **overrides) -> UpdateRequest:
        base = dict(
            request_id="req-1", current_version="1.0.0", target_version="1.1.0",
            package_url_or_source=str(self.package_path), install_dir=str(self.install_dir),
            executable_path=str(self.executable_path), parent_pid=424242,
        )
        base.update(overrides)
        return UpdateRequest(**base)

    def _dirs(self, request_id: str = "req-1"):
        return dict(download_dir=self.tmp / "dl" / request_id, staging_dir=self.tmp / "staging" / request_id, backup_dir=self.tmp / "backup" / request_id)


class SuccessPathTests(_OrchestratorTestCase):
    def test_full_update_succeeds_and_swaps_executable(self):
        # monkeypatch handshake dir to isolate from real app data
        from unittest.mock import patch
        with patch("app.updater.paths.get_app_data_dir", return_value=self.tmp / "appdata"):
            orchestrator = self._orchestrator()
            journal = orchestrator.run_update(self._request(), **self._dirs())

        self.assertEqual(journal.state, UpdateState.SUCCESS)
        self.assertEqual(self.executable_path.read_text(), "new build")

    def test_protected_config_file_survives_update(self):
        from unittest.mock import patch
        with patch("app.updater.paths.get_app_data_dir", return_value=self.tmp / "appdata"):
            orchestrator = self._orchestrator()
            orchestrator.run_update(self._request(), **self._dirs())
        self.assertEqual((self.install_dir / "config" / "controle_producao_config.json").read_text(), '{"real": true}')

    def test_final_version_matches_target_version(self):
        from unittest.mock import patch
        with patch("app.updater.paths.get_app_data_dir", return_value=self.tmp / "appdata"):
            orchestrator = self._orchestrator()
            orchestrator.run_update(self._request(), **self._dirs())
        self.assertEqual((self.install_dir / "VERSION").read_text(), "1.1.0")

    def test_success_cleans_up_backup_and_download_dirs(self):
        from unittest.mock import patch
        dirs = self._dirs()
        with patch("app.updater.paths.get_app_data_dir", return_value=self.tmp / "appdata"):
            orchestrator = self._orchestrator()
            orchestrator.run_update(self._request(), **dirs)
        self.assertFalse(dirs["backup_dir"].exists())
        self.assertFalse(dirs["download_dir"].exists())


class RequestValidationTests(_OrchestratorTestCase):
    def test_invalid_request_never_touches_install_dir(self):
        orchestrator = self._orchestrator()
        bad_request = self._request(target_version="not-a-version")
        before = self.executable_path.read_text()
        with self.assertRaises(InvalidUpdateRequestError):
            orchestrator.run_update(bad_request, **self._dirs())
        self.assertEqual(self.executable_path.read_text(), before)
        self.assertIsNone(self.journal_store.load("req-1"))

    def test_downgrade_without_flag_rejected_before_touching_disk(self):
        orchestrator = self._orchestrator()
        bad_request = self._request(target_version="0.5.0")
        with self.assertRaises(InvalidUpdateRequestError):
            orchestrator.run_update(bad_request, **self._dirs())
        self.assertEqual(self.executable_path.read_text(), "old build")


class DownloadAndValidationFailureTests(_OrchestratorTestCase):
    def test_download_failure_leaves_install_dir_untouched_and_marks_failed(self):
        orchestrator = self._orchestrator()
        request = self._request(package_url_or_source=str(self.tmp / "does-not-exist.zip"))
        with self.assertRaises(UpdateFailedError) as ctx:
            orchestrator.run_update(request, **self._dirs())
        self.assertEqual(ctx.exception.journal.state, UpdateState.FAILED)
        self.assertEqual(self.executable_path.read_text(), "old build")

    def test_hash_mismatch_blocks_update_and_leaves_install_dir_untouched(self):
        orchestrator = self._orchestrator()
        request = self._request(package_expected_hash="0" * 64)
        with self.assertRaises(UpdateFailedError) as ctx:
            orchestrator.run_update(request, **self._dirs())
        self.assertEqual(ctx.exception.journal.state, UpdateState.FAILED)
        self.assertEqual(self.executable_path.read_text(), "old build")

    def test_matching_hash_allows_update_to_proceed(self):
        from unittest.mock import patch
        digest = sha256_file(self.package_path)
        with patch("app.updater.paths.get_app_data_dir", return_value=self.tmp / "appdata"):
            orchestrator = self._orchestrator()
            journal = orchestrator.run_update(self._request(package_expected_hash=digest), **self._dirs())
        self.assertEqual(journal.state, UpdateState.SUCCESS)

    def test_path_traversal_package_blocks_update_and_leaves_install_dir_untouched(self):
        evil_package = self.tmp / "evil.zip"
        with zipfile.ZipFile(evil_package, "w") as archive:
            archive.writestr("../../evil.exe", b"malicious")
        orchestrator = self._orchestrator()
        request = self._request(package_url_or_source=str(evil_package))
        with self.assertRaises(UpdateFailedError) as ctx:
            orchestrator.run_update(request, **self._dirs())
        self.assertEqual(ctx.exception.journal.state, UpdateState.FAILED)
        self.assertIn("Extracao", ctx.exception.journal.error_code or "")
        self.assertEqual(self.executable_path.read_text(), "old build")


class PrecheckFailureTests(_OrchestratorTestCase):
    def test_insufficient_disk_space_blocks_apply(self):
        orchestrator = self._orchestrator()

        def failing_precheck(**kwargs):
            from app.updater.precheck import PrecheckResult
            return PrecheckResult(False, "espaco livre insuficiente (simulado)")
        orchestrator._precheck = failing_precheck

        with self.assertRaises(UpdateFailedError) as ctx:
            orchestrator.run_update(self._request(), **self._dirs())
        self.assertEqual(ctx.exception.journal.state, UpdateState.FAILED)
        self.assertEqual(self.executable_path.read_text(), "old build")


class AppExitTests(_OrchestratorTestCase):
    def test_app_still_open_blocks_swap_until_timeout(self):
        orchestrator = self._orchestrator(allow_force_close=False)
        orchestrator._wait_for_exit = lambda pid, timeout_seconds, poll_interval_seconds: False

        with self.assertRaises(UpdateFailedError) as ctx:
            orchestrator.run_update(self._request(), **self._dirs())
        self.assertEqual(ctx.exception.journal.state, UpdateState.FAILED)
        self.assertEqual(self.executable_path.read_text(), "old build")

    def test_force_close_policy_terminates_and_proceeds(self):
        from unittest.mock import patch
        orchestrator = self._orchestrator(allow_force_close=True)
        wait_calls = []

        def fake_wait(pid, timeout_seconds, poll_interval_seconds):
            wait_calls.append(pid)
            return len(wait_calls) > 1  # primeira chamada falha, segunda (pos-terminate) sucede
        orchestrator._wait_for_exit = fake_wait
        terminated = []
        orchestrator._terminate = lambda pid: terminated.append(pid) or True

        with patch("app.updater.paths.get_app_data_dir", return_value=self.tmp / "appdata"):
            journal = orchestrator.run_update(self._request(), **self._dirs())
        self.assertEqual(journal.state, UpdateState.SUCCESS)
        self.assertEqual(terminated, [424242])


class RollbackTests(_OrchestratorTestCase):
    def test_invalid_new_executable_triggers_local_rollback(self):
        from unittest.mock import patch
        orchestrator = self._orchestrator()

        def selective_validator(**kwargs):
            from app.updater.install_validation import InstallValidationResult, validate_installation
            if kwargs.get("target_version") == "1.1.0":
                return InstallValidationResult(False, "executavel novo invalido (simulado)")
            return validate_installation(**kwargs)
        orchestrator._validate_installation = selective_validator

        with patch("app.updater.paths.get_app_data_dir", return_value=self.tmp / "appdata"):
            with self.assertRaises(UpdateFailedError) as ctx:
                orchestrator.run_update(self._request(), **self._dirs())

        self.assertEqual(ctx.exception.journal.state, UpdateState.ROLLED_BACK)
        self.assertEqual(self.executable_path.read_text(), "old build")
        self.assertEqual((self.install_dir / "config" / "controle_producao_config.json").read_text(), '{"real": true}')

    def test_launch_failure_triggers_local_rollback(self):
        orchestrator = self._orchestrator()

        def failing_launch(executable_path, args=None, cwd=None):
            raise OSError("nao foi possivel iniciar o executavel (simulado)")
        orchestrator._launch = failing_launch

        with self.assertRaises(UpdateFailedError) as ctx:
            orchestrator.run_update(self._request(), **self._dirs())
        self.assertEqual(ctx.exception.journal.state, UpdateState.ROLLED_BACK)
        self.assertEqual(self.executable_path.read_text(), "old build")

    def test_missing_handshake_triggers_local_rollback(self):
        orchestrator = self._orchestrator(handshake_timeout_seconds=0.2)
        orchestrator._launch = lambda executable_path, args=None, cwd=None: 999  # nunca escreve o handshake

        with self.assertRaises(UpdateFailedError) as ctx:
            orchestrator.run_update(self._request(), **self._dirs())
        self.assertEqual(ctx.exception.journal.state, UpdateState.ROLLED_BACK)
        self.assertEqual(self.executable_path.read_text(), "old build")


class ConcurrencyTests(_OrchestratorTestCase):
    def test_two_updaters_cannot_apply_simultaneously(self):
        orchestrator = self._orchestrator()
        holder = UpdaterLock(self.lock_path, timeout_seconds=60)
        holder._acquire()
        try:
            with self.assertRaises(ConcurrentUpdateError):
                orchestrator.run_update(self._request(), **self._dirs())
        finally:
            holder.release()


class RecoveryTests(_OrchestratorTestCase):
    def test_incomplete_journal_before_backup_created_is_marked_failed(self):
        orchestrator = self._orchestrator()
        dirs = self._dirs()
        journal = UpdateJournal(
            request_id="req-1", current_version="1.0.0", target_version="1.1.0", state=UpdateState.DOWNLOADING,
            staging_path=str(dirs["staging_dir"]), backup_path=str(dirs["backup_dir"]),
            started_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc), last_step="DOWNLOADING",
        )
        self.journal_store.save(journal)

        recovered = orchestrator.recover_incomplete_update(request=self._request())
        self.assertEqual(recovered.state, UpdateState.FAILED)
        # install_dir nunca foi tocado -- backup nao existia.
        self.assertEqual(self.executable_path.read_text(), "old build")

    def test_incomplete_journal_after_backup_created_is_rolled_back_deterministically(self):
        orchestrator = self._orchestrator()
        dirs = self._dirs()
        # simula um swap parcialmente aplicado: demote ja aconteceu (backup existe
        # com o build antigo), install_dir contem o build novo (promote completou),
        # mas o journal nunca chegou a SUCCESS.
        dirs["backup_dir"].mkdir(parents=True)
        (dirs["backup_dir"] / "ControleProducao.exe").write_text("old build")
        self.executable_path.write_text("new build (incompleto)")

        journal = UpdateJournal(
            request_id="req-1", current_version="1.0.0", target_version="1.1.0", state=UpdateState.APPLYING,
            staging_path=str(dirs["staging_dir"]), backup_path=str(dirs["backup_dir"]),
            started_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc), last_step="APPLYING",
        )
        self.journal_store.save(journal)

        recovered = orchestrator.recover_incomplete_update(request=self._request())
        self.assertEqual(recovered.state, UpdateState.ROLLED_BACK)
        self.assertEqual(self.executable_path.read_text(), "old build")

    def test_no_incomplete_journal_returns_none(self):
        orchestrator = self._orchestrator()
        self.assertIsNone(orchestrator.recover_incomplete_update(request=self._request()))

    def test_incomplete_journal_without_request_context_escalates_to_manual_intervention(self):
        orchestrator = self._orchestrator()
        dirs = self._dirs()
        dirs["backup_dir"].mkdir(parents=True)
        journal = UpdateJournal(
            request_id="req-1", current_version="1.0.0", target_version="1.1.0", state=UpdateState.APPLYING,
            staging_path=str(dirs["staging_dir"]), backup_path=str(dirs["backup_dir"]),
            started_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc), last_step="APPLYING",
        )
        self.journal_store.save(journal)

        recovered = orchestrator.recover_incomplete_update(request=None)
        self.assertEqual(recovered.state, UpdateState.MANUAL_INTERVENTION_REQUIRED)


if __name__ == "__main__":
    unittest.main()
