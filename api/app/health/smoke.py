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

    def __init__(self, base_url: str, *, client_version: str | None = None):
        self._base_url = base_url.rstrip("/")
        self._client_version = client_version
        self._bearer: str | None = None  # so em memoria; nunca impresso nem gravado

    def set_bearer(self, token: str | None) -> None:
        self._bearer = token

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self._client_version:
            headers["X-Client-Version"] = self._client_version
        if self._bearer:
            headers["Authorization"] = f"Bearer {self._bearer}"
        return headers

    def _request(self, method: str, path: str, *, timeout: float, json_payload: Any = None) -> SmokeHttpResponse:
        import httpx

        # A verificacao TLS do httpx fica no padrao (ligada); sem redirects.
        response = httpx.request(method, f"{self._base_url}{path}", headers=self._headers(), json=json_payload, timeout=timeout)
        try:
            body = response.json()
        except ValueError:
            body = None
        return SmokeHttpResponse(status_code=response.status_code, json_body=body, text=response.text)

    def get(self, path: str, *, timeout: float) -> SmokeHttpResponse:
        return self._request("GET", path, timeout=timeout)

    def post_json(self, path: str, payload: Any, *, timeout: float) -> SmokeHttpResponse:
        # Usado apenas pelo login; as demais etapas continuam somente GET.
        return self._request("POST", path, timeout=timeout, json_payload=payload)


class SmokeTestRunner:
    """Bateria curta de verificacoes somente leitura contra uma instancia ja
    iniciada (Secao 18). Nunca escreve dados operacionais (Secao 20) -- todos os
    passos sao GET em endpoints publicos e idempotentes.

    Modo padrao: so os 4 passos publicos. Modo estendido (`extended`,
    `credentials`, `expect_production_hardening`): ver `scripts/smoke_deploy.py`.
    O unico POST e o login (cria uma sessao); todo o resto e GET.
    """

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 10.0,
        expected_server_version: str | None = None,
        http_client: SmokeHttpClient | None = None,
        clock: Callable[[], datetime] | None = None,
        extended: bool = False,
        credentials: tuple[str, str] | None = None,
        expect_production_hardening: bool = False,
    ):
        self._extended = extended
        self._credentials = credentials
        self._expect_hardening = expect_production_hardening
        # Valores que nunca podem aparecer em mensagens/saida (senha e token).
        self._secrets: list[str] = [credentials[1]] if credentials else []
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

        if self._extended:
            updates_step, _ = self._step("updates_discovery", "/api/v1/updates/desktop", expect_status={200}, required_fields=("available",))
            steps.append(updates_step)
        if self._expect_hardening:
            for path in ("/docs", "/redoc", "/openapi.json"):
                hardening_step, _ = self._step(f"hardening_closed{path}", path, expect_status={404}, require_json=False)
                steps.append(hardening_step)
        if self._credentials:
            self._authenticated_steps(steps)

        return self._finish(started, steps, actual_server_version)

    def _authenticated_steps(self, steps: list[SmokeStepResult]) -> None:
        login_step = self._login()
        steps.append(login_step)
        if login_step.status == SmokeStatus.FAIL:
            return
        try:
            steps.append(self._step("auth_me", "/api/v1/auth/me", expect_status={200}, required_fields=("id", "username", "permissions"))[0])
            steps.append(self._step("system_compatibility_autenticado", "/api/v1/system/compatibility", expect_status={200}, required_fields=("server_version",))[0])
            # Mesmas listagens que o Desktop usa em Propostas, Almoxarifado, Inspecao e Logistica; limit=1 e so GET.
            for name, path in (
                ("proposals_list", "/api/v1/proposals?limit=1"),
                ("warehouse_proposals_list", "/api/v1/warehouse/proposals?limit=1"),
                ("warehouse_items_list", "/api/v1/warehouse/items?limit=1"),
                ("inspections_list", "/api/v1/inspections?limit=1"),
                ("logistics_logs_list", "/api/v1/logistics/logs?limit=1"),
                ("logistics_loads_list", "/api/v1/logistics/loads?limit=1"),
            ):
                steps.append(self._step(name, path, expect_status={200}, required_fields=("items", "total"))[0])
        finally:
            self._client.set_bearer(None)  # type: ignore[attr-defined]

    def _login(self) -> SmokeStepResult:
        username, password = self._credentials  # type: ignore[misc]
        started = time.monotonic()
        try:
            response = self._client.post_json(  # type: ignore[attr-defined]
                "/api/v1/auth/login", {"username": username, "password": password}, timeout=self._timeout,
            )
        except Exception as exc:
            return SmokeStepResult(
                name="auth_login", status=SmokeStatus.FAIL, duration_ms=int((time.monotonic() - started) * 1000),
                http_status=None, error_code="REQUEST_FAILED", message=_sanitize(str(exc), self._secrets),
            )
        duration_ms = int((time.monotonic() - started) * 1000)
        body = response.json_body if isinstance(response.json_body, dict) else {}
        token = body.get("access_token")
        if response.status_code != 200 or not isinstance(token, str) or not token:
            bad_status = response.status_code != 200
            return SmokeStepResult(
                name="auth_login", status=SmokeStatus.FAIL, duration_ms=duration_ms, http_status=response.status_code,
                error_code="UNEXPECTED_HTTP_STATUS" if bad_status else "INVALID_RESPONSE_FORMAT",
                message=f"esperado [200], recebido {response.status_code}" if bad_status else "login sem access_token",
            )
        self._secrets.append(token)
        self._client.set_bearer(token)  # type: ignore[attr-defined]
        return SmokeStepResult(name="auth_login", status=SmokeStatus.PASS, duration_ms=duration_ms, http_status=200, message="OK")

    def _step(
        self,
        name: str,
        path: str,
        *,
        expect_status: set[int],
        required_fields: tuple[str, ...] = (),
        require_json: bool = True,
    ) -> tuple[SmokeStepResult, dict[str, Any] | None]:
        started = time.monotonic()
        try:
            response = self._client.get(path, timeout=self._timeout)
        except Exception as exc:  # falha de rede/timeout do cliente HTTP
            duration_ms = int((time.monotonic() - started) * 1000)
            return SmokeStepResult(
                name=name, status=SmokeStatus.FAIL, duration_ms=duration_ms,
                http_status=None, error_code="REQUEST_FAILED", message=_sanitize(str(exc), self._secrets),
            ), None

        duration_ms = int((time.monotonic() - started) * 1000)
        if response.status_code not in expect_status:
            return SmokeStepResult(
                name=name, status=SmokeStatus.FAIL, duration_ms=duration_ms,
                http_status=response.status_code, error_code="UNEXPECTED_HTTP_STATUS",
                message=f"esperado {sorted(expect_status)}, recebido {response.status_code}",
            ), response.json_body if isinstance(response.json_body, dict) else None

        if not require_json:
            return SmokeStepResult(
                name=name, status=SmokeStatus.PASS, duration_ms=duration_ms,
                http_status=response.status_code, message="OK",
            ), None

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


def _sanitize(message: str, secrets: list[str] | tuple[str, ...] = ()) -> str:
    # httpx ja nao inclui credenciais em mensagens de erro de rede padrao, mas
    # removemos qualquer query string e qualquer segredo conhecido (senha/token).
    # Mascara antes de cortar: o corte no meio de um segredo deixaria o prefixo dele visivel.
    for secret in secrets:
        if secret:
            message = message.replace(secret, "***")
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
