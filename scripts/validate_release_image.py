"""Validacao manual local de uma release (Fase 07, Secao 22): sobe um
container isolado a partir de uma imagem ja construida, aguarda o healthcheck
(Fase 06, embutido na propria imagem) e roda o SmokeTestRunner da Fase 06
contra ele.

Uso:
    python scripts/build_release_image.py --registry ghcr.io/sua-organizacao
    python scripts/validate_release_image.py \
        --image ghcr.io/sua-organizacao/controle-producao-api:0.8.0 \
        --network novapasta_default \
        --database-url "postgresql+asyncpg://usuario:senha@postgres:5432/algum_banco_de_teste" \
        --expected-server-version 0.8.0

Nao exige acesso ao servidor de producao: roda contra qualquer PostgreSQL
descartavel acessivel pela rede Docker informada (mesmo padrao dos testes de
integracao das Fases 04-06). O container e sempre removido ao final, mesmo em
caso de falha.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.app.health.smoke import SmokeTestRunner  # noqa: E402


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def start_container(*, image: str, network: str, database_url: str, secret_key: str, port: int) -> str:
    name = f"release-validate-{uuid.uuid4().hex[:8]}"
    args = [
        "docker", "run", "-d", "--name", name,
        "--network", network,
        "-e", f"DATABASE_URL={database_url}",
        "-e", f"SECRET_KEY={secret_key}",
        "-e", "APP_ENV=test",
        "-e", "OPERATIONAL_COMPANY_CODE=release-validation",
        "-e", "OPERATIONAL_COMPANY_NAME=Release Validation",
        "-e", "OPERATIONAL_ENVIRONMENT_TYPE=production",
        "-p", f"{port}:8000",
        image,
    ]
    result = _run(args)
    if result.returncode != 0:
        raise RuntimeError(f"Falha ao iniciar container: {result.stderr.strip()}")
    return name


def wait_healthy(container_name: str, *, timeout_seconds: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = _run(["docker", "inspect", "--format", "{{.State.Health.Status}}", container_name])
        status = result.stdout.strip()
        if status == "healthy":
            return True
        if status == "unhealthy":
            return False
        time.sleep(2)
    return False


def stop_container(container_name: str) -> None:
    _run(["docker", "rm", "-f", container_name])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sobe um container isolado da imagem de release e roda health/smoke tests da Fase 06.")
    parser.add_argument("--image", required=True, help="Ex.: ghcr.io/sua-organizacao/controle-producao-api:0.8.0")
    parser.add_argument("--network", required=True, help="Rede Docker onde 'postgres' (ou host equivalente) e alcancavel.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--secret-key", default="release-validation-secret-key-32-chars-min")
    parser.add_argument("--port", type=int, default=18000)
    parser.add_argument("--expected-server-version", default=None)
    args = parser.parse_args(argv)

    print(f"Iniciando container isolado a partir de {args.image}...")
    container_name = start_container(
        image=args.image, network=args.network, database_url=args.database_url,
        secret_key=args.secret_key, port=args.port,
    )
    try:
        print(f"Container {container_name} iniciado. Aguardando healthcheck...")
        if not wait_healthy(container_name):
            print("FALHA: container nao ficou 'healthy' dentro do timeout.")
            print(_run(["docker", "logs", container_name]).stdout[-2000:])
            return 1

        print("Healthcheck OK. Rodando smoke tests...")
        runner = SmokeTestRunner(base_url=f"http://127.0.0.1:{args.port}", expected_server_version=args.expected_server_version)
        report = runner.run()
        print(f"Smoke test: {report.status.value} (server_version={report.actual_server_version})")
        for step in report.steps:
            print(f"  - {step.name}: {step.status.value} ({step.duration_ms}ms) http={step.http_status} {step.message}")
        return report.exit_code
    finally:
        print(f"Removendo container {container_name}...")
        stop_container(container_name)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
