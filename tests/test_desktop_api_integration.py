from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app.integrations.api.auth_client import AuthApiClient
from app.integrations.api.client import DesktopApiClient
from app.integrations.api.compatibility import validate_api_compatibility
from app.integrations.api.config import DesktopApiSettings
from app.integrations.api.session import ExperimentalApiSession
from app.integrations.api.system_client import SystemApiClient
from app.integrations.api.token_store import ApiTokenStore


class FakeProtector:
    def protect(self, value: str) -> bytes:
        return ("protected:" + value.encode("utf-8").hex()).encode("ascii")

    def unprotect(self, encrypted: bytes) -> str:
        return bytes.fromhex(encrypted.decode("utf-8").removeprefix("protected:")).decode("utf-8")


@unittest.skipUnless(os.environ.get("DESKTOP_API_INTEGRATION") == "1", "Desktop API integration requires DESKTOP_API_INTEGRATION=1.")
class DesktopApiIntegrationTests(unittest.TestCase):
    def test_desktop_client_to_running_api(self):
        settings = DesktopApiSettings(
            enabled=True,
            base_url=os.environ.get("DESKTOP_API_BASE_URL", "http://127.0.0.1:8000"),
            connect_timeout=3,
            read_timeout=10,
        )
        username = os.environ.get("DESKTOP_API_USERNAME", "admin")
        password = os.environ.get("DESKTOP_API_PASSWORD", "Senha forte bootstrap 123")
        with tempfile.TemporaryDirectory() as temp_dir:
            client = DesktopApiClient(settings)
            system = SystemApiClient(client)
            self.assertEqual(system.health()["status"], "healthy")
            self.assertEqual(system.readiness()["status"], "ready")
            validate_api_compatibility(system.version())

            auth = AuthApiClient(client)
            token_store = ApiTokenStore(secret_path=Path(temp_dir) / "refresh.dpapi", protector=FakeProtector())
            session = ExperimentalApiSession(settings=settings, auth_client=auth, token_store=token_store)
            state = session.start(username, password)
            self.assertTrue(state.api_session_active)
            self.assertTrue(token_store.secret_path.exists())
            session.refresh_if_needed(force=True)
            refreshed_token_file = token_store.secret_path.read_bytes()
            self.assertNotIn(state.access_token.encode("utf-8"), refreshed_token_file)
            session.logout()
            self.assertFalse(token_store.secret_path.exists())
            client.close()


if __name__ == "__main__":
    unittest.main()
