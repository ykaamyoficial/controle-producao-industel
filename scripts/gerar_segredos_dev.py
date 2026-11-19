"""Gera os segredos do ambiente de dev FORA do repositorio, sem imprimir valores.

Uso: python scripts/gerar_segredos_dev.py [--forcar] [--destino CAMINHO]

Padrao: %USERPROFILE%/.controle-producao-dev/dev.env (o mesmo que
scripts/load_dev_env.bat le). Recusa sobrescrever sem --forcar: trocar SECRET_KEY
derruba as sessoes e trocar NOMUS_ENCRYPTION_KEY deixa ilegiveis as credenciais
Nomus ja cifradas no banco de dev (ver docs/architecture/API_RUNTIME_DEV.md).
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

PADRAO = Path.home() / ".controle-producao-dev" / "dev.env"
# NOMUS_ENCRYPTION_KEY pode ser qualquer texto: a API deriva a chave Fernet por SHA-256.
CHAVES = ("SECRET_KEY", "PROVISIONING_SECRET", "NOMUS_ENCRYPTION_KEY")


def gerar(destino: Path, forcar: bool = False) -> list[str]:
    if destino.exists() and not forcar:
        raise FileExistsError(f"{destino} ja existe; use --forcar para sobrescrever")
    destino.parent.mkdir(parents=True, exist_ok=True)
    linhas = ["# Segredos de dev gerados por scripts/gerar_segredos_dev.py. Nunca versionar."]
    linhas += [f"{chave}={secrets.token_urlsafe(48)}" for chave in CHAVES]
    destino.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    try:
        os.chmod(destino, 0o600)
    except OSError:
        pass
    return list(CHAVES)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--forcar", action="store_true")
    ap.add_argument("--destino", type=Path, default=Path(os.environ.get("CONTROLE_DEV_ENV_FILE") or PADRAO))
    args = ap.parse_args()
    try:
        chaves = gerar(args.destino, args.forcar)
    except FileExistsError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1
    print(f"Gravado {args.destino} com: {', '.join(chaves)} (valores nao exibidos).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
