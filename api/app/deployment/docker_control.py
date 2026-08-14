"""Primitivas de baixo nivel para reativar um container Docker por
imagem/tag/digest, sem depender de rebuild (Fase 08, Secao 4/10).

Mesmo estilo de subprocess.run com lista de argumentos (nunca shell=True) ja
usado em scripts/validate_release_image.py e scripts/build_release_image.py
(Fase 07) -- reaproveitado aqui em vez de duplicado como uma classe nova,
apenas generalizado para operar sobre um nome de container arbitrario em vez
do container efemero de validacao.
"""

from __future__ import annotations

import shutil
import subprocess
import time


def _run(cmd: list[str], *, timeout: float = 30.0) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def docker_available() -> bool:
    """Mesmo guard usado pelos testes de integracao (Fases 07/08), promovido a
    modulo de producao: a Fase 09 precisa desta checagem no PRECHECK real do
    pipeline (Secao 15), nao so em testes."""
    if shutil.which("docker") is None:
        return False
    try:
        result = _run(["docker", "info"], timeout=10.0)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def pull_image(image_ref: str) -> None:
    result = _run(["docker", "pull", image_ref], timeout=300.0)
    if result.returncode != 0:
        raise RuntimeError(f"Falha ao baixar a imagem '{image_ref}': {result.stderr.strip()}")


def container_exists(name: str) -> bool:
    result = _run(["docker", "inspect", name])
    return result.returncode == 0


def current_image_ref(container_name: str) -> str | None:
    """A referencia de imagem (tag ou digest) com que o container ATUALMENTE em
    execucao foi criado -- usada para checar idempotencia (Secao 20: um
    rollback repetido nao deve refazer trabalho se a imagem alvo ja esta ativa)."""
    result = _run(["docker", "inspect", container_name, "--format", "{{.Config.Image}}"])
    if result.returncode != 0:
        return None
    ref = result.stdout.strip()
    return ref or None


def image_digest(image_ref: str) -> str | None:
    """Digest imutavel da imagem localmente disponivel, se houver (imagens
    apenas construidas localmente sem push podem nao ter RepoDigests --
    retorna None nesse caso, nunca inventa um valor)."""
    result = _run(["docker", "image", "inspect", image_ref, "--format", "{{index .RepoDigests 0}}"])
    if result.returncode != 0:
        return None
    digest = result.stdout.strip()
    return digest or None


def stop_and_remove_container(name: str) -> None:
    """Idempotente: nao falha se o container ja nao existir (Secao 20)."""
    _run(["docker", "rm", "-f", name], timeout=60.0)


def run_container(
    *,
    name: str,
    image_ref: str,
    network: str,
    env: dict[str, str],
    port: int,
    container_port: int = 8000,
) -> None:
    args = ["docker", "run", "-d", "--name", name, "--network", network]
    for key, value in env.items():
        args.extend(["-e", f"{key}={value}"])
    args.extend(["-p", f"{port}:{container_port}", image_ref])
    result = _run(args, timeout=60.0)
    if result.returncode != 0:
        raise RuntimeError(f"Falha ao iniciar container '{name}' a partir de '{image_ref}': {result.stderr.strip()}")


def run_ephemeral(
    *,
    image_ref: str,
    command: list[str],
    network: str,
    env: dict[str, str],
    timeout: float = 300.0,
) -> subprocess.CompletedProcess:
    """Executa um comando efemero (--rm) na imagem informada, para tarefas
    pontuais como migrations (Fase 09, Secao 18): roda o codigo EXATO da
    imagem ja aprovada/pulled, nunca o checkout do runner do pipeline."""
    args = ["docker", "run", "--rm", "--network", network]
    for key, value in env.items():
        args.extend(["-e", f"{key}={value}"])
    args.append(image_ref)
    args.extend(command)
    return _run(args, timeout=timeout)


def container_health_status(name: str) -> str | None:
    """'healthy' | 'unhealthy' | 'starting' | None (sem HEALTHCHECK ou container ausente)."""
    result = _run(["docker", "inspect", "--format", "{{.State.Health.Status}}", name])
    if result.returncode != 0:
        return None
    status = result.stdout.strip()
    return status or None


def wait_for_healthy(name: str, *, timeout_seconds: float = 60.0, poll_interval_seconds: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = container_health_status(name)
        if status == "healthy":
            return True
        if status == "unhealthy":
            return False
        time.sleep(poll_interval_seconds)
    return False


def recent_logs(name: str, *, tail: int = 200) -> str:
    result = _run(["docker", "logs", "--tail", str(tail), name], timeout=15.0)
    return (result.stdout or "") + (result.stderr or "")
