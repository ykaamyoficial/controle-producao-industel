from __future__ import annotations

import shutil
import subprocess

DEV_POSTGRES_CONTAINER = "controle_producao_postgres_dev"


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def dev_postgres_network() -> str | None:
    """Descobre a rede Docker onde o Postgres de desenvolvimento (mesmo usado
    pelas Fases 04-06) esta conectado, para que um container de teste consiga
    resolver o hostname 'postgres'. Retorna None se o container dev nao estiver
    rodando -- os testes que dependem disso devem pular nesse caso."""
    try:
        result = subprocess.run(
            ["docker", "inspect", DEV_POSTGRES_CONTAINER, "--format", "{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    network = result.stdout.strip()
    return network or None
