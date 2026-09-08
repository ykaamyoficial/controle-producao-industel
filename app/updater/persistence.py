"""Fronteira entre binarios atualizaveis e dados locais persistentes (Fase 10,
Secao 16).

Na instalacao empacotada atual, config/logs/cache/updates ja vivem fora de
install_dir (em ProgramData, ver app.services.app_paths) -- o pacote de
atualizacao, por definicao (Secao 14: "o pacote deve conter somente arquivos
de aplicacao atualizaveis"), nunca deveria conter essas entradas. Esta
allowlist existe como camada de defesa adicional: se algum layout de
instalacao colocar dados persistentes dentro de install_dir (ex.: modo dev),
eles sobrevivem a troca de qualquer forma. Nunca preserva um arquivo
desconhecido so por existir -- so o que bate com a allowlist documentada."""

from __future__ import annotations

import fnmatch
import shutil
from pathlib import Path

DEFAULT_PROTECTED_PATTERNS: tuple[str, ...] = (
    "config/",
    "data/",
    "logs/",
    "cache/",
    "certs/",
    ".env",
    ".env.*",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    # Desinstalador do Inno Setup: criado no install_dir na primeira
    # instalacao, NAO faz parte do pacote de atualizacao. Sem preservar,
    # o swap de diretorio apagaria o "Desinstalar" do Painel de Controle.
    "unins*.exe",
    "unins*.dat",
)


def is_protected(relative_posix_path: str, patterns: tuple[str, ...] = DEFAULT_PROTECTED_PATTERNS) -> bool:
    for pattern in patterns:
        if pattern.endswith("/"):
            top = pattern.rstrip("/")
            if relative_posix_path == top or relative_posix_path.startswith(top + "/"):
                return True
        elif fnmatch.fnmatch(relative_posix_path, pattern) or fnmatch.fnmatch(Path(relative_posix_path).name, pattern):
            return True
    return False


def copy_protected_files(
    *,
    source_install_dir: Path,
    target_install_dir: Path,
    patterns: tuple[str, ...] = DEFAULT_PROTECTED_PATTERNS,
) -> list[str]:
    """Copia (nunca move) do install_dir ATUAL para o staging ja extraido
    qualquer arquivo protegido -- dados persistentes sempre prevalecem sobre
    o que o pacote eventualmente trouxer com o mesmo caminho relativo."""
    if not source_install_dir.exists():
        return []

    preserved: list[str] = []
    for path in source_install_dir.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source_install_dir).as_posix()
        if not is_protected(relative, patterns):
            continue
        destination = target_install_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        preserved.append(relative)
    return preserved
