from __future__ import annotations

from app.versioning.models import SEMVER_PATTERN, SemVer


def parse_version(value: str) -> SemVer:
    """Converte uma string MAJOR.MINOR.PATCH (com 'v' opcional) em SemVer tipado.

    Levanta ValueError para valores vazios ou fora do formato esperado.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Versao nao pode ser vazia.")
    candidate = value.strip()
    match = SEMVER_PATTERN.match(candidate)
    if not match:
        raise ValueError(f"Versao invalida (esperado MAJOR.MINOR.PATCH): '{value}'")
    major, minor, patch = (int(part) for part in match.groups())
    return SemVer(major, minor, patch)


def compare_versions(a: str | SemVer, b: str | SemVer) -> int:
    """Compara duas versoes numericamente. Retorna -1, 0 ou 1."""
    left = a if isinstance(a, SemVer) else parse_version(a)
    right = b if isinstance(b, SemVer) else parse_version(b)
    if left.as_tuple() < right.as_tuple():
        return -1
    if left.as_tuple() > right.as_tuple():
        return 1
    return 0


def is_version_at_least(current: str | SemVer, minimum: str | SemVer) -> bool:
    return compare_versions(current, minimum) >= 0


def is_version_newer(candidate: str | SemVer, current: str | SemVer) -> bool:
    return compare_versions(candidate, current) > 0
