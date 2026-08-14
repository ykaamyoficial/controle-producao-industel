from __future__ import annotations

import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services import installation_identity as identity_module
from app.services.configuration_service import ConfigurationService


class InstallationIdentityTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.config_path = Path(self._tmp.name) / "controle_producao_config.json"
        self._patch_config_path()

    def _patch_config_path(self):
        original = identity_module.get_config_path
        identity_module.get_config_path = lambda: self.config_path
        self.addCleanup(lambda: setattr(identity_module, "get_config_path", original))

    def test_generates_a_valid_uuid_on_first_call(self):
        identity = identity_module.get_or_create_installation_identity()
        uuid.UUID(identity.installation_id)  # nao levanta se for um UUID valido

    def test_second_call_returns_the_same_installation_id(self):
        first = identity_module.get_or_create_installation_identity()
        second = identity_module.get_or_create_installation_identity()
        self.assertEqual(first.installation_id, second.installation_id)

    def test_identity_survives_a_fresh_configuration_service_instance(self):
        # Simula reinicio do processo: nova instancia de ConfigurationService
        # apontada para o MESMO arquivo precisa ver o mesmo installation_id
        # (Secao 6: "deve sobreviver a reinicios e updates").
        first = identity_module.get_or_create_installation_identity()

        fresh_service = ConfigurationService(self.config_path)
        data = fresh_service.load()
        self.assertEqual(data["installation_identity"]["installation_id"], first.installation_id)

    def test_does_not_collide_with_existing_config_namespaces(self):
        identity_module.get_or_create_installation_identity()
        from app.services.configuration_service import get_configuration_service

        service = get_configuration_service(self.config_path)
        service.update(lambda data: {**data, "desktop_api": {"enabled": True}, "nomus_api": {"enabled": False}})
        data = service.load()
        self.assertIn("installation_identity", data)
        self.assertIn("desktop_api", data)
        self.assertIn("nomus_api", data)

    def test_machine_name_and_os_version_are_populated(self):
        identity = identity_module.get_or_create_installation_identity()
        self.assertTrue(identity.machine_name)
        self.assertTrue(identity.os_version)


if __name__ == "__main__":
    unittest.main()
