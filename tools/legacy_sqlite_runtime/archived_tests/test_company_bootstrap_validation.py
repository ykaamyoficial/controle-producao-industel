from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from app.integrations.api.config import DesktopApiSettings
from app.integrations.api.models import SystemIdentity
from app.integrations.platform_bootstrap import CompanyResolution
from app.services.login_preferences import load_login_preferences, save_login_preferences
from app.services.backend_adapter import BackendService


class FakeConfigStore:
    def __init__(self):
        self.saved = None
        self.settings = DesktopApiSettings(enabled=False, base_url="", connect_timeout=3, read_timeout=10)

    def save_settings(self, **kwargs):
        self.saved = kwargs
        self.settings = DesktopApiSettings(
            enabled=bool(kwargs["enabled"]),
            base_url=str(kwargs["base_url"]),
            connect_timeout=float(kwargs["connect_timeout"]),
            read_timeout=float(kwargs["read_timeout"]),
        )
        return self.settings

    def load_settings(self):
        return self.settings


class FakeTokenStore:
    def __init__(self):
        self.cleared = False
        self.refresh_token = "refresh-token"

    def clear(self):
        self.cleared = True
        self.refresh_token = None

    def get_refresh_token(self):
        return self.refresh_token


class FakeOfficialStorage:
    def __init__(self):
        self.config_store = FakeConfigStore()
        self.token_store = FakeTokenStore()


class FakePlatformClient:
    def __init__(self, _base_url):
        pass

    def resolve_company(self, company_code: str, environment_type: str = "production") -> CompanyResolution:
        return CompanyResolution(
            company_id="company-id",
            company_name="teste01",
            company_code=company_code,
            access_code="AC-A90E-3242",
            environment_id="environment-id",
            environment_name="Producao",
            environment_type=environment_type,
            operational_api_url="http://host.docker.internal:8000",
        )

    def resolve_access_code(self, access_code: str, environment_type: str = "production") -> CompanyResolution:
        return CompanyResolution(
            company_id="company-id",
            company_name="teste01",
            company_code="teste01",
            access_code=access_code,
            environment_id="environment-id",
            environment_name="Producao",
            environment_type=environment_type,
            operational_api_url="http://host.docker.internal:8000",
        )


class CompanyBootstrapValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_data_dir = os.environ.get("CONTROLE_PRODUCAO_DATA_DIR")
        os.environ["CONTROLE_PRODUCAO_DATA_DIR"] = self.temp_dir.name

    def tearDown(self):
        if self.old_data_dir is None:
            os.environ.pop("CONTROLE_PRODUCAO_DATA_DIR", None)
        else:
            os.environ["CONTROLE_PRODUCAO_DATA_DIR"] = self.old_data_dir
        self.temp_dir.cleanup()

    def test_configure_company_validates_identity_before_saving(self):
        service = object.__new__(BackendService)
        service.config = {
            "company": "Industel",
            "desktop_api": {"enabled": True, "base_url": "http://127.0.0.1:8000", "connect_timeout": 3, "read_timeout": 10},
            "platform_api": {"enabled": True, "base_url": "http://127.0.0.1:8100", "environment_type": "production", "company_code": "", "company_name": ""},
        }
        service.official_proposal_storage = FakeOfficialStorage()

        saved = {}

        with (
            patch("app.services.backend_adapter.PlatformBootstrapClient", FakePlatformClient),
            patch.object(BackendService, "_validate_resolved_company_identity", return_value=_identity()) as validate,
            patch("app.services.backend_adapter.save_app_config", side_effect=lambda config: saved.update(config)),
        ):
            resolution = service.configure_company_by_code("teste01")

        self.assertEqual(resolution.company_code, "teste01")
        validate.assert_called_once()
        self.assertEqual(service.config["company"], "teste01")
        self.assertEqual(service.config["platform_api"]["company_code"], "teste01")
        self.assertEqual(service.config["platform_api"]["access_code"], "AC-A90E-3242")
        self.assertEqual(service.config["platform_api"]["operational_instance_id"], "35df9bf2-7597-4e79-a3af-f0d788a72fa4")
        self.assertEqual(service.config["desktop_api"]["base_url"], "http://127.0.0.1:8000")
        self.assertEqual(saved["platform_api"]["company_code"], "teste01")
        self.assertEqual(service.official_proposal_storage.config_store.saved["base_url"], "http://127.0.0.1:8000")

    def test_configure_company_by_access_code_saves_resolved_company(self):
        service = object.__new__(BackendService)
        service.config = {
            "company": "Industel",
            "desktop_api": {"enabled": True, "base_url": "http://127.0.0.1:8000", "connect_timeout": 3, "read_timeout": 10},
            "platform_api": {"enabled": True, "base_url": "http://127.0.0.1:8100", "environment_type": "production", "company_code": "", "company_name": ""},
        }
        service.official_proposal_storage = FakeOfficialStorage()

        with (
            patch("app.services.backend_adapter.PlatformBootstrapClient", FakePlatformClient),
            patch.object(BackendService, "_validate_resolved_company_identity", return_value=_identity()),
            patch("app.services.backend_adapter.save_app_config"),
        ):
            resolution = service.configure_company_by_access_code("AC-A90E-3242")

        self.assertEqual(resolution.company_code, "teste01")
        self.assertEqual(service.config["platform_api"]["company_code"], "teste01")
        self.assertEqual(service.config["platform_api"]["access_code"], "AC-A90E-3242")
        self.assertTrue(service.config["desktop_api"]["enabled"])

    def test_request_company_change_clears_company_session_and_operational_api(self):
        service = object.__new__(BackendService)
        storage = FakeOfficialStorage()
        service.official_proposal_storage = storage
        service.config = {
            "company": "teste01",
            "desktop_api": {"enabled": True, "base_url": "http://127.0.0.1:8000", "connect_timeout": 3, "read_timeout": 10},
            "platform_api": {
                "enabled": True,
                "base_url": "http://127.0.0.1:8100",
                "environment_type": "production",
                "company_code": "teste01",
                "company_name": "teste01",
                "access_code": "AC-A90E-3242",
                "environment_id": "environment-id",
                "operational_instance_id": "35df9bf2-7597-4e79-a3af-f0d788a72fa4",
            },
        }
        service.user = {"login": "admin", "api_superuser": True}
        service._api_access_token = None
        service._api_refresh_token = "refresh-token"
        save_login_preferences("admin", True)
        saved = {}

        with patch("app.services.backend_adapter.save_app_config", side_effect=lambda config: saved.update(config)):
            service.request_company_change()

        self.assertIsNone(service.user)
        self.assertIsNone(service._api_access_token)
        self.assertIsNone(service._api_refresh_token)
        self.assertTrue(storage.token_store.cleared)
        self.assertEqual(service.config["company"], "Industel")
        self.assertEqual(service.config["platform_api"]["company_code"], "")
        self.assertEqual(service.config["platform_api"]["company_name"], "")
        self.assertNotIn("access_code", service.config["platform_api"])
        self.assertNotIn("environment_id", service.config["platform_api"])
        self.assertNotIn("operational_instance_id", service.config["platform_api"])
        self.assertFalse(service.config["desktop_api"]["enabled"])
        self.assertEqual(service.config["desktop_api"]["base_url"], "")
        self.assertFalse(storage.config_store.saved["enabled"])
        self.assertEqual(storage.config_store.saved["base_url"], "")
        self.assertFalse(load_login_preferences()["remember_user"])
        self.assertEqual(saved["platform_api"]["company_code"], "")


def _identity() -> SystemIdentity:
    return SystemIdentity(
        instance_id="35df9bf2-7597-4e79-a3af-f0d788a72fa4",
        company_id=None,
        company_code="teste01",
        company_name="teste01",
        environment_type="production",
        api_name="controle-producao-api",
        api_version="0.8.0",
        api_stage="official-fiscal",
        database_revision="20260722_0009",
        database_status="compatible",
        minimum_desktop_version="2.5.2",
        maximum_desktop_version=None,
        supported_features=["auth", "auth_me", "permissions_read", "refresh", "logout"],
    )


if __name__ == "__main__":
    unittest.main()
