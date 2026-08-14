"""Constroi e identifica uma imagem Docker versionada e imutavel do backend
(Fase 07).

Uso:
    python scripts/build_release_image.py --registry ghcr.io/sua-organizacao
    python scripts/build_release_image.py --registry ghcr.io/sua-organizacao --tag 0.8.0

Sem --tag: a tag e derivada de api.app.core.config.API_VERSION (fonte unica de
verdade, Fase 01) -- nunca digite o numero da versao manualmente aqui.
Com --tag: o valor precisa coincidir com API_VERSION; divergencia falha
explicitamente (Secao 9: "Sem duplicacao de versao"), em vez de construir uma
imagem com identidade ambigua.

Ao final, valida a propria imagem que acabou de construir (tag == server_version
== label org.opencontainers.image.version) antes de reportar sucesso. Nao faz
push para nenhum registry -- isso continua sendo um passo manual do operador
(`docker push <image>`), fora do escopo desta fase.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.app.core.config import API_VERSION  # noqa: E402

DEFAULT_REPOSITORY = "controle-producao-api"
DOCKERFILE = ROOT / "api" / "Dockerfile"


class ReleaseVersionMismatchError(ValueError):
    pass


def resolve_release_tag(requested_tag: str | None, *, source_version: str = API_VERSION) -> str:
    """Resolve a tag oficial da imagem a partir da fonte central de versoes."""
    if requested_tag is None:
        return source_version
    if requested_tag != source_version:
        raise ReleaseVersionMismatchError(
            f"Tag solicitada '{requested_tag}' diverge de server_version '{source_version}' "
            "(api.app.core.config.API_VERSION). Corrija a tag ou atualize API_VERSION antes de gerar a release."
        )
    return requested_tag


def resolve_commit_sha(*, cwd: Path = ROOT) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=cwd, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip() or "unknown"


def resolve_build_time(*, now: datetime | None = None) -> str:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_image(*, image_ref: str, server_version: str, commit_sha: str, build_time: str, dockerfile: Path = DOCKERFILE, context: Path = ROOT) -> None:
    args = [
        "docker", "build",
        "-f", str(dockerfile),
        "--build-arg", f"SERVER_VERSION={server_version}",
        "--build-arg", f"COMMIT_SHA={commit_sha}",
        "--build-arg", f"BUILD_TIME={build_time}",
        "-t", image_ref,
        str(context),
    ]
    subprocess.run(args, check=True)


def inspect_labels(image_ref: str) -> dict[str, str]:
    result = subprocess.run(
        ["docker", "image", "inspect", image_ref, "--format", "{{json .Config.Labels}}"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout.strip() or "{}")


def verify_image_identity(image_ref: str, *, expected_version: str) -> None:
    """Teste de identidade minimo (Secao 23): a label
    org.opencontainers.image.version deve bater com a versao esperada."""
    labels = inspect_labels(image_ref)
    actual = labels.get("org.opencontainers.image.version")
    if actual != expected_version:
        raise ReleaseVersionMismatchError(
            f"Label org.opencontainers.image.version='{actual}' diverge da versao esperada '{expected_version}'."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Constroi e valida a identidade de uma imagem de release do backend.")
    parser.add_argument("--registry", required=True, help="Ex.: ghcr.io/sua-organizacao")
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--tag", default=None, help="Se informado, precisa coincidir com API_VERSION.")
    args = parser.parse_args(argv)

    try:
        version = resolve_release_tag(args.tag)
    except ReleaseVersionMismatchError as exc:
        print(f"ERRO: {exc}")
        return 1

    commit_sha = resolve_commit_sha()
    build_time = resolve_build_time()
    image_ref = f"{args.registry}/{args.repository}:{version}"

    print(f"Construindo {image_ref} (commit={commit_sha}, build_time={build_time})...")
    try:
        build_image(image_ref=image_ref, server_version=version, commit_sha=commit_sha, build_time=build_time)
    except subprocess.CalledProcessError:
        print("ERRO: docker build falhou.")
        return 1

    try:
        verify_image_identity(image_ref, expected_version=version)
    except ReleaseVersionMismatchError as exc:
        print(f"ERRO: {exc}")
        return 1

    print(f"OK: {image_ref} construida e identidade validada (version={version}, commit={commit_sha}).")
    print("Digest imutavel so existe apos 'docker push' para um registry -- ver docs/architecture/DOCKER_RELEASE_IMAGES.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
