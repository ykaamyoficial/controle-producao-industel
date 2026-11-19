from __future__ import annotations

import unittest

from api.app.deployment.schema_compatibility import evaluate_rollback_schema_compatibility


class SchemaCompatibilityTests(unittest.TestCase):
    """A readiness da imagem exige revisao IGUAL a esperada
    (api/app/database/health.py), entao so banco na mesma revisao da release
    alvo e compativel. Antes a regra olhava so migrations DESTRUCTIVE no
    caminho e liberava, por exemplo, 0038 -> 0047 (auditoria de deploy, A2);
    os testes antigos que fixavam "so ADDITIVE no caminho = compativel"
    foram trocados por estes. Usa revisoes reais, sem banco."""

    def test_same_revision_is_compatible(self):
        result = evaluate_rollback_schema_compatibility(from_revision="20261014_0038", to_revision="20261014_0038")
        self.assertTrue(result.compatible)

    def test_database_ahead_with_only_additive_migrations_is_incompatible(self):
        # caso real da auditoria: 0039-0047 nao tem DESTRUCTIVE, mas a imagem
        # 0038 recusa ficar pronta sobre 0047.
        result = evaluate_rollback_schema_compatibility(from_revision="20261014_0038", to_revision="20261109_0047")
        self.assertFalse(result.compatible)
        self.assertIn("20261109_0047", result.reason)
        self.assertIn("dump pre-deploy", result.reason)

    def test_database_one_additive_migration_ahead_is_incompatible(self):
        # 20260802_0012 -> 20260803_0013: so ADDITIVE/TRANSITIONAL (antes era compativel).
        result = evaluate_rollback_schema_compatibility(from_revision="20260802_0012", to_revision="20260803_0013")
        self.assertFalse(result.compatible)

    def test_database_behind_previous_release_is_incompatible(self):
        result = evaluate_rollback_schema_compatibility(from_revision="20261109_0047", to_revision="20261014_0038")
        self.assertFalse(result.compatible)
        self.assertIn("dump pre-deploy", result.reason)

    def test_unknown_from_revision_fails_closed(self):
        result = evaluate_rollback_schema_compatibility(from_revision="unknown-rev", to_revision="20260810_0015")
        self.assertFalse(result.compatible)
        self.assertIn("desconhecida", result.reason)

    def test_unknown_to_revision_fails_closed(self):
        result = evaluate_rollback_schema_compatibility(from_revision="20260810_0015", to_revision="unknown-rev")
        self.assertFalse(result.compatible)

    def test_same_unknown_revision_on_both_sides_fails_closed(self):
        result = evaluate_rollback_schema_compatibility(from_revision="unknown-rev", to_revision="unknown-rev")
        self.assertFalse(result.compatible)

    def test_missing_or_empty_current_database_revision_fails_closed(self):
        for revision in (None, ""):
            with self.subTest(revision=revision):
                result = evaluate_rollback_schema_compatibility(from_revision="20260810_0015", to_revision=revision)
                self.assertFalse(result.compatible)
                self.assertIn("dump pre-deploy", result.reason)

    def test_missing_or_empty_previous_release_revision_fails_closed(self):
        for revision in (None, ""):
            with self.subTest(revision=revision):
                result = evaluate_rollback_schema_compatibility(from_revision=revision, to_revision="20260810_0015")
                self.assertFalse(result.compatible)


if __name__ == "__main__":
    unittest.main()
