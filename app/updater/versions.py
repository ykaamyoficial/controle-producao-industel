"""Layout de instalacao versionado (pastas lado a lado + ponteiro).

    <install_root>/
        ControleProducao.exe      launcher (app/launcher) -- estavel
        current.json              ponteiro para a versao ativa
        versions/<semver>/        arvore completa de cada versao

Nada aqui renomeia ou apaga a versao em uso: instalar uma versao nova e criar
uma pasta nova; ativar e regravar o ponteiro (atomico); desfazer e regravar o
ponteiro com a versao anterior. Por isso um processo que continue vivo dentro
da versao antiga nunca impede a atualizacao.

Este modulo e usado tambem pelo launcher, entao depende SO da stdlib.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

POINTER_FILE_NAME = "current.json"
VERSIONS_DIR_NAME = "versions"
APP_EXECUTABLE_NAME = "ControleProducaoApp.exe"
LAUNCHER_EXECUTABLE_NAME = "ControleProducao.exe"
POINTER_SCHEMA = 1

_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class VersionLayoutError(RuntimeError):
    pass


def version_key(version: str) -> tuple[int, int, int]:
    match = _SEMVER.match((version or "").strip())
    if not match:
        raise ValueError(f"Versao invalida (esperado MAJOR.MINOR.PATCH): {version!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def is_valid_version(version: str) -> bool:
    try:
        version_key(version)
    except ValueError:
        return False
    return True


def versions_dir(install_root: Path) -> Path:
    return Path(install_root) / VERSIONS_DIR_NAME


def version_dir(install_root: Path, version: str) -> Path:
    if not is_valid_version(version):
        raise VersionLayoutError(f"Versao invalida: {version!r}")
    return versions_dir(install_root) / version.strip()


def pending_version_dir(install_root: Path, version: str) -> Path:
    """Pasta de trabalho da extracao; vira version_dir() por rename quando completa."""
    return versions_dir(install_root) / f"{version.strip()}.tmp"


def app_executable(install_root: Path, version: str) -> Path:
    return version_dir(install_root, version) / APP_EXECUTABLE_NAME


def launcher_path(install_root: Path) -> Path:
    return Path(install_root) / LAUNCHER_EXECUTABLE_NAME


def pointer_path(install_root: Path) -> Path:
    return Path(install_root) / POINTER_FILE_NAME


def is_versioned_layout(install_root: Path) -> bool:
    return versions_dir(install_root).is_dir() and pointer_path(install_root).is_file()


@dataclass(frozen=True)
class Pointer:
    version: str
    previous_version: str | None = None
    updated_at: str = ""


def read_pointer(install_root: Path) -> Pointer | None:
    """None quando ausente ou ilegivel -- o chamador decide se autorrepara."""
    try:
        data = json.loads(pointer_path(install_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    version = data.get("version")
    if not isinstance(version, str) or not is_valid_version(version):
        return None
    previous = data.get("previous_version")
    if previous is not None and (not isinstance(previous, str) or not is_valid_version(previous)):
        previous = None
    return Pointer(version=version.strip(), previous_version=previous, updated_at=str(data.get("updated_at") or ""))


def write_pointer(install_root: Path, version: str, *, previous_version: str | None = None) -> Pointer:
    """Escrita atomica: temp no mesmo diretorio + os.replace. Nunca deixa um
    current.json pela metade, mesmo se faltar energia no meio."""
    version_key(version)
    if previous_version is not None:
        version_key(previous_version)
    root = Path(install_root)
    pointer = Pointer(
        version=version.strip(),
        previous_version=previous_version.strip() if previous_version else None,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    payload = {
        "schema": POINTER_SCHEMA,
        "version": pointer.version,
        "dir": f"{VERSIONS_DIR_NAME}/{pointer.version}",
        "previous_version": pointer.previous_version,
        "updated_at": pointer.updated_at,
    }
    root.mkdir(parents=True, exist_ok=True)
    temp = root / f"{POINTER_FILE_NAME}.{os.getpid()}.tmp"
    try:
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temp, pointer_path(root))
    finally:
        temp.unlink(missing_ok=True)
    return pointer


def list_installed_versions(install_root: Path) -> list[str]:
    """Versoes com executavel presente, da maior para a menor."""
    base = versions_dir(install_root)
    if not base.is_dir():
        return []
    found = [
        entry.name
        for entry in base.iterdir()
        if entry.is_dir() and is_valid_version(entry.name) and (entry / APP_EXECUTABLE_NAME).is_file()
    ]
    return sorted(found, key=version_key, reverse=True)


def resolve_active_version(install_root: Path) -> str | None:
    """Versao que o launcher deve abrir. Ponteiro valido e com executavel vence;
    senao autorrepara escolhendo a maior versao instalada."""
    pointer = read_pointer(install_root)
    if pointer is not None and (version_dir(install_root, pointer.version) / APP_EXECUTABLE_NAME).is_file():
        return pointer.version
    installed = list_installed_versions(install_root)
    return installed[0] if installed else None


def cleanup_old_versions(install_root: Path, *, keep: int = 2, protect: tuple[str, ...] = ()) -> tuple[list[str], list[str]]:
    """Remove versoes antigas e restos de extracao (*.tmp). Mantem a ativa, a
    anterior do ponteiro e as `keep` mais novas. Falha ao apagar (arquivo em
    uso) nao e erro: fica para a proxima limpeza. Retorna (removidas, adiadas)."""
    root = Path(install_root)
    base = versions_dir(root)
    if not base.is_dir():
        return [], []

    pointer = read_pointer(root)
    keep_set = set(protect)
    if pointer is not None:
        keep_set.add(pointer.version)
        if pointer.previous_version:
            keep_set.add(pointer.previous_version)
    keep_set.update(list_installed_versions(root)[: max(keep, 0)])

    removed: list[str] = []
    deferred: list[str] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        is_leftover = entry.name.endswith(".tmp")
        if not is_leftover and (not is_valid_version(entry.name) or entry.name in keep_set):
            continue
        shutil.rmtree(entry, ignore_errors=True)
        (deferred if entry.exists() else removed).append(entry.name)
    return removed, deferred
