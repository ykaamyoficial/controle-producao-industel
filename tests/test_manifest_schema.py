from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from app.updater.manifest import (
    ArtifactDescriptor,
    ManifestValidationError,
    ReleaseManifest,
    is_safe_artifact_filename,
    validate_manifest_dict,
)


def _manifest_dict(**overrides) -> dict:
    base = {
        "manifest_schema_version": 1,
        "release_version": "2.6.0",
        "channel": "production",
        "published_at": "2026-08-11T12:00:00Z",
        "minimum_server_version": "0.8.0",
        "api_contract_version": "v1",
        "artifact": {
            "filename": "ControleProducaoSetup-2.6.0.exe",
            "size_bytes": 123456,
            "sha256": "a" * 64,
            "content_type": "application/vnd.microsoft.portable-executable",
        },
    }
    base.update(overrides)
    return base


class SafeArtifactFilenameTests(unittest.TestCase):
    def test_accepts_plain_filename(self):
        self.assertTrue(is_safe_artifact_filename("Sistema-Setup-3.2.0.exe"))

    def test_rejects_parent_traversal(self):
        self.assertFalse(is_safe_artifact_filename("../update.exe"))
        self.assertFalse(is_safe_artifact_filename("..\\update.exe"))

    def test_rejects_absolute_windows_path(self):
        self.assertFalse(is_safe_artifact_filename(r"C:\temp\update.exe"))

    def test_rejects_absolute_unix_path(self):
        self.assertFalse(is_safe_artifact_filename("/server/share/update.exe"))

    def test_rejects_subdirectory(self):
        self.assertFalse(is_safe_artifact_filename("subdir/update.exe"))

    def test_rejects_empty_or_whitespace(self):
        self.assertFalse(is_safe_artifact_filename(""))
        self.assertFalse(is_safe_artifact_filename("   "))


class ValidateManifestDictTests(unittest.TestCase):
    def test_valid_manifest_is_accepted(self):
        manifest = validate_manifest_dict(_manifest_dict())
        self.assertEqual(manifest.release_version, "2.6.0")
        self.assertEqual(manifest.artifact.filename, "ControleProducaoSetup-2.6.0.exe")

    def test_unknown_schema_version_is_rejected(self):
        with self.assertRaises(ManifestValidationError):
            validate_manifest_dict(_manifest_dict(manifest_schema_version=2))

    def test_missing_schema_version_is_rejected(self):
        data = _manifest_dict()
        del data["manifest_schema_version"]
        with self.assertRaises(ManifestValidationError):
            validate_manifest_dict(data)

    def test_invalid_semver_release_version_is_rejected(self):
        with self.assertRaises(ManifestValidationError):
            validate_manifest_dict(_manifest_dict(release_version="not-semver"))

    def test_invalid_channel_is_rejected(self):
        with self.assertRaises(ManifestValidationError):
            validate_manifest_dict(_manifest_dict(channel="beta"))

    def test_non_utc_timestamp_without_offset_is_rejected(self):
        with self.assertRaises(ManifestValidationError):
            validate_manifest_dict(_manifest_dict(published_at="2026-08-11T12:00:00"))

    def test_invalid_minimum_server_version_is_rejected(self):
        with self.assertRaises(ManifestValidationError):
            validate_manifest_dict(_manifest_dict(minimum_server_version="x.y.z"))

    def test_empty_api_contract_version_is_rejected(self):
        with self.assertRaises(ManifestValidationError):
            validate_manifest_dict(_manifest_dict(api_contract_version=""))

    def test_path_traversal_filename_is_rejected(self):
        data = _manifest_dict()
        data["artifact"]["filename"] = "../evil.exe"
        with self.assertRaises(ManifestValidationError):
            validate_manifest_dict(data)

    def test_non_positive_size_bytes_is_rejected(self):
        data = _manifest_dict()
        data["artifact"]["size_bytes"] = 0
        with self.assertRaises(ManifestValidationError):
            validate_manifest_dict(data)

    def test_short_hash_is_rejected(self):
        data = _manifest_dict()
        data["artifact"]["sha256"] = "abc123"
        with self.assertRaises(ManifestValidationError):
            validate_manifest_dict(data)

    def test_non_hex_hash_is_rejected(self):
        data = _manifest_dict()
        data["artifact"]["sha256"] = "z" * 64
        with self.assertRaises(ManifestValidationError):
            validate_manifest_dict(data)

    def test_uppercase_hash_is_normalized_to_lowercase(self):
        data = _manifest_dict()
        data["artifact"]["sha256"] = "A" * 64
        manifest = validate_manifest_dict(data)
        self.assertEqual(manifest.artifact.sha256, "a" * 64)

    def test_missing_artifact_is_rejected(self):
        data = _manifest_dict()
        del data["artifact"]
        with self.assertRaises(ManifestValidationError):
            validate_manifest_dict(data)

    def test_non_http_artifact_url_is_rejected(self):
        with self.assertRaises(ManifestValidationError):
            validate_manifest_dict(_manifest_dict(artifact_url="file:///etc/passwd"))

    def test_ftp_artifact_url_is_rejected(self):
        with self.assertRaises(ManifestValidationError):
            validate_manifest_dict(_manifest_dict(artifact_url="ftp://example.com/pkg.exe"))

    def test_https_artifact_url_is_accepted(self):
        manifest = validate_manifest_dict(_manifest_dict(artifact_url="https://example.com/pkg.exe"))
        self.assertEqual(manifest.artifact_url, "https://example.com/pkg.exe")

    def test_not_a_dict_is_rejected(self):
        with self.assertRaises(ManifestValidationError):
            validate_manifest_dict(["not", "a", "dict"])  # type: ignore[arg-type]


class ReleaseManifestSerializationTests(unittest.TestCase):
    def test_to_canonical_json_is_deterministic_and_sorted(self):
        manifest = validate_manifest_dict(_manifest_dict())
        first = manifest.to_canonical_json()
        second = manifest.to_canonical_json()
        self.assertEqual(first, second)
        parsed = json.loads(first)
        self.assertEqual(list(parsed.keys()), sorted(parsed.keys()))

    def test_round_trip_through_json_preserves_semantics(self):
        original = validate_manifest_dict(_manifest_dict())
        restored = validate_manifest_dict(json.loads(original.to_canonical_json()))
        self.assertEqual(original.release_version, restored.release_version)
        self.assertEqual(original.artifact.sha256, restored.artifact.sha256)
        self.assertEqual(original.published_at, restored.published_at)

    def test_published_at_serializes_as_utc_z_suffix(self):
        manifest = ReleaseManifest(
            manifest_schema_version=1, release_version="1.0.0", channel="production",
            published_at=datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc),
            minimum_server_version="1.0.0", api_contract_version="v1",
            artifact=ArtifactDescriptor(filename="x.exe", size_bytes=10, sha256="a" * 64),
        )
        self.assertEqual(manifest.to_dict()["published_at"], "2026-08-11T12:00:00Z")


if __name__ == "__main__":
    unittest.main()
