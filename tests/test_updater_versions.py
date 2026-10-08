from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.updater import versions as v


def _install(root: Path, version: str) -> Path:
    folder = root / "versions" / version
    folder.mkdir(parents=True)
    (folder / v.APP_EXECUTABLE_NAME).write_text(version)
    return folder


class VersionsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_version_key_orders_numerically(self):
        self.assertGreater(v.version_key("2.10.0"), v.version_key("2.9.9"))
        with self.assertRaises(ValueError):
            v.version_key("2.8")

    def test_version_dir_rejects_traversal(self):
        with self.assertRaises(v.VersionLayoutError):
            v.version_dir(self.root, "..\\evil")

    def test_pointer_roundtrip_and_atomic_leaves_no_temp(self):
        v.write_pointer(self.root, "2.9.0", previous_version="2.8.0")
        pointer = v.read_pointer(self.root)
        self.assertEqual((pointer.version, pointer.previous_version), ("2.9.0", "2.8.0"))
        self.assertEqual([p.name for p in self.root.iterdir()], ["current.json"])

    def test_read_pointer_tolerates_corruption(self):
        (self.root / "current.json").write_text("{nao e json")
        self.assertIsNone(v.read_pointer(self.root))
        (self.root / "current.json").write_text(json.dumps({"version": "../x"}))
        self.assertIsNone(v.read_pointer(self.root))

    def test_resolve_active_prefers_valid_pointer(self):
        _install(self.root, "2.8.0")
        _install(self.root, "2.9.0")
        v.write_pointer(self.root, "2.8.0")
        self.assertEqual(v.resolve_active_version(self.root), "2.8.0")

    def test_resolve_active_self_heals_when_pointer_target_missing(self):
        _install(self.root, "2.8.0")
        _install(self.root, "2.9.0")
        v.write_pointer(self.root, "3.0.0")
        self.assertEqual(v.resolve_active_version(self.root), "2.9.0")

    def test_resolve_active_none_when_nothing_installed(self):
        self.assertIsNone(v.resolve_active_version(self.root))

    def test_list_ignores_dirs_without_executable_and_tmp(self):
        _install(self.root, "2.8.0")
        (self.root / "versions" / "2.9.0").mkdir()
        (self.root / "versions" / "3.0.0.tmp").mkdir()
        self.assertEqual(v.list_installed_versions(self.root), ["2.8.0"])

    def test_cleanup_keeps_active_previous_and_newest(self):
        for version in ("2.5.0", "2.6.0", "2.7.0", "2.8.0", "2.9.0"):
            _install(self.root, version)
        (self.root / "versions" / "3.0.0.tmp").mkdir()
        v.write_pointer(self.root, "2.9.0", previous_version="2.8.0")
        removed, deferred = v.cleanup_old_versions(self.root, keep=2)
        self.assertEqual(sorted(removed), ["2.5.0", "2.6.0", "2.7.0", "3.0.0.tmp"])
        self.assertEqual(deferred, [])
        self.assertEqual(v.list_installed_versions(self.root), ["2.9.0", "2.8.0"])

    def test_cleanup_protects_requested_versions(self):
        for version in ("2.5.0", "2.8.0", "2.9.0"):
            _install(self.root, version)
        v.write_pointer(self.root, "2.9.0")
        v.cleanup_old_versions(self.root, keep=1, protect=("2.5.0",))
        self.assertIn("2.5.0", v.list_installed_versions(self.root))

    def test_is_versioned_layout(self):
        self.assertFalse(v.is_versioned_layout(self.root))
        _install(self.root, "2.8.0")
        v.write_pointer(self.root, "2.8.0")
        self.assertTrue(v.is_versioned_layout(self.root))


if __name__ == "__main__":
    unittest.main()
