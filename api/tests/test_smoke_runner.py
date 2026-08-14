from __future__ import annotations

import unittest
from datetime import datetime, timezone

from api.app.health.models import SmokeStatus
from api.app.health.smoke import SmokeHttpResponse, SmokeTestRunner


class FakeHttpClient:
    """Cliente falso e totalmente somente-leitura: so implementa .get(), nunca
    escreve nada em lugar nenhum -- reforca estruturalmente o requisito de
    'nenhum smoke test escreve no banco' (nao ha metodo de escrita para chamar)."""

    def __init__(self, responses: dict[str, SmokeHttpResponse]):
        self._responses = responses
        self.calls: list[str] = []

    def get(self, path: str, *, timeout: float) -> SmokeHttpResponse:
        self.calls.append(path)
        if path not in self._responses:
            raise AssertionError(f"chamada inesperada em teste: {path}")
        return self._responses[path]


def _ok_responses(server_version: str = "0.8.0") -> dict[str, SmokeHttpResponse]:
    return {
        "/api/v1/health/live": SmokeHttpResponse(200, {"status": "alive", "server_version": server_version}, ""),
        "/api/v1/health/ready": SmokeHttpResponse(200, {"overall_status": "HEALTHY", "checks": []}, ""),
        "/api/v1/system/compatibility": SmokeHttpResponse(200, {"server_version": server_version, "api_contract_version": "v1", "database_revision": "20260810_0015"}, ""),
        "/api/v1/system/version": SmokeHttpResponse(200, {"api_version": server_version, "database_revision": "20260810_0015", "database_status": "compatible"}, ""),
    }


class SmokeTestRunnerTests(unittest.TestCase):
    def _runner(self, responses, **kwargs) -> SmokeTestRunner:
        return SmokeTestRunner(base_url="http://servidor:8000", http_client=FakeHttpClient(responses), **kwargs)

    def test_full_pass_when_all_endpoints_healthy(self):
        runner = self._runner(_ok_responses())
        report = runner.run()
        self.assertEqual(report.status, SmokeStatus.PASS)
        self.assertEqual(report.exit_code, 0)
        self.assertEqual(report.actual_server_version, "0.8.0")
        self.assertEqual([s.name for s in report.steps], ["health_live", "health_ready", "system_compatibility", "system_version_read_only_query"])

    def test_fails_and_stops_early_when_health_ready_fails(self):
        responses = _ok_responses()
        responses["/api/v1/health/ready"] = SmokeHttpResponse(503, {"overall_status": "UNHEALTHY", "checks": []}, "")
        runner = self._runner(responses)
        client = runner._client  # type: ignore[attr-defined]
        report = runner.run()
        self.assertEqual(report.status, SmokeStatus.FAIL)
        self.assertEqual(report.exit_code, 1)
        # nao continua chamando os passos seguintes depois de ready falhar
        self.assertNotIn("/api/v1/system/compatibility", client.calls)

    def test_fails_when_health_live_is_unreachable(self):
        runner = self._runner({})  # nenhuma resposta configurada -> AssertionError vira FAIL
        report = runner.run()
        self.assertEqual(report.status, SmokeStatus.FAIL)
        self.assertEqual(report.steps[0].error_code, "REQUEST_FAILED")

    def test_detects_unexpected_server_version(self):
        runner = self._runner(_ok_responses(server_version="0.8.0"), expected_server_version="0.9.0")
        report = runner.run()
        self.assertEqual(report.status, SmokeStatus.FAIL)
        self.assertEqual(report.steps[0].error_code, "VERSION_MISMATCH")

    def test_passes_when_expected_version_matches(self):
        runner = self._runner(_ok_responses(server_version="0.8.0"), expected_server_version="0.8.0")
        report = runner.run()
        self.assertEqual(report.status, SmokeStatus.PASS)

    def test_missing_required_field_is_a_format_failure(self):
        responses = _ok_responses()
        responses["/api/v1/system/compatibility"] = SmokeHttpResponse(200, {"server_version": "0.8.0"}, "")
        runner = self._runner(responses)
        report = runner.run()
        self.assertEqual(report.status, SmokeStatus.FAIL)
        compat_step = next(s for s in report.steps if s.name == "system_compatibility")
        self.assertEqual(compat_step.error_code, "INVALID_RESPONSE_FORMAT")

    def test_never_calls_anything_but_get(self):
        # FakeHttpClient so tem .get(); confirmar que nao ha nenhum outro metodo
        # de escrita sendo chamado e uma garantia estrutural, nao apenas comportamental.
        client = FakeHttpClient(_ok_responses())
        self.assertFalse(hasattr(client, "post"))
        self.assertFalse(hasattr(client, "put"))
        self.assertFalse(hasattr(client, "delete"))

    def test_clock_is_used_for_started_and_completed_timestamps(self):
        fixed = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
        runner = self._runner(_ok_responses(), clock=lambda: fixed)
        report = runner.run()
        self.assertEqual(report.started_at_utc, fixed)
        self.assertEqual(report.completed_at_utc, fixed)


if __name__ == "__main__":
    unittest.main()
