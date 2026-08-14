from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_release_manifest import (
    ManifestGenerationError,
    generate_manifest,
    resolve_release_version,
)
from app.updater.manifest import ManifestValidationError, validate_manifest_dict
from app.updater.validation import sha256_file
from app.version import APP_VERSION


class ResolveReleaseVersionTests(unittest.TestCase):
    def test_no_requested_version_uses_central_source(self):
        self.assertEqual(resolve_release_version(None), APP_VERSION)

    def test_matching_requested_version_is_accepted(self):
        self.assertEqual(resolve_release_version(APP_VERSION), APP_VERSION)

    def test_diverging_requested_version_is_rejected(self):
        with self.assertRaises(ManifestGenerationError):
            resolve_release_version("9.9.9", source_version=APP_VERSION)


class GenerateManifestTests(unittest.TestCase):
    def test_generates_manifest_with_correct_size_and_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "ControleProducaoSetup-2.6.0.exe"
            artifact.write_bytes(b"REAL_INSTALLER_BYTES" * 5000)
            manifest = generate_manifest(
                artifact_path=artifact, release_version="2.6.0", channel="production",
                minimum_server_version="0.8.0", api_contract_version="v1",
            )
            self.assertEqual(manifest.artifact.size_bytes, artifact.stat().st_size)
            self.assertEqual(manifest.artifact.sha256, sha256_file(artifact))
            self.assertEqual(manifest.artifact.filename, artifact.name)

    def test_missing_artifact_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ManifestGenerationError):
                generate_manifest(
                    artifact_path=Path(tmp) / "nope.exe", release_version="2.6.0", channel="production",
                    minimum_server_version="0.8.0", api_contract_version="v1",
                )

    def test_generated_manifest_passes_client_side_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "pkg.exe"
            artifact.write_bytes(b"content")
            manifest = generate_manifest(
                artifact_path=artifact, release_version="2.6.0", channel="production",
                minimum_server_version="0.8.0", api_contract_version="v1",
            )
            # nao deve levantar -- o proprio gerador ja valida antes de devolver.
            validate_manifest_dict(manifest.to_dict())

    def test_invalid_release_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "pkg.exe"
            artifact.write_bytes(b"content")
            with self.assertRaises(ManifestValidationError):
                generate_manifest(
                    artifact_path=artifact, release_version="not-semver", channel="production",
                    minimum_server_version="0.8.0", api_contract_version="v1",
                )

    def test_regenerating_after_artifact_changes_produces_different_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "pkg.exe"
            artifact.write_bytes(b"version-1-content")
            first = generate_manifest(
                artifact_path=artifact, release_version="2.6.0", channel="production",
                minimum_server_version="0.8.0", api_contract_version="v1",
            )
            artifact.write_bytes(b"version-2-content-different")
            second = generate_manifest(
                artifact_path=artifact, release_version="2.6.0", channel="production",
                minimum_server_version="0.8.0", api_contract_version="v1",
            )
            self.assertNotEqual(first.artifact.sha256, second.artifact.sha256)
            self.assertNotEqual(first.artifact.size_bytes, second.artifact.size_bytes)


if __name__ == "__main__":
    unittest.main()
