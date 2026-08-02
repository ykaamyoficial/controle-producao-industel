from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services import support_diagnostics


class PostgreSqlSupportDiagnosticsTests(unittest.TestCase):
    def test_diagnostic_report_describes_postgresql_api_without_local_database_probe(self):
        with patch.object(support_diagnostics, "diagnose_update_endpoint", return_value={"status": "ok"}):
            report = support_diagnostics.build_diagnostic_report("ignored.db")

        self.assertEqual(report["database"]["engine"], "PostgreSQL")
        self.assertEqual(report["database"]["access"], "API")
        self.assertEqual(report["database"]["status"], "managed_by_server")
        self.assertIn("nao acessa banco", report["database"]["detail"])


if __name__ == "__main__":
    unittest.main()
