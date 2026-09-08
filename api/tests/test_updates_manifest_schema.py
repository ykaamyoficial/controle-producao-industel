from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from api.app.updates.manifest_schema import (
    ManifestSchemaError,
    is_safe_artifact_filename,
    sha256_file,
    validate_manifest_dict,
)


def _valid_manifest(**overrides) -> dict:
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
            "content_type": "application/octet-stream",
        },
    }
    base.update(overrides)
    return base


class SafeArtifactFilenameTests(unittest.TestCase):
    def test_accepts_plain_filename(self):
        self.assertTrue(is_safe_artifact_filename("Sistema-Setup-3.2.0.exe"))

    def test_rejects_parent_traversal_forward_slash(self):
        self.assertFalse(is_safe_artifact_filename("../update.exe"))

    def test_rejects_parent_traversal_backslash(self):
        self.assertFalse(is_safe_artifact_filename("..\\update.exe"))

    def test_rejects_windows_drive_letter(self):
        self.assertFalse(is_safe_artifact_filename("C:\\temp\\update.exe"))

    def test_rejects_absolute_unix_path(self):
        self.assertFalse(is_safe_artifact_filename("/server/share/update.exe"))

    def test_rejects_subdirectory(self):
        self.assertFalse(is_safe_artifact_filename("subdir/update.exe"))

    def test_rejects_empty(self):
        self.assertFalse(is_safe_artifact_filename(""))
        self.assertFalse(is_safe_artifact_filename("   "))

    def test_rejects_null_byte(self):
        self.assertFalse(is_safe_artifact_filename("update.exe\x00.txt"))


class Sha256FileTests(unittest.TestCase):
    def test_matches_hashlib_reference(self):
        import hashlib

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.bin"
            payload = b"conteudo-de-teste" * 100000
            path.write_bytes(payload)
            self.assertEqual(sha256_file(path), hashlib.sha256(payload).hexdigest())


class ValidateManifestDictTests(unittest.TestCase):
    def test_accepts_valid_manifest_and_normalizes_sha256_lowercase(self):
        manifest = _valid_manifest()
        manifest["artifact"]["sha256"] = "A" * 64
        normalized = validate_manifest_dict(manifest)
        self.assertEqual(normalized["artifact"]["sha256"], "a" * 64)

    def test_rejects_unsupported_schema_version(self):
        with self.assertRaises(ManifestSchemaError):
            validate_manifest_dict(_valid_manifest(manifest_schema_version=99))

    def test_rejects_non_dict(self):
        with self.assertRaises(ManifestSchemaError):
            validate_manifest_dict([])  # type: ignore[arg-type]

    def test_rejects_invalid_release_version(self):
        with self.assertRaises(ManifestSchemaError):
            validate_manifest_dict(_valid_manifest(release_version="not-semver"))

    def test_rejects_invalid_channel(self):
        with self.assertRaises(ManifestSchemaError):
            validate_manifest_dict(_valid_manifest(channel="beta"))

    def test_rejects_missing_published_at(self):
        with self.assertRaises(ManifestSchemaError):
            validate_manifest_dict(_valid_manifest(published_at=""))

    def test_rejects_invalid_minimum_server_version(self):
        with self.assertRaises(ManifestSchemaError):
            validate_manifest_dict(_valid_manifest(minimum_server_version="x"))

    def test_rejects_empty_api_contract_version(self):
        with self.assertRaises(ManifestSchemaError):
            validate_manifest_dict(_valid_manifest(api_contract_version=""))

    def test_rejects_missing_artifact(self):
        data = _valid_manifest()
        del data["artifact"]
        with self.assertRaises(ManifestSchemaError):
            validate_manifest_dict(data)

    def test_rejects_unsafe_artifact_filename(self):
        data = _valid_manifest()
        data["artifact"]["filename"] = "../evil.exe"
        with self.assertRaises(ManifestSchemaError):
            validate_manifest_dict(data)

    def test_rejects_non_positive_size(self):
        data = _valid_manifest()
        data["artifact"]["size_bytes"] = 0
        with self.assertRaises(ManifestSchemaError):
            validate_manifest_dict(data)

    def test_rejects_bool_as_size(self):
        data = _valid_manifest()
        data["artifact"]["size_bytes"] = True
        with self.assertRaises(ManifestSchemaError):
            validate_manifest_dict(data)

    def test_rejects_invalid_sha256_length(self):
        data = _valid_manifest()
        data["artifact"]["sha256"] = "abc123"
        with self.assertRaises(ManifestSchemaError):
            validate_manifest_dict(data)

    def test_rejects_non_http_artifact_url(self):
        data = _valid_manifest(artifact_url="file:///etc/passwd")
        with self.assertRaises(ManifestSchemaError):
            validate_manifest_dict(data)

    def test_accepts_https_artifact_url(self):
        data = _valid_manifest(artifact_url="https://example.com/pkg.exe")
        normalized = validate_manifest_dict(data)
        self.assertEqual(normalized["artifact_url"], "https://example.com/pkg.exe")

    def test_defaults_content_type_when_absent(self):
        data = _valid_manifest()
        del data["artifact"]["content_type"]
        normalized = validate_manifest_dict(data)
        self.assertEqual(normalized["artifact"]["content_type"], "application/octet-stream")


if __name__ == "__main__":
    unittest.main()
