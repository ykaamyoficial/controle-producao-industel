from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.updater.artifact_verification import (
    ArtifactVerificationStatus,
    verify_artifact_against_manifest,
    verify_download,
)
from app.updater.manifest import ArtifactDescriptor, ReleaseManifest


def _manifest_for(path: Path, **overrides) -> ReleaseManifest:
    base = dict(
        manifest_schema_version=1, release_version="2.6.0", channel="production",
        published_at=datetime.now(timezone.utc), minimum_server_version="0.8.0", api_contract_version="v1",
        artifact=ArtifactDescriptor(filename=path.name, size_bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest()),
    )
    base.update(overrides)
    return ReleaseManifest(**base)


class VerifyArtifactAgainstManifestTests(unittest.TestCase):
    def test_valid_artifact_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pkg.exe"
            path.write_bytes(b"content" * 1000)
            result = verify_artifact_against_manifest(path, _manifest_for(path))
            self.assertEqual(result.status, ArtifactVerificationStatus.VALID)
            self.assertTrue(result.is_valid)

    def test_streaming_hash_matches_reference_for_large_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "big.bin"
            with path.open("wb") as handle:
                for _ in range(30):
                    handle.write(b"Y" * (1024 * 1024))  # 30MB, multiplos chunks
            manifest = _manifest_for(path)
            result = verify_artifact_against_manifest(path, manifest)
            self.assertEqual(result.status, ArtifactVerificationStatus.VALID)
            self.assertEqual(result.actual_sha256, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_truncated_file_is_size_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pkg.exe"
            path.write_bytes(b"content" * 1000)
            manifest = _manifest_for(path)
            path.write_bytes(b"content" * 500)  # truncado depois do manifesto ja gerado
            result = verify_artifact_against_manifest(path, manifest)
            self.assertEqual(result.status, ArtifactVerificationStatus.SIZE_MISMATCH)

    def test_same_size_altered_content_is_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pkg.exe"
            data = bytearray(b"content" * 1000)
            path.write_bytes(bytes(data))
            manifest = _manifest_for(path)
            data[500] ^= 0xFF
            path.write_bytes(bytes(data))  # mesmo tamanho, 1 byte alterado
            result = verify_artifact_against_manifest(path, manifest)
            self.assertEqual(result.status, ArtifactVerificationStatus.HASH_MISMATCH)

    def test_appended_bytes_is_size_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pkg.exe"
            path.write_bytes(b"content" * 1000)
            manifest = _manifest_for(path)
            with path.open("ab") as handle:
                handle.write(b"extra-bytes")
            result = verify_artifact_against_manifest(path, manifest)
            self.assertEqual(result.status, ArtifactVerificationStatus.SIZE_MISMATCH)

    def test_missing_file_is_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.exe"
            fake_manifest = ReleaseManifest(
                manifest_schema_version=1, release_version="2.6.0", channel="production",
                published_at=datetime.now(timezone.utc), minimum_server_version="0.8.0", api_contract_version="v1",
                artifact=ArtifactDescriptor(filename="nope.exe", size_bytes=10, sha256="a" * 64),
            )
            result = verify_artifact_against_manifest(missing, fake_manifest)
            self.assertEqual(result.status, ArtifactVerificationStatus.FILE_MISSING)


class VerifyDownloadTests(unittest.TestCase):
    def test_invalid_manifest_short_circuits_to_manifest_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pkg.exe"
            path.write_bytes(b"data")
            result = verify_download(manifest_data={"manifest_schema_version": 99}, file_path=path)
            self.assertEqual(result.status, ArtifactVerificationStatus.MANIFEST_INVALID)

    def test_valid_manifest_and_matching_file_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pkg.exe"
            path.write_bytes(b"content" * 100)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest_data = {
                "manifest_schema_version": 1, "release_version": "2.6.0", "channel": "production",
                "published_at": "2026-08-11T12:00:00Z", "minimum_server_version": "0.8.0", "api_contract_version": "v1",
                "artifact": {"filename": "pkg.exe", "size_bytes": path.stat().st_size, "sha256": digest},
            }
            result = verify_download(manifest_data=manifest_data, file_path=path)
            self.assertEqual(result.status, ArtifactVerificationStatus.VALID)


if __name__ == "__main__":
    unittest.main()
