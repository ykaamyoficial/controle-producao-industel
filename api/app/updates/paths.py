"""Repositorio local de updates do Desktop (Fase 12, Secao 7).

Toda resolucao de caminho de arquivo parte de um identificador ja validado
(versao SemVer, nome de arquivo ja aprovado no manifesto) -- nunca de um
valor bruto vindo do cliente (Secao 21: protecao contra path traversal).
"""

from __future__ import annotations

from pathlib import Path

from api.app.core.config import get_settings
from api.app.core.versioning import parse_version


class UnsafeVersionSegmentError(ValueError):
    """Levantado quando uma string que deveria ser uma versao SemVer nao e
    segura para uso como segmento de caminho -- nunca usada para montar um
    Path antes de passar por esta validacao."""


def safe_version_segment(version: str) -> str:
    """Valida que `version` e um SemVer valido e devolve exatamente essa
    string para uso como nome de subdiretorio. SemVer valido (Fase 01) ja
    exclui '..', '/', '\\' e qualquer caractere fora de [0-9.] -- nunca
    aceita o valor bruto do cliente sem essa validacao antes."""
    try:
        parse_version(version)
    except ValueError as exc:
        raise UnsafeVersionSegmentError(f"Versao invalida para uso como caminho: {version!r}.") from exc
    return version


def update_repository_root() -> Path:
    settings = get_settings()
    configured = Path(settings.update_repository_dir)
    if configured.is_absolute():
        return configured
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / configured


def staging_dir() -> Path:
    return update_repository_root() / "staging"


def ready_dir() -> Path:
    return update_repository_root() / "ready"


def ready_version_dir(version: str) -> Path:
    return ready_dir() / safe_version_segment(version)


def revoked_dir() -> Path:
    return update_repository_root() / "revoked"


def state_dir() -> Path:
    return update_repository_root() / "state"


def failed_dir() -> Path:
    return update_repository_root() / "failed"


def resolve_ready_manifest_path(version: str) -> Path:
    return ready_version_dir(version) / "manifest.json"


def resolve_ready_package_path(version: str, filename: str) -> Path:
    """`filename` precisa ja ter passado por
    manifest_schema.is_safe_artifact_filename antes de chegar aqui (garantido
    porque so e chamado com o filename persistido no ReleaseRecord, nunca com
    entrada do cliente) -- resolve e confirma que o resultado pertence
    mesmo ao diretorio da versao (defesa em profundidade contra qualquer
    regressao futura na validacao do nome)."""
    version_dir = ready_version_dir(version).resolve()
    candidate = (version_dir / filename).resolve()
    try:
        candidate.relative_to(version_dir)
    except ValueError as exc:
        raise UnsafeVersionSegmentError(f"Caminho de artefato fora do diretorio da release: {filename!r}.") from exc
    return candidate


def ensure_repository_dirs() -> None:
    for directory in (staging_dir(), ready_dir(), revoked_dir(), state_dir(), failed_dir()):
        directory.mkdir(parents=True, exist_ok=True)
