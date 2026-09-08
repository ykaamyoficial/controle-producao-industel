"""Validacao da instalacao nova, depois da troca de arquivos e antes de
limpar o backup local (Fase 10, Secao 22). Nunca executa operacoes de
negocio reais -- apenas checagens estruturais no sistema de arquivos."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InstallValidationResult:
    ok: bool
    detail: str


def validate_installation(
    *,
    install_dir: Path,
    executable_path: Path,
    target_version: str,
    protected_relative_paths: list[str] | None = None,
) -> InstallValidationResult:
    if not executable_path.is_file():
        return InstallValidationResult(False, f"Executavel principal ausente apos a troca: '{executable_path}'.")

    leftover = [str(path) for path in install_dir.rglob("*.part")]
    if leftover:
        return InstallValidationResult(False, f"Arquivo(s) '.part' promovidos por engano: {leftover}.")

    for relative in protected_relative_paths or []:
        if not (install_dir / relative).exists():
            return InstallValidationResult(False, f"Arquivo/pasta persistente ausente apos a troca: '{relative}'.")

    # Marcador de versao opcional dentro do proprio pacote (VERSION, na raiz de
    # install_dir). Nao e obrigatorio nesta fase -- o manifest oficial da Fase 11
    # tornara essa confirmacao formal/bloqueante; por ora, so valida SE o pacote
    # decidiu incluir esse arquivo.
    version_marker = install_dir / "VERSION"
    if version_marker.is_file():
        declared = version_marker.read_text(encoding="utf-8").strip()
        if declared and declared != target_version:
            return InstallValidationResult(
                False, f"Versao declarada no pacote ('{declared}') diverge de target_version ('{target_version}')."
            )

    return InstallValidationResult(True, "OK")
