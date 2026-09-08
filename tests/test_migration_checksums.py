from __future__ import annotations

import unittest

from scripts.check_migration_checksums import verify


class MigrationChecksumTests(unittest.TestCase):
    def test_migration_checksums_match_manifest(self):
        self.assertEqual(verify(), [])


if __name__ == "__main__":
    unittest.main()
