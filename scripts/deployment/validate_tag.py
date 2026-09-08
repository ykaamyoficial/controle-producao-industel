"""Valida o gatilho de release do servidor contra a versao central (Fase 09,
Secao 7). Convencao de tag EXCLUSIVA do backend: 'api-vX.Y.Z' -- deliberadamente
distinta das tags historicas do repositorio (ex.: v2.3.0-relatorios-operacionais,
que marcam entregas de produto/Desktop, nao releases do servidor), para o
pipeline de producao nunca disparar por engano a partir de uma tag com outro
proposito. Aceita tambem uma versao explicita (workflow_dispatch), sem exigir
uma tag Git correspondente.

Reaproveita scripts/build_release_image.resolve_release_tag (Fase 07) para a
comparacao contra API_VERSION -- nao duplica a logica de divergencia de versao.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_release_image import ReleaseVersionMismatchError, resolve_release_tag  # noqa: E402

TAG_PATTERN = re.compile(r"^api-v(\d+\.\d+\.\d+)$")


class InvalidReleaseTagError(ValueError):
    """Tag nao segue a convencao 'api-vX.Y.Z' (Secao 7)."""


def version_from_tag(tag: str) -> str:
    match = TAG_PATTERN.match(tag)
    if not match:
        raise InvalidReleaseTagError(
            f"Tag '{tag}' nao segue a convencao obrigatoria 'api-vX.Y.Z' (SemVer) para releases do servidor."
        )
    return match.group(1)


def validate_release_trigger(*, tag: str | None, version: str | None) -> str:
    """Retorna a versao validada (== API_VERSION) ou levanta
    InvalidReleaseTagError/ReleaseVersionMismatchError. Exatamente um de
    `tag`/`version` deve ser informado (tag = push de tag; version =
    workflow_dispatch manual)."""
    if (tag is None) == (version is None):
        raise ValueError("Informe exatamente um entre tag e version.")
    requested = version_from_tag(tag) if tag is not None else version
    return resolve_release_tag(requested)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Valida o gatilho de release do servidor contra API_VERSION.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tag", default=None, help="Tag do Git no formato api-vX.Y.Z (gatilho por push de tag).")
    group.add_argument("--version", default=None, help="Versao SemVer explicita (gatilho por workflow_dispatch).")
    args = parser.parse_args(argv)

    try:
        resolved = validate_release_trigger(tag=args.tag, version=args.version)
    except (InvalidReleaseTagError, ReleaseVersionMismatchError) as exc:
        print(f"ERRO: {exc}")
        return 1

    print(f"version={resolved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
