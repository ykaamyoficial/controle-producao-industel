from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.services import production_repository
from app.services.migration_runner import MigrationError, apply_migrations, migration_status


ROOT = Path(__file__).resolve().parents[1]
REAL_DB = ROOT / "app" / "data" / "controle_producao.db"


class MigrationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="industel_migration_test_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def connect(self, path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def assert_integrity(self, conn: sqlite3.Connection):
        self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_fresh_database_migrates_once_and_initializes(self):
        db_path = self.temp_dir / "fresh.db"
        with self.connect(db_path) as conn:
            self.assertEqual(apply_migrations(conn), [1, 2, 3, 4, 5, 6, 7, 8])
            self.assertEqual(apply_migrations(conn), [])
            production_repository.initialize_database(conn)
            self.assert_integrity(conn)
            versions = conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
            self.assertEqual([row[0] for row in versions], [1, 2, 3, 4, 5, 6, 7, 8])
            self.assertTrue(all(item["applied"] for item in migration_status(conn)))

    def test_copy_of_current_database_migrates_without_data_loss(self):
        copied_db = self.temp_dir / "current_copy.db"
        shutil.copy2(REAL_DB, copied_db)
        with self.connect(copied_db) as conn:
            before = conn.execute("SELECT COUNT(*) FROM processos").fetchone()[0]
            apply_migrations(conn)
            production_repository.initialize_database(conn)
            after = conn.execute("SELECT COUNT(*) FROM processos").fetchone()[0]
            self.assertEqual(before, after)
            self.assert_integrity(conn)

    def test_backup_file_exists_and_is_valid(self):
        backup_root = ROOT / "backups"
        backups = sorted(backup_root.glob("pre_migrations_*/controle_producao.db"))
        self.assertTrue(backups, "Backup preparatorio nao encontrado.")
        with self.connect(backups[-1]) as conn:
            self.assert_integrity(conn)

    def test_failed_migration_rolls_back_and_is_not_registered(self):
        migrations_dir = self.temp_dir / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "001_valid.sql").write_text(
            "CREATE TABLE stable_table (id INTEGER PRIMARY KEY);",
            encoding="utf-8",
        )
        (migrations_dir / "002_broken.sql").write_text(
            "CREATE TABLE rollback_table (id INTEGER);\n"
            "INSERT INTO table_that_does_not_exist(id) VALUES (1);",
            encoding="utf-8",
        )
        with self.connect(self.temp_dir / "rollback.db") as conn:
            with self.assertRaises(MigrationError):
                apply_migrations(conn, migrations_dir)
            self.assertIsNotNone(
                conn.execute(
                    "SELECT name FROM sqlite_master WHERE name = 'stable_table'"
                ).fetchone()
            )
            self.assertIsNone(
                conn.execute(
                    "SELECT name FROM sqlite_master WHERE name = 'rollback_table'"
                ).fetchone()
            )
            versions = conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
            self.assertEqual([row[0] for row in versions], [1])

    def test_checksum_is_stable_with_windows_line_endings(self):
        migrations_dir = self.temp_dir / "line_endings"
        migrations_dir.mkdir()
        migration_path = migrations_dir / "001_line_endings.sql"
        migration_path.write_bytes(
            b"CREATE TABLE newline_test (id INTEGER);\n"
        )
        with self.connect(self.temp_dir / "line_endings.db") as conn:
            self.assertEqual(apply_migrations(conn, migrations_dir), [1])
            migration_path.write_bytes(
                b"CREATE TABLE newline_test (id INTEGER);\r\n"
            )
            self.assertEqual(apply_migrations(conn, migrations_dir), [])


if __name__ == "__main__":
    unittest.main()
