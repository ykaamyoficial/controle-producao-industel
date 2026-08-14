from __future__ import annotations

import unittest

from app.integrations.api.exceptions import (
    ApiAuthenticationError,
    ApiConnectionError,
    ApiPermissionError,
    ApiTimeoutError,
    ApiUnavailableError,
)
from app.integrations.api.models import SystemCompatibilityDto
from app.services.compatibility_check import CompatibilityCheckResult, run_compatibility_check
from app.versioning.compatibility import evaluate_startup_compatibility
from app.versioning.models import CompatibilityStatus


def _dto(**overrides) -> SystemCompatibilityDto:
    defaults = dict(
        server_version="3.2.0",
        api_contract_version="v1",
        database_revision="20260810_0015",
        minimum_desktop_version="3.1.0",
        recommended_desktop_version="3.2.0",
        maintenance_mode=False,
    )
    defaults.update(overrides)
    return SystemCompatibilityDto(**defaults)


class EvaluateStartupCompatibilityTests(unittest.TestCase):
    """Regra pura (sem rede) de decisao de compatibilidade de startup."""

    def _evaluate(self, dto: SystemCompatibilityDto, desktop_version: str) -> CompatibilityStatus:
        return evaluate_startup_compatibility(
            maintenance_mode=dto.maintenance_mode,
            api_contract_version=dto.api_contract_version,
            minimum_desktop_version=dto.minimum_desktop_version,
            recommended_desktop_version=dto.recommended_desktop_version,
            server_version=dto.server_version,
            database_schema_version=dto.database_revision,
            desktop_version=desktop_version,
            supported_api_contract_version="v1",
        )

    def test_version_equal_to_recommended_is_compatible(self):
        self.assertEqual(self._evaluate(_dto(), "3.2.0"), CompatibilityStatus.COMPATIBLE)

    def test_version_between_minimum_and_recommended_is_update_available(self):
        self.assertEqual(self._evaluate(_dto(), "3.1.5"), CompatibilityStatus.UPDATE_AVAILABLE)

    def test_version_below_minimum_is_update_required(self):
        self.assertEqual(self._evaluate(_dto(), "3.0.9"), CompatibilityStatus.UPDATE_REQUIRED)

    def test_version_above_recommended_with_valid_contract_is_compatible(self):
        # A politica define minimo/recomendado, nao um maximo suportado (secao 13 da Fase 03).
        self.assertEqual(self._evaluate(_dto(), "9.9.9"), CompatibilityStatus.COMPATIBLE)

    def test_maintenance_mode_wins_over_everything_else(self):
        dto = _dto(maintenance_mode=True)
        self.assertEqual(self._evaluate(dto, "1.0.0"), CompatibilityStatus.MAINTENANCE)
        self.assertEqual(self._evaluate(dto, "9.9.9"), CompatibilityStatus.MAINTENANCE)

    def test_unsupported_api_contract_is_incompatible(self):
        dto = _dto(api_contract_version="v2")
        self.assertEqual(self._evaluate(dto, "3.2.0"), CompatibilityStatus.INCOMPATIBLE)

    def test_server_version_is_never_used_as_contract_substitute(self):
        # server_version muda (correcao interna do backend) mas api_contract_version continua
        # suportado -> nao deve virar INCOMPATIBLE por causa do server_version.
        dto = _dto(server_version="3.7.2", api_contract_version="v1")
        self.assertEqual(self._evaluate(dto, "3.2.0"), CompatibilityStatus.COMPATIBLE)

    def test_database_schema_never_influences_the_decision(self):
        result_a = self._evaluate(_dto(database_revision="20260810_0015"), "3.2.0")
        result_b = self._evaluate(_dto(database_revision="qualquer_outra_revisao"), "3.2.0")
        self.assertEqual(result_a, result_b)
        self.assertEqual(result_a, CompatibilityStatus.COMPATIBLE)

    def test_invalid_local_desktop_version_raises_value_error(self):
        with self.assertRaises(ValueError):
            self._evaluate(_dto(), "nao-e-semver")

    def test_invalid_remote_policy_raises_value_error(self):
        dto = _dto(minimum_desktop_version="nao-e-semver")
        with self.assertRaises(ValueError):
            self._evaluate(dto, "3.2.0")


class MinimumApiVersionTests(unittest.TestCase):
    """Fase 6 - Compatibilidade de Versoes, Secao 6/7 (REGRA B): protege o
    caso simetrico ao minimo do Desktop -- um Desktop novo apontando para
    uma API antiga demais, mesmo quando o contrato ('v1') ainda bate."""

    def _evaluate(self, dto: SystemCompatibilityDto, desktop_version: str, *, minimum_api_version: str) -> CompatibilityStatus:
        return evaluate_startup_compatibility(
            maintenance_mode=dto.maintenance_mode,
            api_contract_version=dto.api_contract_version,
            minimum_desktop_version=dto.minimum_desktop_version,
            recommended_desktop_version=dto.recommended_desktop_version,
            server_version=dto.server_version,
            database_schema_version=dto.database_revision,
            desktop_version=desktop_version,
            supported_api_contract_version="v1",
            minimum_api_version=minimum_api_version,
        )

    def test_server_below_minimum_api_version_is_server_update_required(self):
        dto = _dto(server_version="3.0.0")
        self.assertEqual(self._evaluate(dto, "3.2.0", minimum_api_version="3.1.0"), CompatibilityStatus.SERVER_UPDATE_REQUIRED)

    def test_server_at_minimum_api_version_is_not_blocked(self):
        dto = _dto(server_version="3.1.0")
        self.assertEqual(self._evaluate(dto, "3.2.0", minimum_api_version="3.1.0"), CompatibilityStatus.COMPATIBLE)

    def test_server_above_minimum_api_version_is_not_blocked(self):
        dto = _dto(server_version="9.9.9")
        self.assertEqual(self._evaluate(dto, "3.2.0", minimum_api_version="3.1.0"), CompatibilityStatus.COMPATIBLE)

    def test_omitting_minimum_api_version_preserves_previous_behavior(self):
        # Sem minimum_api_version (None), o comportamento e identico ao de
        # antes desta fase -- nenhum chamador existente e afetado.
        dto = _dto(server_version="0.0.1")
        state = evaluate_startup_compatibility(
            maintenance_mode=dto.maintenance_mode,
            api_contract_version=dto.api_contract_version,
            minimum_desktop_version=dto.minimum_desktop_version,
            recommended_desktop_version=dto.recommended_desktop_version,
            server_version=dto.server_version,
            database_schema_version=dto.database_revision,
            desktop_version="3.2.0",
            supported_api_contract_version="v1",
        )
        self.assertEqual(state, CompatibilityStatus.COMPATIBLE)

    def test_minimum_api_version_is_checked_before_server_desktop_state(self):
        # Um servidor antigo demais nao e uma fonte confiavel para decidir
        # se o Desktop pode operar -- SERVER_UPDATE_REQUIRED vence mesmo que
        # o servidor tenha mandado um desktop_state "otimista".
        dto = _dto(server_version="3.0.0", desktop_state="COMPATIBLE")
        self.assertEqual(self._evaluate(dto, "3.2.0", minimum_api_version="3.1.0"), CompatibilityStatus.SERVER_UPDATE_REQUIRED)

    def test_maintenance_still_wins_over_minimum_api_version(self):
        dto = _dto(server_version="3.0.0", maintenance_mode=True)
        self.assertEqual(self._evaluate(dto, "3.2.0", minimum_api_version="3.1.0"), CompatibilityStatus.MAINTENANCE)

    def test_unsupported_contract_still_wins_over_minimum_api_version(self):
        dto = _dto(server_version="3.0.0", api_contract_version="v2")
        self.assertEqual(self._evaluate(dto, "3.2.0", minimum_api_version="3.1.0"), CompatibilityStatus.INCOMPATIBLE)


class ServerDesktopStateOverrideTests(unittest.TestCase):
    """Fase 13: quando o servidor ja manda desktop_state (considerando
    enforcement/grace period), o Desktop usa diretamente -- nunca refaz essa
    conta sozinho (Secao 4: 'a obrigatoriedade pertence ao servidor')."""

    def _evaluate(self, dto: SystemCompatibilityDto, desktop_version: str) -> CompatibilityStatus:
        return evaluate_startup_compatibility(
            maintenance_mode=dto.maintenance_mode,
            api_contract_version=dto.api_contract_version,
            minimum_desktop_version=dto.minimum_desktop_version,
            recommended_desktop_version=dto.recommended_desktop_version,
            server_version=dto.server_version,
            database_schema_version=dto.database_revision,
            desktop_version=desktop_version,
            supported_api_contract_version="v1",
            server_desktop_state=dto.desktop_state,
        )

    def test_server_desktop_state_is_used_directly_when_present(self):
        # local math would say COMPATIBLE (3.2.0 == recommended), mas o servidor
        # mandou UPDATE_RECOMMENDED (enforcement=RECOMMENDED) -- o servidor vence.
        dto = _dto(desktop_state="UPDATE_RECOMMENDED")
        self.assertEqual(self._evaluate(dto, "3.2.0"), CompatibilityStatus.UPDATE_RECOMMENDED)

    def test_absent_server_desktop_state_falls_back_to_local_math(self):
        dto = _dto(desktop_state=None)
        self.assertEqual(self._evaluate(dto, "3.1.5"), CompatibilityStatus.UPDATE_AVAILABLE)

    def test_unrecognized_server_desktop_state_falls_back_to_local_math(self):
        dto = _dto(desktop_state="SOME_FUTURE_STATE_THIS_CLIENT_DOES_NOT_KNOW")
        self.assertEqual(self._evaluate(dto, "3.2.0"), CompatibilityStatus.COMPATIBLE)

    def test_maintenance_mode_still_wins_over_server_desktop_state(self):
        dto = _dto(maintenance_mode=True, desktop_state="COMPATIBLE")
        self.assertEqual(self._evaluate(dto, "3.2.0"), CompatibilityStatus.MAINTENANCE)

    def test_unsupported_contract_still_wins_over_server_desktop_state(self):
        dto = _dto(api_contract_version="v2", desktop_state="COMPATIBLE")
        self.assertEqual(self._evaluate(dto, "3.2.0"), CompatibilityStatus.INCOMPATIBLE)


class FakeSystemApiClient:
    def __init__(self, *, dto: SystemCompatibilityDto | None = None, error: Exception | None = None):
        self._dto = dto
        self._error = error
        self.calls = 0
        self.last_desktop_version: str | None = None
        self.last_installation_id: str | None = None

    def compatibility(
        self,
        *,
        desktop_version: str | None = None,
        installation_id: str | None = None,
        machine_name: str | None = None,
        os_version: str | None = None,
    ) -> SystemCompatibilityDto:
        self.calls += 1
        self.last_desktop_version = desktop_version
        self.last_installation_id = installation_id
        if self._error is not None:
            raise self._error
        return self._dto


class _FakeInstallationIdentity:
    installation_id = "fake-installation-id"
    machine_name = "fake-machine"
    os_version = "fake-os"


def _fake_identity_provider() -> _FakeInstallationIdentity:
    return _FakeInstallationIdentity()


class RunCompatibilityCheckTests(unittest.TestCase):
    """Coordenador (I/O + regra pura), sem Qt e sem rede real. Injeta um
    identity_provider fixo (Fase 15) para nao tocar o config.json real do
    desenvolvedor rodando os testes."""

    def _run(self, client, **kwargs):
        kwargs.setdefault("identity_provider", _fake_identity_provider)
        return run_compatibility_check(client, **kwargs)

    def test_builds_result_from_valid_response(self):
        client = FakeSystemApiClient(dto=_dto())
        result = self._run(client, desktop_version="3.2.0")
        self.assertEqual(result.state, CompatibilityStatus.COMPATIBLE)
        self.assertEqual(result.local_desktop_version, "3.2.0")
        self.assertIsNotNone(result.dto)

    def test_sends_persistent_installation_id(self):
        client = FakeSystemApiClient(dto=_dto())
        self._run(client, desktop_version="3.2.0")
        self.assertEqual(client.last_installation_id, "fake-installation-id")

    def test_uses_central_desktop_version_when_not_provided(self):
        from app.versioning.versions import get_desktop_version

        client = FakeSystemApiClient(dto=_dto())
        result = self._run(client)
        self.assertEqual(result.local_desktop_version, get_desktop_version())

    def test_timeout_becomes_check_failed(self):
        client = FakeSystemApiClient(error=ApiTimeoutError())
        result = self._run(client, desktop_version="3.2.0")
        self.assertEqual(result.state, CompatibilityStatus.CHECK_FAILED)
        self.assertIsNone(result.dto)

    def test_connection_refused_becomes_check_failed(self):
        client = FakeSystemApiClient(error=ApiConnectionError())
        result = self._run(client, desktop_version="3.2.0")
        self.assertEqual(result.state, CompatibilityStatus.CHECK_FAILED)

    def test_5xx_becomes_check_failed(self):
        client = FakeSystemApiClient(error=ApiUnavailableError())
        result = self._run(client, desktop_version="3.2.0")
        self.assertEqual(result.state, CompatibilityStatus.CHECK_FAILED)

    def test_401_and_403_do_not_become_update_required(self):
        for error in (ApiAuthenticationError(), ApiPermissionError()):
            with self.subTest(error=type(error).__name__):
                client = FakeSystemApiClient(error=error)
                result = self._run(client, desktop_version="3.2.0")
                self.assertEqual(result.state, CompatibilityStatus.CHECK_FAILED)
                self.assertNotEqual(result.state, CompatibilityStatus.UPDATE_REQUIRED)

    def test_invalid_policy_from_server_becomes_check_failed(self):
        client = FakeSystemApiClient(dto=_dto(minimum_desktop_version="nao-e-semver"))
        result = self._run(client, desktop_version="3.2.0")
        self.assertEqual(result.state, CompatibilityStatus.CHECK_FAILED)
        self.assertIsNotNone(result.dto)

    def test_maintenance_mode_short_circuits(self):
        client = FakeSystemApiClient(dto=_dto(maintenance_mode=True))
        result = self._run(client, desktop_version="1.0.0")
        self.assertEqual(result.state, CompatibilityStatus.MAINTENANCE)

    def test_result_is_a_plain_dataclass_serializable_for_logging(self):
        client = FakeSystemApiClient(dto=_dto())
        result = self._run(client, desktop_version="3.2.0")
        self.assertIsInstance(result, CompatibilityCheckResult)

    def test_identity_resolution_failure_never_blocks_the_check(self):
        def _failing_provider():
            raise RuntimeError("disco indisponivel")

        client = FakeSystemApiClient(dto=_dto())
        result = run_compatibility_check(client, desktop_version="3.2.0", identity_provider=_failing_provider)
        self.assertEqual(result.state, CompatibilityStatus.COMPATIBLE)
        self.assertIsNone(client.last_installation_id)


if __name__ == "__main__":
    unittest.main()
