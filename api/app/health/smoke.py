from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from api.app.health.models import SmokeStatus, SmokeStepResult, SmokeTestReport


@dataclass(frozen=True)
class SmokeHttpResponse:
    status_code: int
    json_body: Any | None
    text: str


class SmokeHttpClient(Protocol):
    def get(self, path: str, *, timeout: float) -> SmokeHttpResponse: ...


class HttpxSmokeClient:
    """Cliente HTTP real usado pelo CLI/pipeline (Secao 22). httpx ja e dependencia
    da imagem da API (api/requirements-dev.txt, instalada no container -- ver
    api/Dockerfile); nenhuma dependencia nova foi adicionada."""

    def __init__(self, base_url: str):
        self._base_url = base_url.rstrip("/")

    def get(self, path: str, *, timeout: float) -> SmokeHttpResponse:
        import httpx

        url = f"{self._base_url}{path}"
        response = httpx.get(url, timeout=timeout)
        try:
            body = response.json()
        except ValueError:
            body = None
        return SmokeHttpResponse(status_code=response.status_code, json_body=body, text=response.text)


class SmokeTestRunner:
    """Bateria curta de verificacoes somente leitura contra uma instancia ja
    iniciada (Secao 18). Nunca escreve dados operacionais (Secao 20) -- todos os
    passos sao GET em endpoints publicos e idempotentes.

    Passo 4 do prompt (autenticacao tecnica controlada) foi omitido deliberadamente:
    nao existe nenhuma credencial tecnica segura/dedicada para smoke test neste
    projeto (login exige usuario real), e o prompt torna esse passo condicional
    ("se existir fixture segura") -- ver docs/architecture/HEALTH_CHECKS_AND_SMOKE_TESTS.md.
    """

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 10.0,
        expected_server_version: str | None = None,
        http_client: SmokeHttpClient | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._expected_server_version = expected_server_version
        self._client = http_client or HttpxSmokeClient(self._base_url)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def run(self) -> SmokeTestReport:
        started = self._clock()
        steps: list[SmokeStepResult] = []
        actual_server_version: str | None = None

        live_step, live_body = self._step("health_live", "/api/v1/health/live", expect_status={200})
        steps.append(live_step)
        if live_body is not None:
            actual_server_version = live_body.get("server_version")

        if live_step.status == SmokeStatus.PASS and self._expected_server_version and actual_server_version != self._expected_server_version:
            steps[-1] = SmokeStepResult(
                name=live_step.name, status=SmokeStatus.FAIL, duration_ms=live_step.duration_ms,
                http_status=live_step.http_status, error_code="VERSION_MISMATCH",
                message=f"server_version inesperado: esperado={self._expected_server_version} atual={actual_server_version}",
            )

        if steps[-1].status == SmokeStatus.FAIL:
            return self._finish(started, steps, actual_server_version)

        ready_step, _ = self._step("health_ready", "/api/v1/health/ready", expect_status={200})
        steps.append(ready_step)
        if ready_step.status == SmokeStatus.FAIL:
            return self._finish(started, steps, actual_server_version)

        compat_step, compat_body = self._step(
            "system_compatibility", "/api/v1/system/compatibility", expect_status={200},
            required_fields=("server_version", "api_contract_version", "database_revision"),
        )
        steps.append(compat_step)
        if actual_server_version is None and compat_body is not None:
            actual_server_version = compat_body.get("server_version")

        version_step, _ = self._step(
            "system_version_read_only_query", "/api/v1/system/version", expect_status={200},
            required_fields=("api_version", "database_revision", "database_status"),
        )
        steps.append(version_step)

        return self._finish(started, steps, actual_server_version)

    def _step(
        self,
        name: str,
        path: str,
        *,
        expect_status: set[int],
        required_fields: tuple[str, ...] = (),
    ) -> tuple[SmokeStepResult, dict[str, Any] | None]:
        started = time.monotonic()
        try:
            response = self._client.get(path, timeout=self._timeout)
        except Exception as exc:  # falha de rede/timeout do cliente HTTP
            duration_ms = int((time.monotonic() - started) * 1000)
            return SmokeStepResult(
                name=name, status=SmokeStatus.FAIL, duration_ms=duration_ms,
                http_status=None, error_code="REQUEST_FAILED", message=_sanitize(str(exc)),
            ), None

        duration_ms = int((time.monotonic() - started) * 1000)
        if response.status_code not in expect_status:
            return SmokeStepResult(
                name=name, status=SmokeStatus.FAIL, duration_ms=duration_ms,
                http_status=response.status_code, error_code="UNEXPECTED_HTTP_STATUS",
                message=f"esperado {sorted(expect_status)}, recebido {response.status_code}",
            ), response.json_body if isinstance(response.json_body, dict) else None

        body = response.json_body
        if not isinstance(body, dict):
            return SmokeStepResult(
                name=name, status=SmokeStatus.FAIL, duration_ms=duration_ms,
                http_status=response.status_code, error_code="INVALID_RESPONSE_FORMAT",
                message="resposta nao e um objeto JSON valido",
            ), None

        missing = [field for field in required_fields if field not in body]
        if missing:
            return SmokeStepResult(
                name=name, status=SmokeStatus.FAIL, duration_ms=duration_ms,
                http_status=response.status_code, error_code="INVALID_RESPONSE_FORMAT",
                message=f"campos ausentes na resposta: {', '.join(missing)}",
            ), body

        return SmokeStepResult(
            name=name, status=SmokeStatus.PASS, duration_ms=duration_ms,
            http_status=response.status_code, message="OK",
        ), body

    def _finish(self, started: datetime, steps: list[SmokeStepResult], actual_server_version: str | None) -> SmokeTestReport:
        overall = SmokeStatus.PASS if all(step.status == SmokeStatus.PASS for step in steps) else SmokeStatus.FAIL
        return SmokeTestReport(
            status=overall,
            started_at_utc=started,
            completed_at_utc=self._clock(),
            target_base_url=self._base_url,
            actual_server_version=actual_server_version,
            expected_server_version=self._expected_server_version,
            steps=steps,
        )


def _sanitize(message: str) -> str:
    # httpx ja nao inclui credenciais em mensagens de erro de rede padrao, mas
    # removemos qualquer query string por seguranca (poderia conter token futuro).
    return message.split("?", 1)[0][:400]


def _format_human(report: SmokeTestReport) -> str:
    lines = [
        f"target={report.target_base_url}",
        f"status={report.status.value}",
        f"actual_server_version={report.actual_server_version}",
    ]
    if report.expected_server_version:
        lines.append(f"expected_server_version={report.expected_server_version}")
    for step in report.steps:
        lines.append(f"  - {step.name}: {step.status.value} ({step.duration_ms}ms) http={step.http_status} {step.message}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke test pos-deployment (somente leitura).")
    parser.add_argument("--base-url", required=True, help="Ex.: http://servidor:8000")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--expected-server-version", default=None)
    parser.add_argument("--json", action="store_true", help="Saida em JSON em vez de texto legivel.")
    args = parser.parse_args(argv)

    runner = SmokeTestRunner(
        base_url=args.base_url,
        timeout_seconds=args.timeout,
        expected_server_version=args.expected_server_version,
    )
    report = runner.run()

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(_format_human(report))

    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
