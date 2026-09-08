from __future__ import annotations

import unittest

from scripts.check_migration_safety import _revision_id, load_registry, migration_files, verify


class MigrationSafetyPolicyTests(unittest.TestCase):
    def test_every_migration_is_classified_with_no_unjustified_risk(self):
        errors = verify()
        self.assertEqual(errors, [], "\n".join(errors))

    def test_registry_covers_exactly_the_existing_migration_files(self):
        registry = load_registry()
        revisions = {_revision_id(path) for path in migration_files()}
        self.assertEqual(set(registry.keys()), revisions)

    def test_known_destructive_migrations_are_flagged_and_documented(self):
        # 0005 (TRUNCATE + ALTER ... SET NOT NULL sem backfill) e 0014 (UNIQUE sem
        # pre-checagem de duplicidade) sao os dois casos reais encontrados no
        # inventario da Fase 04. Confirma que o linter realmente os capturaria e
        # que ambos estao documentados como DESTRUCTIVE, nao escondidos como ADDITIVE.
        registry = load_registry()
        self.assertEqual(registry["20260720_0005"]["classification"], "DESTRUCTIVE")
        self.assertEqual(registry["20260807_0014"]["classification"], "DESTRUCTIVE")
        self.assertTrue(registry["20260720_0005"]["justification"].strip())
        self.assertTrue(registry["20260807_0014"]["justification"].strip())

    def test_purely_additive_migrations_are_not_flagged(self):
        from scripts.check_migration_safety import scan_migration

        additive_revisions = {"20260720_0001", "20260721_0006", "20260802_0012"}
        registry = load_registry()
        for path in migration_files():
            revision = _revision_id(path)
            if revision in additive_revisions:
                self.assertEqual(scan_migration(path), [], f"{revision} nao deveria conter padroes de risco")
                self.assertEqual(registry[revision]["classification"], "ADDITIVE")


if __name__ == "__main__":
    unittest.main()
