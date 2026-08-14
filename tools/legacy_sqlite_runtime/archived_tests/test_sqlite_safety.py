from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from tools.legacy_sqlite_runtime.sqlite_safety import (
    DatabaseSafetyError,
    inspect_database,
    is_network_path,
    recover_database,
    require_healthy_database,
    safe_backup,
)


class SQLiteSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _healthy_db(self) -> Path:
        path = self.root / "healthy.db"
        with closing(sqlite3.connect(path)) as conn:
            conn.execute("CREATE TABLE usuarios(id INTEGER PRIMARY KEY)")
            conn.execute("CREATE TABLE processos(id INTEGER PRIMARY KEY)")
            conn.execute("CREATE TABLE historico_status(id INTEGER PRIMARY KEY)")
            conn.commit()
        return path

    def test_missing_database_is_reported(self):
        health = inspect_database(self.root / "missing.db")
        self.assertFalse(health.exists)
        self.assertFalse(health.integrity_ok)

    def test_database_without_read_permission_is_blocked(self):
        path = self._healthy_db()
        with patch("tools.legacy_sqlite_runtime.sqlite_safety.os.access", return_value=False):
            health = inspect_database(path)
        self.assertFalse(health.readable)
        with patch("tools.legacy_sqlite_runtime.sqlite_safety.inspect_database", return_value=health):
            with self.assertRaises(DatabaseSafetyError):
                require_healthy_database(path)

    def test_corrupted_database_is_blocked(self):
        path = self.root / "corrupt.db"
        path.write_bytes(b"not a sqlite database")
        health = inspect_database(path)
        self.assertFalse(health.integrity_ok)
        with self.assertRaises(DatabaseSafetyError):
            require_healthy_database(path)

    def test_integrity_failure_is_blocked(self):
        path = self._healthy_db()
        with patch("tools.legacy_sqlite_runtime.sqlite_safety.inspect_database") as inspect:
            inspect.return_value = type("Health", (), {"exists": True, "readable": True, "integrity_ok": False, "foreign_key_errors": 0})()
            with self.assertRaises(DatabaseSafetyError):
                require_healthy_database(path)

    def test_safe_backup_is_valid_and_non_empty(self):
        source = self._healthy_db()
        target = safe_backup(source, self.root / "backups", "teste")
        self.assertTrue(target.exists())
        self.assertGreater(target.stat().st_size, 0)
        self.assertTrue(inspect_database(target).integrity_ok)

    def test_corrupted_source_is_not_backed_up_as_valid(self):
        source = self.root / "bad.db"
        source.write_bytes(b"broken")
        with self.assertRaises(DatabaseSafetyError):
            safe_backup(source, self.root / "backups", "teste")

    def test_recovery_failure_preserves_original_and_report(self):
        source = self.root / "bad.db"
        source.write_bytes(b"broken")
        with patch("tools.legacy_sqlite_runtime.sqlite_safety.shutil.which", return_value=None):
            result = recover_database(source, self.root / "recovery")
        self.assertFalse(result["success"])
        self.assertTrue(Path(result["preserved"]).exists())
        self.assertTrue(Path(result["report"]).exists())
        self.assertEqual(source.read_bytes(), b"broken")

    def test_unc_path_is_detected(self):
        self.assertTrue(is_network_path(r"\\SERVIDOR\dados\controle.db"))
        self.assertFalse(is_network_path(r"C:\dados\controle.db"))

    def test_unc_validation_uses_native_path_not_sqlite_uri(self):
        path = Path(r"\\SERVIDOR\dados\controle.db")
        connection = unittest.mock.MagicMock()
        integrity_cursor = unittest.mock.MagicMock()
        integrity_cursor.fetchall.return_value = [("ok",)]
        foreign_cursor = unittest.mock.MagicMock()
        foreign_cursor.fetchall.return_value = []
        connection.execute.side_effect = [unittest.mock.MagicMock(), integrity_cursor, foreign_cursor]
        with patch.object(Path, "exists", return_value=True), patch.object(Path, "is_file", return_value=True), patch.object(
            Path, "parent", new_callable=unittest.mock.PropertyMock, return_value=Path(r"\\SERVIDOR\dados")
        ), patch("tools.legacy_sqlite_runtime.sqlite_safety.os.access", return_value=True), patch(
            "tools.legacy_sqlite_runtime.sqlite_safety.sqlite3.connect", return_value=connection
        ) as connect:
            health = inspect_database(path)
        connect.assert_called_once_with(str(path), timeout=8)
        self.assertTrue(health.integrity_ok)

    def test_database_in_exclusive_use_returns_unhealthy_instead_of_hanging(self):
        path = self._healthy_db()
        blocker = sqlite3.connect(path, timeout=0.1)
        try:
            blocker.execute("BEGIN EXCLUSIVE")
            health = inspect_database(path, timeout=0.05)
            self.assertFalse(health.integrity_ok)
            self.assertIn("locked", health.detail.lower())
        finally:
            blocker.rollback()
            blocker.close()


if __name__ == "__main__":
    unittest.main()
