"""Interface de validacao de integridade do pacote (Fase 10, Secao 13).

A Fase 11 vai definir o manifest oficial e o SHA-256 publicado/assinado pela
infraestrutura de release -- esta fase so prepara a interface tipada que sera
alimentada por aquele manifest. `MISSING_METADATA` e aceito somente enquanto
`expected_hash` nao for fornecido (modo transitorio/teste); a partir do
momento em que o manifest oficial existir (Fase 11), todo request precisara
trazer um hash esperado e MISSING_METADATA deixara de ser um resultado aceito
pelo chamador -- o enum/funcao ja estao prontos para essa mudanca de politica
sem qualquer alteracao de assinatura.
"""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class PackageValidationStatus(str, Enum):
    VALID = "VALID"
    INVALID_HASH = "INVALID_HASH"
    INVALID_SIZE = "INVALID_SIZE"
    MISSING_METADATA = "MISSING_METADATA"
    INVALID_PACKAGE = "INVALID_PACKAGE"


@dataclass(frozen=True)
class PackageValidationResult:
    status: PackageValidationStatus
    detail: str
    actual_size: int | None = None
    actual_hash: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.status == PackageValidationStatus.VALID


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_package(
    path: Path,
    *,
    expected_hash: str | None = None,
    expected_size: int | None = None,
) -> PackageValidationResult:
    """Fase 10, Secao 13. Se `expected_hash` for fornecido, a verificacao de
    hash e obrigatoria e qualquer divergencia bloqueia (nunca instala um
    pacote com hash divergente). Sem `expected_hash`, aceita o pacote como
    MISSING_METADATA somente se a estrutura basica (arquivo existe, e um ZIP
    valido) estiver correta -- nunca promove um arquivo corrompido so por
    faltar hash."""
    if not path.is_file():
        return PackageValidationResult(PackageValidationStatus.INVALID_PACKAGE, f"Pacote nao encontrado: '{path}'.")

    actual_size = path.stat().st_size
    if expected_size is not None and actual_size != expected_size:
        return PackageValidationResult(
            PackageValidationStatus.INVALID_SIZE,
            f"Tamanho do pacote ({actual_size}) diverge do esperado ({expected_size}).",
            actual_size=actual_size,
        )

    if not zipfile.is_zipfile(path):
        return PackageValidationResult(PackageValidationStatus.INVALID_PACKAGE, f"'{path}' nao e um pacote ZIP valido.", actual_size=actual_size)
    try:
        with zipfile.ZipFile(path) as archive:
            bad_entry = archive.testzip()
            if bad_entry is not None:
                return PackageValidationResult(
                    PackageValidationStatus.INVALID_PACKAGE, f"Entrada corrompida no pacote: '{bad_entry}'.", actual_size=actual_size,
                )
            if not archive.namelist():
                return PackageValidationResult(PackageValidationStatus.INVALID_PACKAGE, "Pacote ZIP vazio.", actual_size=actual_size)
    except (zipfile.BadZipFile, OSError) as exc:
        return PackageValidationResult(PackageValidationStatus.INVALID_PACKAGE, f"Falha ao abrir o pacote: {exc}", actual_size=actual_size)

    actual_hash = sha256_file(path)
    if expected_hash is None:
        return PackageValidationResult(
            PackageValidationStatus.MISSING_METADATA,
            "Nenhum hash esperado fornecido (modo transitorio/teste da Fase 10 -- "
            "sera bloqueante a partir do manifest oficial da Fase 11).",
            actual_size=actual_size, actual_hash=actual_hash,
        )
    if actual_hash.lower() != expected_hash.lower():
        return PackageValidationResult(
            PackageValidationStatus.INVALID_HASH,
            f"Hash divergente: esperado={expected_hash} calculado={actual_hash}.",
            actual_size=actual_size, actual_hash=actual_hash,
        )
    return PackageValidationResult(PackageValidationStatus.VALID, "OK", actual_size=actual_size, actual_hash=actual_hash)
