"""Gera o manifest.json deterministico de uma release Desktop (Fase 11).

Uso:
    python scripts/generate_release_manifest.py \
        --artifact release/ControleProducaoSetup-2.6.0.exe \
        --minimum-server-version 0.8.0 --api-contract-version v1

Sem --release-version: a versao e derivada de app.version.APP_VERSION (fonte
unica de verdade, Fase 01) -- nunca digite o numero da versao manualmente
aqui. Com --release-version: o valor precisa coincidir com APP_VERSION;
divergencia falha explicitamente (mesmo padrao de scripts/build_release_image.py,
Fase 07).

SHA-256 e size_bytes sao SEMPRE calculados a partir do artefato real -- este
script nunca aceita um hash informado manualmente (Secao 11).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.updater.manifest import ArtifactDescriptor, ManifestValidationError, ReleaseChannel, ReleaseManifest, validate_manifest_dict  # noqa: E402
from app.updater.validation import sha256_file  # noqa: E402
from app.version import APP_VERSION  # noqa: E402


class ManifestGenerationError(RuntimeError):
    pass


def resolve_release_version(requested: str | None, *, source_version: str = APP_VERSION) -> str:
    if requested is None:
        return source_version
    if requested != source_version:
        raise ManifestGenerationError(
            f"release_version solicitada '{requested}' diverge de app.version.APP_VERSION '{source_version}'. "
            "Corrija o argumento ou atualize APP_VERSION antes de gerar o manifesto."
        )
    return requested


def generate_manifest(
    *,
    artifact_path: Path,
    release_version: str,
    channel: str,
    minimum_server_version: str,
    api_contract_version: str,
    artifact_url: str | None = None,
    release_notes: str | None = None,
    content_type: str = "application/octet-stream",
    published_at: datetime | None = None,
) -> ReleaseManifest:
    if not artifact_path.is_file():
        raise ManifestGenerationError(f"Artefato nao encontrado: '{artifact_path}'.")

    size_bytes = artifact_path.stat().st_size
    sha256 = sha256_file(artifact_path)
    artifact = ArtifactDescriptor(filename=artifact_path.name, size_bytes=size_bytes, sha256=sha256, content_type=content_type)

    manifest = ReleaseManifest(
        manifest_schema_version=1,
        release_version=release_version,
        channel=channel,
        published_at=(published_at or datetime.now(timezone.utc)),
        minimum_server_version=minimum_server_version,
        api_contract_version=api_contract_version,
        artifact=artifact,
        artifact_url=artifact_url,
        release_notes=release_notes,
    )
    # Valida o proprio manifesto recem-construido antes de devolver -- nunca
    # escreve em disco algo que o cliente rejeitaria.
    validate_manifest_dict(manifest.to_dict())
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gera manifest.json deterministico para uma release Desktop (Fase 11).")
    parser.add_argument("--artifact", required=True, help="Caminho do instalador/pacote final ja fechado.")
    parser.add_argument("--release-version", default=None, help="Se informado, precisa coincidir com app.version.APP_VERSION.")
    parser.add_argument(
        "--channel", default=ReleaseChannel.PRODUCTION.value, choices=[item.value for item in ReleaseChannel],
        help="Canal do manifesto (vocabulario proprio da Fase 11 -- nao e o mesmo campo que app.version.APP_CHANNEL).",
    )
    parser.add_argument("--minimum-server-version", required=True)
    parser.add_argument("--api-contract-version", required=True)
    parser.add_argument("--artifact-url", default=None)
    parser.add_argument("--release-notes", default=None)
    parser.add_argument("--content-type", default="application/vnd.microsoft.portable-executable")
    parser.add_argument("--output", default=None, help="Caminho do manifest.json a escrever (default: ao lado do artefato).")
    args = parser.parse_args(argv)

    try:
        version = resolve_release_version(args.release_version)
        manifest = generate_manifest(
            artifact_path=Path(args.artifact), release_version=version, channel=args.channel,
            minimum_server_version=args.minimum_server_version, api_contract_version=args.api_contract_version,
            artifact_url=args.artifact_url, release_notes=args.release_notes, content_type=args.content_type,
        )
    except (ManifestGenerationError, ManifestValidationError) as exc:
        print(f"ERRO: {exc}")
        return 1

    output_path = Path(args.output) if args.output else Path(args.artifact).with_name("manifest.json")
    output_path.write_text(manifest.to_canonical_json(), encoding="utf-8")

    print(f"OK: manifesto gerado em {output_path}")
    print(f"release_version={manifest.release_version}")
    print(f"artifact.filename={manifest.artifact.filename}")
    print(f"artifact.size_bytes={manifest.artifact.size_bytes}")
    print(f"artifact.sha256={manifest.artifact.sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
