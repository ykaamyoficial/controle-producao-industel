from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from api.app.core.config import EXPECTED_DATABASE_REVISION
from api.app.database.health import DatabaseCheck
from api.app.health.checks.database import run_database_and_schema_checks
from api.app.health.checks.version import run_version_check
from api.app.health.models import HealthStatus


def _run(check: DatabaseCheck):
    async def _inner():
        with patch("api.app.health.checks.database.database_check", new=AsyncMock(return_value=check)):
            return await run_database_and_schema_checks()

    import asyncio

    return asyncio.run(_inner())


class DatabaseAndSchemaCheckTests(unittest.TestCase):
    def test_connected_and_compatible_revision_passes_both_checks(self):
        db_result, schema_result, raw = _run(DatabaseCheck(status="connected", revision=EXPECTED_DATABASE_REVISION, revision_status="compatible"))
        self.assertEqual(db_result.status, HealthStatus.PASS)
        self.assertTrue(db_result.critical)
        self.assertEqual(schema_result.status, HealthStatus.PASS)
        self.assertTrue(schema_result.critical)
        self.assertEqual(raw.revision, EXPECTED_DATABASE_REVISION)

    def test_not_configured_fails_database_check_with_specific_error_code(self):
        db_result, schema_result, _ = _run(DatabaseCheck(status="not_configured", revision=None, revision_status="not_configured"))
        self.assertEqual(db_result.status, HealthStatus.FAIL)
        self.assertEqual(db_result.error_code, "DATABASE_NOT_CONFIGURED")
        self.assertEqual(schema_result.status, HealthStatus.FAIL)

    def test_unavailable_database_fails_without_leaking_internal_detail(self):
        db_result, _, _ = _run(DatabaseCheck(status="unavailable", revision=None, revision_status="unavailable"))
        self.assertEqual(db_result.status, HealthStatus.FAIL)
        self.assertEqual(db_result.error_code, "DATABASE_UNAVAILABLE")
        self.assertNotIn("Traceback", db_result.message)
        self.assertNotIn("asyncpg", db_result.message.lower())

    def test_divergent_revision_is_classified_as_incompatible_not_silently_accepted(self):
        _, schema_result, _ = _run(DatabaseCheck(status="connected", revision="20260803_0013", revision_status="incompatible"))
        self.assertEqual(schema_result.status, HealthStatus.FAIL)
        self.assertEqual(schema_result.error_code, "SCHEMA_REVISION_MISMATCH")
        self.assertIn("20260803_0013", schema_result.message)

    def test_unversioned_database_fails_schema_check_explicitly(self):
        _, schema_result, _ = _run(DatabaseCheck(status="connected", revision=None, revision_status="unversioned"))
        self.assertEqual(schema_result.status, HealthStatus.FAIL)
        self.assertEqual(schema_result.error_code, "SCHEMA_UNVERSIONED")

    def test_both_checks_are_critical(self):
        db_result, schema_result, _ = _run(DatabaseCheck(status="connected", revision=EXPECTED_DATABASE_REVISION, revision_status="compatible"))
        self.assertTrue(db_result.critical)
        self.assertTrue(schema_result.critical)


class VersionCheckTests(unittest.TestCase):
    def test_passes_and_is_not_critical(self):
        result = run_version_check()
        self.assertEqual(result.status, HealthStatus.PASS)
        self.assertFalse(result.critical)
        self.assertIn("server_version", result.message)


if __name__ == "__main__":
    unittest.main()
