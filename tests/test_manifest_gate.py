from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.updater.contract import validate_update_request
from app.updater.downloader import DownloadError
from app.updater.manifest_gate import (
    ManifestGateError,
    build_update_request,
    download_and_verify_artifact,
    fetch_and_validate_manifest,
)
from app.updater.manifest_provider import LocalFileManifestProvider
from app.updater.manifest_store import LastKnownGoodManifestStore
from app.updater.validation import sha256_file


def _write_manifest_and_artifact(tmp: Path, *, tamper: bool = False, truncate: bool = False) -> tuple[Path, Path]:
    artifact = tmp / "ControleProducaoSetup-2.6.0.exe"
    artifact.write_bytes(b"INSTALLER_CONTENT" * 2000)
    digest = sha256_file(artifact)
    size = artifact.stat().st_size

    if tamper:
        data = bytearray(artifact.read_bytes())
        data[100] ^= 0xFF
        artifact.write_bytes(bytes(data))
    if truncate:
        artifact.write_bytes(artifact.read_bytes()[:-500])

    manifest_path = tmp / "manifest.json"
    import json
    manifest_path.write_text(json.dumps({
        "manifest_schema_version": 1, "release_version": "2.6.0", "channel": "production",
        "published_at": "2026-08-11T12:00:00Z", "minimum_server_version": "0.8.0", "api_contract_version": "v1",
        "artifact": {"filename": artifact.name, "size_bytes": size, "sha256": digest},
    }), encoding="utf-8")
    return manifest_path, artifact


class FetchAndValidateManifestTests(unittest.TestCase):
    def test_valid_manifest_is_accepted_and_stored_as_last_known_good(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            manifest_path, _ = _write_manifest_and_artifact(tmp)
            store = LastKnownGoodManifestStore(tmp / "lastgood")
            manifest = fetch_and_validate_manifest(LocalFileManifestProvider(manifest_path), last_known_good_store=store)
            self.assertEqual(manifest.release_version, "2.6.0")
            self.assertEqual(store.load().release_version, "2.6.0")

    def test_invalid_manifest_never_overwrites_last_known_good(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            good_path, _ = _write_manifest_and_artifact(tmp)
            store = LastKnownGoodManifestStore(tmp / "lastgood")
            fetch_and_validate_manifest(LocalFileManifestProvider(good_path), last_known_good_store=store)

            bad_path = tmp / "bad_manifest.json"
            bad_path.write_text('{"manifest_schema_version": 99}', encoding="utf-8")
            with self.assertRaises(ManifestGateError):
                fetch_and_validate_manifest(LocalFileManifestProvider(bad_path), last_known_good_store=store)

            self.assertEqual(store.load().release_version, "2.6.0")


class DownloadAndVerifyArtifactTests(unittest.TestCase):
    def test_valid_artifact_is_downloaded_and_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            manifest_path, artifact = _write_manifest_and_artifact(tmp)
            manifest = fetch_and_validate_manifest(LocalFileManifestProvider(manifest_path))
            result_path = download_and_verify_artifact(manifest, tmp / "downloads", tmp / "quarantine", source=str(artifact))
            self.assertTrue(result_path.is_file())
            self.assertEqual(sha256_file(result_path), manifest.artifact.sha256)

    def test_tampered_artifact_is_rejected_and_quarantined(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            manifest_path, artifact = _write_manifest_and_artifact(tmp, tamper=True)
            manifest = fetch_and_validate_manifest(LocalFileManifestProvider(manifest_path))
            with self.assertRaises(ManifestGateError):
                download_and_verify_artifact(manifest, tmp / "downloads", tmp / "quarantine", source=str(artifact))
            quarantined = list((tmp / "quarantine").iterdir())
            self.assertEqual(len(quarantined), 1)
            downloads = list((tmp / "downloads").iterdir()) if (tmp / "downloads").exists() else []
            self.assertEqual(downloads, [])

    def test_truncated_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            manifest_path, artifact = _write_manifest_and_artifact(tmp, truncate=True)
            manifest = fetch_and_validate_manifest(LocalFileManifestProvider(manifest_path))
            with self.assertRaises(ManifestGateError):
                download_and_verify_artifact(manifest, tmp / "downloads", tmp / "quarantine", source=str(artifact))

    def test_missing_source_raises_before_any_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            manifest_path, _ = _write_manifest_and_artifact(tmp)
            manifest = fetch_and_validate_manifest(LocalFileManifestProvider(manifest_path))
            with self.assertRaises(ManifestGateError):
                download_and_verify_artifact(manifest, tmp / "downloads", tmp / "quarantine", source=None)

    def test_download_failure_raises_manifest_gate_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            manifest_path, _ = _write_manifest_and_artifact(tmp)
            manifest = fetch_and_validate_manifest(LocalFileManifestProvider(manifest_path))
            with self.assertRaises(ManifestGateError):
                download_and_verify_artifact(manifest, tmp / "downloads", tmp / "quarantine", source=str(tmp / "does-not-exist.exe"))


class BuildUpdateRequestTests(unittest.TestCase):
    def test_produces_a_request_that_passes_phase10_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            manifest_path, artifact = _write_manifest_and_artifact(tmp)
            manifest = fetch_and_validate_manifest(LocalFileManifestProvider(manifest_path))
            downloaded = download_and_verify_artifact(manifest, tmp / "downloads", tmp / "quarantine", source=str(artifact))

            request = build_update_request(
                manifest, downloaded, request_id="req-1", install_dir=str(tmp / "install"),
                executable_path=str(tmp / "install" / "ControleProducao.exe"), parent_pid=1234, current_version="2.5.2",
            )
            validate_update_request(request)  # nao deve levantar
            self.assertEqual(request.target_version, "2.6.0")
            self.assertEqual(request.package_expected_hash, manifest.artifact.sha256)
            self.assertEqual(request.package_expected_size, manifest.artifact.size_bytes)

    def test_request_never_relies_on_missing_metadata_path(self):
        # um request construido a partir de um manifesto sempre carrega hash
        # e tamanho explicitos -- nunca cai no caminho MISSING_METADATA da
        # verificacao interna da Fase 10.
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            manifest_path, artifact = _write_manifest_and_artifact(tmp)
            manifest = fetch_and_validate_manifest(LocalFileManifestProvider(manifest_path))
            downloaded = download_and_verify_artifact(manifest, tmp / "downloads", tmp / "quarantine", source=str(artifact))
            request = build_update_request(
                manifest, downloaded, request_id="req-1", install_dir=str(tmp / "install"),
                executable_path=str(tmp / "install" / "App.exe"), parent_pid=1234,
            )
            self.assertIsNotNone(request.package_expected_hash)
            self.assertIsNotNone(request.package_expected_size)


if __name__ == "__main__":
    unittest.main()
