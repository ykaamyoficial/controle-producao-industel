from __future__ import annotations

import unittest

from api.app.core.config import EXPECTED_DATABASE_REVISION, MINIMUM_DATABASE_REVISION
from api.app.core.migration_state import build_migration_state, known_revisions, script_head_revision


class MigrationStateTests(unittest.TestCase):
    """Testes puros: ScriptDirectory so le os arquivos em api/alembic/versions/,
    nenhum banco e acessado aqui."""

    def test_script_head_matches_expected_database_revision_constant(self):
        # Mantem EXPECTED_DATABASE_REVISION honesta: se alguem esquecer de
        # atualiza-la ao adicionar uma migration nova, este teste falha.
        self.assertEqual(script_head_revision(), EXPECTED_DATABASE_REVISION)

    def test_minimum_database_revision_is_a_known_revision(self):
        self.assertIn(MINIMUM_DATABASE_REVISION, known_revisions())

    def test_known_revisions_contains_all_migrations(self):
        self.assertEqual(len(known_revisions()), 23)
        self.assertIn("20260720_0001", known_revisions())
        self.assertIn(EXPECTED_DATABASE_REVISION, known_revisions())

    def test_state_at_head_is_consistent_and_reports_is_at_head(self):
        state = build_migration_state(EXPECTED_DATABASE_REVISION)
        self.assertTrue(state.is_at_head)
        self.assertTrue(state.migration_history_consistent)
        self.assertEqual(state.expected_head_revision, EXPECTED_DATABASE_REVISION)
        self.assertEqual(state.current_revision, EXPECTED_DATABASE_REVISION)

    def test_state_at_earlier_known_revision_is_consistent_but_not_at_head(self):
        state = build_migration_state("20260803_0013")
        self.assertFalse(state.is_at_head)
        self.assertTrue(state.migration_history_consistent)

    def test_state_with_unknown_revision_is_inconsistent(self):
        state = build_migration_state("does_not_exist_in_history")
        self.assertFalse(state.is_at_head)
        self.assertFalse(state.migration_history_consistent)

    def test_state_with_no_revision_applied_is_treated_as_consistent_but_not_at_head(self):
        # Banco sem alembic_version (unversioned) -- nao e uma divergencia de
        # historico, e apenas "ainda nao migrado".
        state = build_migration_state(None)
        self.assertFalse(state.is_at_head)
        self.assertTrue(state.migration_history_consistent)


if __name__ == "__main__":
    unittest.main()
