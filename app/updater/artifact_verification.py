"""Verificacao do artefato baixado contra o manifesto (Fase 11, Secoes 18-20).

Reaproveita sha256_file (Fase 10, app.updater.validation -- streaming, ja
aborta sem retornar hash parcial em erro de leitura) em vez de duplicar o
calculo. O tamanho e sempre conferido antes/junto do hash (Secao 18):
tamanho divergente ja caracteriza artefato invalido sem precisar ler o
arquivo inteiro de novo.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.updater.manifest import ManifestValidationError, ReleaseManifest, validate_manifest_dict
from app.updater.validation import sha256_file


class ArtifactVerificationStatus(str, Enum):
    NOT_CHECKED = "NOT_CHECKED"
    VALID = "VALID"
    SIZE_MISMATCH = "SIZE_MISMATCH"
    HASH_MISMATCH = "HASH_MISMATCH"
    MANIFEST_INVALID = "MANIFEST_INVALID"
    FILE_MISSING = "FILE_MISSING"
    READ_ERROR = "READ_ERROR"


@dataclass(frozen=True)
class ArtifactVerificationResult:
    status: ArtifactVerificationStatus
    detail: str
    actual_size: int | None = None
    actual_sha256: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.status == ArtifactVerificationStatus.VALID


def verify_artifact_against_manifest(file_path: Path, manifest: ReleaseManifest) -> ArtifactVerificationResult:
    if not file_path.is_file():
        return ArtifactVerificationResult(ArtifactVerificationStatus.FILE_MISSING, f"Arquivo nao encontrado: '{file_path}'.")

    try:
        actual_size = file_path.stat().st_size
    except OSError as exc:
        return ArtifactVerificationResult(ArtifactVerificationStatus.READ_ERROR, f"Falha ao ler metadados do arquivo: {exc}")

    if actual_size != manifest.artifact.size_bytes:
        return ArtifactVerificationResult(
            ArtifactVerificationStatus.SIZE_MISMATCH,
            f"Tamanho do arquivo ({actual_size}) diverge do manifesto ({manifest.artifact.size_bytes}).",
            actual_size=actual_size,
        )

    try:
        actual_sha256 = sha256_file(file_path)
    except OSError as exc:
        return ArtifactVerificationResult(ArtifactVerificationStatus.READ_ERROR, f"Falha ao ler o arquivo para calcular o hash: {exc}", actual_size=actual_size)

    if not hmac.compare_digest(actual_sha256, manifest.artifact.sha256):
        return ArtifactVerificationResult(
            ArtifactVerificationStatus.HASH_MISMATCH,
            f"SHA-256 divergente do manifesto (esperado prefixo {manifest.artifact.sha256[:12]}...).",
            actual_size=actual_size, actual_sha256=actual_sha256,
        )

    return ArtifactVerificationResult(ArtifactVerificationStatus.VALID, "OK", actual_size=actual_size, actual_sha256=actual_sha256)


def verify_download(*, manifest_data: dict, file_path: Path) -> ArtifactVerificationResult:
    """Ponto de entrada unico (Secao 21): valida o manifesto primeiro; um
    manifesto invalido nunca chega a checar o arquivo."""
    try:
        manifest = validate_manifest_dict(manifest_data)
    except ManifestValidationError as exc:
        return ArtifactVerificationResult(ArtifactVerificationStatus.MANIFEST_INVALID, str(exc))
    return verify_artifact_against_manifest(file_path, manifest)
