from __future__ import annotations

import unittest

from api.app.backup.connection import InvalidDatabaseUrlError, parse_database_url


class ParseDatabaseUrlTests(unittest.TestCase):
    def test_extracts_all_components_from_asyncpg_url(self):
        params = parse_database_url("postgresql+asyncpg://controle_dev:s3gredo@127.0.0.1:55432/controle_producao_dev")
        self.assertEqual(params.host, "127.0.0.1")
        self.assertEqual(params.port, 55432)
        self.assertEqual(params.user, "controle_dev")
        self.assertEqual(params.password, "s3gredo")
        self.assertEqual(params.dbname, "controle_producao_dev")

    def test_defaults_port_to_5432_when_absent(self):
        params = parse_database_url("postgresql+asyncpg://user:pass@dbhost/mydb")
        self.assertEqual(params.port, 5432)

    def test_rejects_empty_url(self):
        with self.assertRaises(InvalidDatabaseUrlError):
            parse_database_url("")

    def test_rejects_url_without_dbname(self):
        with self.assertRaises(InvalidDatabaseUrlError):
            parse_database_url("postgresql+asyncpg://user:pass@host:5432/")

    def test_rejects_non_postgresql_scheme(self):
        with self.assertRaises(InvalidDatabaseUrlError):
            parse_database_url("mysql://user:pass@host/db")


class ConnectionParamsSecurityTests(unittest.TestCase):
    def setUp(self):
        self.params = parse_database_url("postgresql+asyncpg://controle_dev:s3gredo@127.0.0.1:55432/controle_producao_dev")

    def test_as_args_never_includes_password(self):
        args = self.params.as_args()
        self.assertNotIn("s3gredo", args)
        self.assertEqual(args, ["-h", "127.0.0.1", "-p", "55432", "-U", "controle_dev"])

    def test_env_carries_pgpassword_and_preserves_base(self):
        env = self.params.env(base={"PATH": "/usr/bin"})
        self.assertEqual(env["PGPASSWORD"], "s3gredo")
        self.assertEqual(env["PATH"], "/usr/bin")

    def test_sanitize_for_log_redacts_password(self):
        message = "pg_dump failed: connection to server, password 's3gredo' rejected"
        sanitized = self.params.sanitize_for_log(message)
        self.assertNotIn("s3gredo", sanitized)
        self.assertIn("[redigido]", sanitized)

    def test_sanitize_for_log_is_noop_when_no_password(self):
        params = parse_database_url("postgresql+asyncpg://user@host/db")
        self.assertEqual(params.sanitize_for_log("texto qualquer"), "texto qualquer")


if __name__ == "__main__":
    unittest.main()
