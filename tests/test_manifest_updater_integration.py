from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.updater.contract import UpdateState
from app.updater.exceptions import UpdateFailedError
from app.updater.journal_store import UpdateJournalStore
from app.updater.manifest_gate import ManifestGateError, build_update_request, download_and_verify_artifact, fetch_and_validate_manifest
from app.updater.manifest_provider import LocalFileManifestProvider
from app.updater.orchestrator import OrchestratorConfig, UpdaterOrchestrator
from app.updater.validation import sha256_file


class ManifestToUpdaterIntegrationTests(unittest.TestCase):
    """Fase 11, Secao 21: 'O Updater so pode avancar para preflight/swap
    quando receber um artefato VALID.' -- exercita o caminho completo
    manifesto -> download -> verificacao -> UpdateRequest -> Updater real da
    Fase 10 (sem mocks na fronteira entre as duas fases)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

        self.install_dir = self.tmp / "install"
        self.install_dir.mkdir()
        self.executable_path = self.install_dir / "ControleProducao.exe"
        self.executable_path.write_text("old build")

        # o pacote de atualizacao real da Fase 10 e um ZIP -- o "artefato"
        # descrito pelo manifesto da Fase 11 e esse mesmo ZIP.
        self.package_path = self.tmp / "update-package.zip"
        with zipfile.ZipFile(self.package_path, "w") as archive:
            archive.writestr("ControleProducao.exe", "new build")
            archive.writestr("VERSION", "2.6.0")

        digest = sha256_file(self.package_path)
        manifest_path = self.tmp / "manifest.json"
        manifest_path.write_text(json.dumps({
            "manifest_schema_version": 1, "release_version": "2.6.0", "channel": "production",
            "published_at": "2026-08-11T12:00:00Z", "minimum_server_version": "0.8.0", "api_contract_version": "v1",
            "artifact": {"filename": self.package_path.name, "size_bytes": self.package_path.stat().st_size, "sha256": digest},
        }), encoding="utf-8")
        self.manifest_path = manifest_path

        self.journal_store = UpdateJournalStore(self.tmp / "journal")
        self.lock_path = self.tmp / ".updater.lock"

    def _orchestrator(self) -> UpdaterOrchestrator:
        config = OrchestratorConfig(app_exit_timeout_seconds=1.0, app_exit_poll_interval_seconds=0.1, handshake_timeout_seconds=1.0)
        orchestrator = UpdaterOrchestrator(journal_store=self.journal_store, lock_path=self.lock_path, config=config)
        orchestrator._wait_for_exit = lambda pid, timeout_seconds, poll_interval_seconds: True

        def fake_launch(executable_path, args=None, cwd=None):
            if args and "--post-update" in args:
                from app.updater.handshake import write_handshake_marker
                write_handshake_marker(args[args.index("--post-update") + 1])
            return 999
        orchestrator._launch = fake_launch
        return orchestrator

    def test_valid_manifest_and_artifact_flow_all_the_way_to_success(self):
        from unittest.mock import patch

        manifest = fetch_and_validate_manifest(LocalFileManifestProvider(self.manifest_path))
        downloaded = download_and_verify_artifact(manifest, self.tmp / "downloads", self.tmp / "quarantine", source=str(self.package_path))
        request = build_update_request(
            manifest, downloaded, request_id="req-manifest-integ", install_dir=str(self.install_dir),
            executable_path=str(self.executable_path), parent_pid=424242, current_version="2.5.2",
        )

        with patch("app.updater.paths.get_app_data_dir", return_value=self.tmp / "appdata"):
            orchestrator = self._orchestrator()
            journal = orchestrator.run_update(
                request, download_dir=self.tmp / "dl2", staging_dir=self.tmp / "staging", backup_dir=self.tmp / "backup",
            )

        self.assertEqual(journal.state, UpdateState.SUCCESS)
        self.assertEqual(self.executable_path.read_text(), "new build")

    def test_tampered_artifact_never_reaches_updater_staging(self):
        # adultera o pacote depois do manifesto ja emitido -- o gate deve
        # bloquear ANTES de qualquer UpdateRequest ser construido, entao o
        # Updater da Fase 10 nunca e sequer chamado.
        data = bytearray(self.package_path.read_bytes())
        data[10] ^= 0xFF
        self.package_path.write_bytes(bytes(data))

        manifest = fetch_and_validate_manifest(LocalFileManifestProvider(self.manifest_path))
        with self.assertRaises(ManifestGateError):
            download_and_verify_artifact(manifest, self.tmp / "downloads", self.tmp / "quarantine", source=str(self.package_path))

        # nada foi tocado na instalacao.
        self.assertEqual(self.executable_path.read_text(), "old build")
        self.assertFalse((self.tmp / "staging").exists())


if __name__ == "__main__":
    unittest.main()
