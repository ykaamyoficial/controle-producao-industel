from __future__ import annotations

import unittest

from api.app.deployment.schema_compatibility import evaluate_rollback_schema_compatibility


class SchemaCompatibilityTests(unittest.TestCase):
    """Usa o registro de risco REAL da Fase 04 (api/alembic/migration_risk_registry.json)
    -- 20260807_0014 e 20260720_0005 sao as duas unicas revisoes DESTRUCTIVE
    conhecidas no historico atual, entao servem como fixtures deterministicas
    sem precisar de um registro forjado."""

    def test_same_revision_is_always_compatible(self):
        result = evaluate_rollback_schema_compatibility(from_revision="20260810_0015", to_revision="20260810_0015")
        self.assertTrue(result.compatible)

    def test_only_additive_or_transitional_migrations_since_previous_is_compatible(self):
        # 20260802_0012 -> 20260803_0013: so ADDITIVE/TRANSITIONAL no caminho.
        result = evaluate_rollback_schema_compatibility(from_revision="20260802_0012", to_revision="20260803_0013")
        self.assertTrue(result.compatible)
        self.assertEqual(result.blocking_revisions, ())

    def test_destructive_migration_in_range_blocks_rollback(self):
        # 20260803_0013 -> 20260810_0015 atravessa 20260807_0014 (DESTRUCTIVE).
        result = evaluate_rollback_schema_compatibility(from_revision="20260803_0013", to_revision="20260810_0015")
        self.assertFalse(result.compatible)
        self.assertIn("20260807_0014", result.blocking_revisions)

    def test_destructive_boundary_itself_blocks_rollback(self):
        result = evaluate_rollback_schema_compatibility(from_revision="20260802_0012", to_revision="20260807_0014")
        self.assertFalse(result.compatible)
        self.assertEqual(result.blocking_revisions, ("20260807_0014",))

    def test_from_revision_matching_the_destructive_migration_itself_does_not_reblock_it(self):
        # a revisao DESTRUCTIVE ja fazia parte do "from" (a release anterior ja
        # rodava sobre ela) -- so migrations APOS from_revision contam.
        result = evaluate_rollback_schema_compatibility(from_revision="20260807_0014", to_revision="20260810_0015")
        self.assertTrue(result.compatible)

    def test_unknown_from_revision_fails_closed(self):
        result = evaluate_rollback_schema_compatibility(from_revision="unknown-rev", to_revision="20260810_0015")
        self.assertFalse(result.compatible)

    def test_unknown_to_revision_fails_closed(self):
        result = evaluate_rollback_schema_compatibility(from_revision="20260810_0015", to_revision="unknown-rev")
        self.assertFalse(result.compatible)

    def test_missing_current_database_revision_fails_closed(self):
        result = evaluate_rollback_schema_compatibility(from_revision="20260810_0015", to_revision=None)
        self.assertFalse(result.compatible)

    def test_missing_previous_release_revision_fails_closed(self):
        result = evaluate_rollback_schema_compatibility(from_revision=None, to_revision="20260810_0015")
        self.assertFalse(result.compatible)

    def test_revisions_out_of_order_fails_closed_instead_of_raising(self):
        result = evaluate_rollback_schema_compatibility(from_revision="20260810_0015", to_revision="20260720_0001")
        self.assertFalse(result.compatible)


if __name__ == "__main__":
    unittest.main()
