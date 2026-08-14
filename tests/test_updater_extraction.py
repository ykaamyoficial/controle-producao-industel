from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from app.updater.extraction import PathTraversalError, safe_extract_zip


def _zip_with(path: Path, names_and_content: list[tuple[str, bytes]]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in names_and_content:
            archive.writestr(name, content)


class SafeExtractZipTests(unittest.TestCase):
    def test_extracts_normal_nested_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive = tmp / "pkg.zip"
            _zip_with(archive, [("app/main.exe", b"binary"), ("app/lib/helper.dll", b"dll")])
            dest = tmp / "dest"
            extracted = safe_extract_zip(archive, dest)
            self.assertEqual(set(extracted), {"app/main.exe", "app/lib/helper.dll"})
            self.assertEqual((dest / "app" / "main.exe").read_bytes(), b"binary")

    def test_rejects_parent_directory_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive = tmp / "evil.zip"
            _zip_with(archive, [("../../evil.exe", b"malicious")])
            dest = tmp / "dest"
            with self.assertRaises(PathTraversalError):
                safe_extract_zip(archive, dest)
            self.assertFalse(any(dest.rglob("*"))) if dest.exists() else None

    def test_rejects_absolute_path_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive = tmp / "evil.zip"
            _zip_with(archive, [("/etc/passwd", b"malicious")])
            with self.assertRaises(PathTraversalError):
                safe_extract_zip(archive, tmp / "dest")

    def test_rejects_windows_drive_letter_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive = tmp / "evil.zip"
            _zip_with(archive, [("C:/Windows/System32/evil.dll", b"malicious")])
            with self.assertRaises(PathTraversalError):
                safe_extract_zip(archive, tmp / "dest")

    def test_rejects_backslash_separator_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive = tmp / "evil.zip"
            _zip_with(archive, [("..\\..\\evil.exe", b"malicious")])
            with self.assertRaises(PathTraversalError):
                safe_extract_zip(archive, tmp / "dest")

    def test_nothing_extracted_when_one_entry_among_many_is_malicious(self):
        # validacao acontece ANTES de qualquer escrita -- nem as entradas legitimas
        # do mesmo pacote devem ser gravadas se houver uma entrada suspeita.
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive = tmp / "mixed.zip"
            _zip_with(archive, [("app/legit.exe", b"legit"), ("../escape.exe", b"malicious")])
            dest = tmp / "dest"
            with self.assertRaises(PathTraversalError):
                safe_extract_zip(archive, dest)
            self.assertFalse((dest / "app" / "legit.exe").exists())

    def test_directory_entries_are_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive = tmp / "pkg.zip"
            _zip_with(archive, [("empty_dir/", b"")])
            dest = tmp / "dest"
            safe_extract_zip(archive, dest)
            self.assertTrue((dest / "empty_dir").is_dir())


if __name__ == "__main__":
    unittest.main()
