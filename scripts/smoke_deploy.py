"""Smoke test de deploy da API (somente leitura, exceto o login).

Reaproveita `api.app.health.smoke.SmokeTestRunner`. Etapas publicas (live, ready,
compatibility, version, descoberta de update, e /docs + /openapi.json fechados com
--expect-production-hardening) e, sem --skip-auth, login + leituras que o Desktop usa.

Credenciais: variaveis SMOKE_USERNAME / SMOKE_PASSWORD, ou prompt (senha sem eco).
Nada de credencial em arquivo ou argumento de linha de comando. O token fica so em memoria.
Verificacao TLS sempre ligada. Exit code 0 so se todas as etapas passarem; 2 = uso/credencial ausente.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.app.core.config import MINIMUM_DESKTOP_VERSION  # noqa: E402
from api.app.health.models import SmokeStatus, SmokeTestReport  # noqa: E402
from api.app.health.smoke import HttpxSmokeClient, SmokeHttpClient, SmokeTestRunner  # noqa: E402

_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def _format_report(report: SmokeTestReport) -> str:
    lines = [f"Smoke de deploy em {report.target_base_url}"]
    for step in report.steps:
        ok = step.status == SmokeStatus.PASS
        http = f"HTTP {step.http_status}" if step.http_status is not None else "sem resposta"
        detail = "" if ok else f"  {step.message}"
        lines.append(f"[{'OK' if ok else 'FALHA':<5}] {step.name:<36} {http} ({step.duration_ms} ms){detail}")
    failed = sum(1 for step in report.steps if step.status != SmokeStatus.PASS)
    lines.append("RESULTADO: OK" if report.exit_code == 0 else f"RESULTADO: FALHA ({failed} de {len(report.steps)} etapas)")
    return "\n".join(lines)


def _credentials(env: Mapping[str, str], prompt_user: Callable[[], str], prompt_password: Callable[[], str]) -> tuple[str, str] | None:
    username, password = env.get("SMOKE_USERNAME", ""), env.get("SMOKE_PASSWORD", "")
    if not (username and password):
        if not sys.stdin.isatty():
            return None
        username = username or prompt_user().strip()
        password = password or prompt_password()
    return (username, password) if username and password else None


def main(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    http_client: SmokeHttpClient | None = None,
    prompt_user: Callable[[], str] = lambda: input("Usuario do smoke: "),
    prompt_password: Callable[[], str] = lambda: getpass.getpass("Senha do smoke (sem eco): "),
) -> int:
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(description="Smoke test de deploy da API (somente leitura, exceto o login).")
    parser.add_argument("--base-url", default=env.get("SMOKE_BASE_URL"), help="Ex.: https://api.exemplo.com.br ou http://127.0.0.1:8001 (ou SMOKE_BASE_URL)")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--expected-server-version", default=None)
    parser.add_argument("--client-version", default=MINIMUM_DESKTOP_VERSION, help="Enviada em X-Client-Version (a API pode recusar versao antiga).")
    parser.add_argument("--skip-auth", action="store_true", help="So etapas publicas, sem login.")
    parser.add_argument("--expect-production-hardening", action="store_true", help="Exige 404 em /docs, /redoc e /openapi.json.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not args.base_url:
        parser.error("informe --base-url ou SMOKE_BASE_URL")
    parsed = urlparse(args.base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query:
        parser.error("--base-url deve ser http(s)://host[:porta][/caminho], sem usuario, senha ou query")

    credentials = None
    if not args.skip_auth:
        credentials = _credentials(env, prompt_user, prompt_password)
        if credentials is None:
            print("Credenciais ausentes: defina SMOKE_USERNAME e SMOKE_PASSWORD, rode num terminal interativo, ou use --skip-auth.", file=sys.stderr)
            return 2
        if parsed.scheme == "http" and parsed.hostname not in _LOOPBACK:
            print("AVISO: login por http (sem TLS) fora do localhost; a senha trafega em texto puro nessa rede.", file=sys.stderr)

    report = SmokeTestRunner(
        base_url=args.base_url,
        timeout_seconds=args.timeout,
        expected_server_version=args.expected_server_version,
        http_client=http_client or HttpxSmokeClient(args.base_url, client_version=args.client_version),
        extended=True,
        credentials=credentials,
        expect_production_hardening=args.expect_production_hardening,
    ).run()
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) if args.json else _format_report(report))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
