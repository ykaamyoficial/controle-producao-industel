from __future__ import annotations

import os


def collect_prefixed_env(prefix: str) -> dict[str, str]:
    """Variaveis a repassar para um container/comando efemero, lidas do
    ambiente do processo com um prefixo explicito (ex.: DEPLOY_CONTAINER_ENV_DATABASE_URL
    -> DATABASE_URL). Nunca hardcoded nos scripts -- evita duplicar o bloco
    'environment:' do docker-compose.prod.yml em Python/YAML."""
    return {key[len(prefix):]: value for key, value in os.environ.items() if key.startswith(prefix)}
