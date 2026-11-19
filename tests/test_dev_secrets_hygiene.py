"""Garante que os arquivos de dev versionados nao carregam segredo real."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
# NOME(SECRET|KEY|PASSWORD|TOKEN) seguido de = / : / :- e um valor literal longo.
PADRAO = re.compile(
    r"(?i)[A-Z0-9_]*(?:SECRET|KEY|PASSWORD|TOKEN)[A-Z0-9_]*[\"']?\s*(?:=|:-|:)\s*[\"']?([A-Za-z0-9_+/=-]{32,})"
)
ARQUIVOS = [
    "api/.env.example",
    "web/.env.example",
    "docker-compose.dev.yml",
    "scripts/load_dev_env.bat",
    "scripts/start_cloudflare_tunnel.bat",
    "scripts/start_cloudflare_named_tunnel.bat",
]


def _achados(texto: str) -> list[str]:
    return [m.group(0).split("=")[0][:40] for m in PADRAO.finditer(texto)]


def test_detector_pega_segredo_literal():
    assert _achados("SECRET_KEY=" + "a1B2" * 12)
    assert _achados('set "PROVISIONING_SECRET=' + "x" * 40 + '"')
    assert _achados("      NOMUS_ENCRYPTION_KEY: ${NOMUS_ENCRYPTION_KEY:-" + "k" * 34 + "}")
    assert not _achados("SECRET_KEY=troque-por-valor-gerado")
    assert not _achados("SECRET_KEY: ${SECRET_KEY:?defina SECRET_KEY em dev.env}")


def test_arquivos_de_dev_sem_segredo_literal():
    for rel in ARQUIVOS:
        caminho = RAIZ / rel
        if caminho.exists():
            assert not _achados(caminho.read_text(encoding="utf-8")), f"segredo literal em {rel}"


def test_gerador_grava_fora_do_repo_sem_imprimir(tmp_path):
    destino = tmp_path / "dev.env"
    cmd = [sys.executable, str(RAIZ / "scripts" / "gerar_segredos_dev.py"), "--destino", str(destino)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0
    valores = dict(l.split("=", 1) for l in destino.read_text().splitlines() if "=" in l and not l.startswith("#"))
    assert set(valores) == {"SECRET_KEY", "PROVISIONING_SECRET", "NOMUS_ENCRYPTION_KEY"}
    assert all(len(v) >= 32 for v in valores.values())
    assert not any(v in r.stdout + r.stderr for v in valores.values())
    assert subprocess.run(cmd, capture_output=True, text=True, timeout=30).returncode == 1  # nao sobrescreve
