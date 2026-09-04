from __future__ import annotations

import unittest

from app.integrations.api.config import DesktopApiSettings
from app.integrations.api.models import SystemCompatibilityDto
from app.main import run_startup_compatibility_check
from app.services.compatibility_check import CompatibilityCheckResult
from app.versioning.models import CompatibilityStatus


class FakeConfigStore:
    def __init__(self, *, enabled: bool):
        self._enabled = enabled

    def load_settings(self) -> DesktopApiSettings:
        return DesktopApiSettings(enabled=self._enabled, base_url="http://127.0.0.1:8000", connect_timeout=1, read_timeout=1)


class DummyDialog:
    calls: list = []

    def __init__(self, perform_check, parent=None, *, proceed: bool, check_result: CompatibilityCheckResult | None):
        self.perform_check = perform_check
        self.parent = parent
        self.proceed = proceed
        self.check_result = check_result
        DummyDialog.calls.append(self)

    def exec(self):
        return 0


def _dialog_factory(*, proceed: bool, check_result: CompatibilityCheckResult | None):
    def factory(perform_check, parent=None):
        return DummyDialog(perform_check, parent, proceed=proceed, check_result=check_result)

    return factory


def _maintenance_dialog_factory(*, proceed: bool, check_result: CompatibilityCheckResult | None):
    def factory(perform_check, initial_result, parent=None):
        return DummyDialog(perform_check, parent, proceed=proceed, check_result=check_result)

    return factory


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


class RunStartupCompatibilityCheckTests(unittest.TestCase):
    """Testa app.main.run_startup_compatibility_check via injecao de dependencia,
    sem Qt real e sem rede real (mesmo idioma de tests/test_startup_update_check.py)."""

    def setUp(self):
        DummyDialog.calls.clear()

    def test_skips_check_entirely_when_api_integration_disabled(self):
        proceed, message = run_startup_compatibility_check(
            config_store_factory=lambda: FakeConfigStore(enabled=False),
            dialog_factory=_dialog_factory(proceed=True, check_result=None),
        )
        self.assertTrue(proceed)
        self.assertIsNone(message)
        self.assertEqual(DummyDialog.calls, [])

    def test_proceeds_silently_when_compatible(self):
        result = CompatibilityCheckResult(CompatibilityStatus.COMPATIBLE, "3.2.0", dto=_dto())
        proceed, message = run_startup_compatibility_check(
            config_store_factory=lambda: FakeConfigStore(enabled=True),
            check_runner=lambda _client: result,
            dialog_factory=_dialog_factory(proceed=True, check_result=result),
        )
        self.assertTrue(proceed)
        self.assertIsNone(message)
        # Compativel nao exige nenhuma acao do usuario -- o dialogo nao chega
        # a ser construido, so a checagem silenciosa decide.
        self.assertEqual(len(DummyDialog.calls), 0)

    def test_returns_non_blocking_message_when_update_available(self):
        dto = _dto(recommended_desktop_version="3.5.0")
        result = CompatibilityCheckResult(CompatibilityStatus.UPDATE_AVAILABLE, "3.1.5", dto=dto)
        proceed, message = run_startup_compatibility_check(
            config_store_factory=lambda: FakeConfigStore(enabled=True),
            check_runner=lambda _client: result,
            dialog_factory=_dialog_factory(proceed=True, check_result=result),
        )
        self.assertTrue(proceed)
        self.assertIn("3.5.0", message)
        self.assertEqual(len(DummyDialog.calls), 0)

    def test_blocks_startup_when_dialog_reports_proceed_false(self):
        for state in (
            CompatibilityStatus.UPDATE_REQUIRED,
            CompatibilityStatus.INCOMPATIBLE,
            CompatibilityStatus.CHECK_FAILED,
        ):
            with self.subTest(state=state):
                result = CompatibilityCheckResult(state, "3.0.0")
                proceed, message = run_startup_compatibility_check(
                    config_store_factory=lambda: FakeConfigStore(enabled=True),
                    check_runner=lambda _client, _result=result: _result,
                    dialog_factory=_dialog_factory(proceed=False, check_result=result),
                )
                self.assertFalse(proceed)
                self.assertIsNone(message)

    def test_maintenance_result_delegates_to_maintenance_dialog(self):
        # Fase 14: quando o gate detecta MAINTENANCE, run_startup_compatibility_check
        # delega para um segundo dialogo dedicado (maintenance_dialog_factory) em vez
        # de bloquear direto -- exercitado aqui sem Qt real, via injecao.
        gate_result = CompatibilityCheckResult(CompatibilityStatus.MAINTENANCE, "3.0.0")
        maintenance_result = CompatibilityCheckResult(CompatibilityStatus.COMPATIBLE, "3.0.0", dto=_dto())

        proceed, message = run_startup_compatibility_check(
            config_store_factory=lambda: FakeConfigStore(enabled=True),
            check_runner=lambda _client, _result=gate_result: _result,
            dialog_factory=_dialog_factory(proceed=False, check_result=gate_result),
            maintenance_dialog_factory=_maintenance_dialog_factory(proceed=True, check_result=maintenance_result),
        )

        self.assertTrue(proceed)
        self.assertIsNone(message)

    def test_maintenance_dialog_can_also_block_startup(self):
        gate_result = CompatibilityCheckResult(CompatibilityStatus.MAINTENANCE, "3.0.0")

        proceed, message = run_startup_compatibility_check(
            config_store_factory=lambda: FakeConfigStore(enabled=True),
            check_runner=lambda _client, _result=gate_result: _result,
            dialog_factory=_dialog_factory(proceed=False, check_result=gate_result),
            maintenance_dialog_factory=_maintenance_dialog_factory(proceed=False, check_result=gate_result),
        )

        self.assertFalse(proceed)
        self.assertIsNone(message)

    def test_never_raises_when_dialog_check_result_is_missing(self):
        # dialog_factory devolvendo um objeto sem check_result (ex.: excecao inesperada
        # tratada dentro do dialogo) nao pode derrubar o processo. A checagem silenciosa
        # tambem falha (simulando erro de rede), forcando o caminho do dialogo.
        def raising_check_runner(_client):
            raise RuntimeError("boom")

        proceed, message = run_startup_compatibility_check(
            config_store_factory=lambda: FakeConfigStore(enabled=True),
            check_runner=raising_check_runner,
            dialog_factory=_dialog_factory(proceed=False, check_result=None),
        )
        self.assertFalse(proceed)
        self.assertIsNone(message)


if __name__ == "__main__":
    unittest.main()
