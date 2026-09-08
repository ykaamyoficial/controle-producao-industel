from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import backend_adapter


class PostgreSqlOnlyConfigTests(unittest.TestCase):
    def test_load_app_config_removes_legacy_sqlite_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "controle_producao_config.json"
            example_path = root / "controle_producao_config.example.json"
            config_path.write_text(
                json.dumps(
                    {
                        "company": "Industel",
                        "color_palette": "claro",
                        "postgresql_official_proposals_enabled": True,
                        "db_path": "controle_producao.db",
                        "backup_dir": "backups",
                        "backup_keep": 20,
                        "desktop_api": {
                            "enabled": True,
                            "base_url": "http://127.0.0.1:8000",
                            "connect_timeout": 3,
                            "read_timeout": 10,
                        },
                    }
                ),
                encoding="utf-8",
            )
            example_path.write_text("{}", encoding="utf-8")

            with patch.object(backend_adapter, "ensure_app_data_dirs", return_value=None), patch.object(
                backend_adapter, "get_config_path", return_value=config_path
            ), patch.object(backend_adapter, "get_config_example_path", return_value=example_path):
                config = backend_adapter.load_app_config()

            self.assertNotIn("postgresql_official_proposals_enabled", config)
            self.assertNotIn("db_path", config)
            self.assertNotIn("backup_dir", config)
            self.assertNotIn("backup_keep", config)
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertNotIn("db_path", saved)
            self.assertEqual(saved["desktop_api"]["base_url"], "http://127.0.0.1:8000")

    def test_backend_service_initializes_without_sqlite_runtime(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "controle_producao_config.json"
            example_path = root / "controle_producao_config.example.json"
            config_path.write_text(
                json.dumps(
                    {
                        "company": "Industel",
                        "color_palette": "claro",
                        "desktop_api": {
                            "enabled": True,
                            "base_url": "http://127.0.0.1:8000",
                            "connect_timeout": 3,
                            "read_timeout": 10,
                        },
                    }
                ),
                encoding="utf-8",
            )
            example_path.write_text("{}", encoding="utf-8")

            with patch.object(backend_adapter, "ensure_app_data_dirs", return_value=None), patch.object(
                backend_adapter, "get_config_path", return_value=config_path
            ), patch.object(backend_adapter, "get_config_example_path", return_value=example_path):
                service = backend_adapter.BackendService()

            self.assertTrue(service.official_proposals_enabled())
            self.assertFalse(hasattr(service, "conn"))
            self.assertFalse(hasattr(service, "repo"))
            self.assertFalse(hasattr(backend_adapter.legacy, "db_connect"))
            self.assertFalse(hasattr(backend_adapter.legacy, "initialize_database"))

    def test_backend_import_does_not_load_sqlite_repository_module(self):
        code = (
            "import sys;"
            "sys.modules.pop('app.services.backend_adapter', None);"
            "sys.modules.pop('app.services.production_repository', None);"
            "sys.modules.pop('tools.legacy_sqlite_runtime.production_repository', None);"
            "import app.services.backend_adapter;"
            "loaded = 'app.services.production_repository' in sys.modules or "
            "'tools.legacy_sqlite_runtime.production_repository' in sys.modules;"
            "raise SystemExit(1 if loaded else 0)"
        )
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1])

        self.assertEqual(result.returncode, 0)

    def test_production_core_is_archived_and_not_runtime_entrypoint(self):
        code = "\n".join(
            [
                "import app.services.production_core as module",
                "try:",
                "    module.Repository",
                "except Exception as exc:",
                "    raise SystemExit(0 if 'arquivado' in str(exc) else 1)",
                "raise SystemExit(1)",
            ]
        )
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1])

        self.assertEqual(result.returncode, 0)

    def test_sqlite_report_services_are_archived_in_official_runtime(self):
        for module_name, attribute, message in (
            ("app.services.operational_reports", "OperationalReportsService", "arquivado"),
            ("app.services.executive_dashboard", "ExecutiveDashboardService", "arquivado"),
            ("app.services.sqlite_safety", "inspect_database", "arquivado"),
            ("app.services.migration_runner", "apply_migrations", "arquivado"),
            ("app.services.production_repository", "Repository", "arquivado"),
        ):
            code = "\n".join(
                [
                    f"import {module_name} as module",
                    "try:",
                    f"    module.{attribute}",
                    "except Exception as exc:",
                    f"    raise SystemExit(0 if {message!r} in str(exc) else 1)",
                    "raise SystemExit(1)",
                ]
            )
            result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1])
            self.assertEqual(result.returncode, 0, module_name)


if __name__ == "__main__":
    unittest.main()

