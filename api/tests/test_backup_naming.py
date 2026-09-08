from __future__ import annotations

import unittest
from datetime import datetime, timezone

from api.app.backup.naming import build_backup_id, dump_filename, manifest_filename


class BuildBackupIdTests(unittest.TestCase):
    def test_id_is_deterministic_given_a_fixed_clock_except_random_suffix(self):
        moment = datetime(2026, 8, 10, 20, 15, 30, tzinfo=timezone.utc)
        backup_id = build_backup_id(server_version="0.8.0", database_revision="20260810_0015", now=moment)
        self.assertTrue(backup_id.startswith("predeploy_20260810T201530Z_server-0.8.0_db-rev20260810_0015_"))
        suffix = backup_id.rsplit("_", 1)[-1]
        self.assertEqual(len(suffix), 8)
        int(suffix, 16)  # deve ser hexadecimal

    def test_two_calls_never_collide(self):
        moment = datetime(2026, 8, 10, 20, 15, 30, tzinfo=timezone.utc)
        first = build_backup_id(server_version="0.8.0", database_revision="20260810_0015", now=moment)
        second = build_backup_id(server_version="0.8.0", database_revision="20260810_0015", now=moment)
        self.assertNotEqual(first, second)

    def test_never_produces_a_fixed_or_overwritable_name(self):
        backup_id = build_backup_id(server_version="0.8.0", database_revision="20260810_0015")
        self.assertNotIn(backup_id, {"backup", "ultimo", "latest"})
        self.assertNotEqual(dump_filename(backup_id), "backup.dump")
        self.assertNotEqual(dump_filename(backup_id), "ultimo.dump")

    def test_sanitizes_unsafe_characters_in_components(self):
        backup_id = build_backup_id(server_version="0.8.0/beta", database_revision="rev with spaces")
        self.assertNotIn("/", backup_id)
        self.assertNotIn(" ", backup_id)

    def test_dump_and_manifest_filenames_share_the_backup_id(self):
        backup_id = "predeploy_20260810T201530Z_server-0.8.0_db-rev20260810_0015_a1b2c3d4"
        self.assertEqual(dump_filename(backup_id), f"{backup_id}.dump")
        self.assertEqual(manifest_filename(backup_id), f"{backup_id}.manifest.json")


if __name__ == "__main__":
    unittest.main()
