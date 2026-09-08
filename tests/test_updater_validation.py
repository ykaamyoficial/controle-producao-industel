from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from app.updater.validation import PackageValidationStatus, sha256_file, verify_package


def _make_zip(path: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)


class VerifyPackageTests(unittest.TestCase):
    def test_missing_file_is_invalid_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = verify_package(Path(tmp) / "nope.zip")
            self.assertEqual(result.status, PackageValidationStatus.INVALID_PACKAGE)

    def test_size_mismatch_is_invalid_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pkg.zip"
            _make_zip(path, {"a.txt": b"hello"})
            result = verify_package(path, expected_size=999999)
            self.assertEqual(result.status, PackageValidationStatus.INVALID_SIZE)

    def test_non_zip_file_is_invalid_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pkg.zip"
            path.write_bytes(b"not a zip file at all")
            result = verify_package(path)
            self.assertEqual(result.status, PackageValidationStatus.INVALID_PACKAGE)

    def test_empty_zip_is_invalid_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.zip"
            with zipfile.ZipFile(path, "w"):
                pass
            result = verify_package(path)
            self.assertEqual(result.status, PackageValidationStatus.INVALID_PACKAGE)

    def test_missing_expected_hash_is_missing_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pkg.zip"
            _make_zip(path, {"a.txt": b"hello"})
            result = verify_package(path)
            self.assertEqual(result.status, PackageValidationStatus.MISSING_METADATA)

    def test_matching_hash_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pkg.zip"
            _make_zip(path, {"a.txt": b"hello"})
            expected = sha256_file(path)
            result = verify_package(path, expected_hash=expected)
            self.assertEqual(result.status, PackageValidationStatus.VALID)

    def test_mismatched_hash_is_invalid_hash_and_never_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pkg.zip"
            _make_zip(path, {"a.txt": b"hello"})
            result = verify_package(path, expected_hash="0" * 64)
            self.assertEqual(result.status, PackageValidationStatus.INVALID_HASH)
            self.assertFalse(result.is_valid)

    def test_hash_check_is_case_insensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pkg.zip"
            _make_zip(path, {"a.txt": b"hello"})
            expected = sha256_file(path).upper()
            result = verify_package(path, expected_hash=expected)
            self.assertEqual(result.status, PackageValidationStatus.VALID)


if __name__ == "__main__":
    unittest.main()
