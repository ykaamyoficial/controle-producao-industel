"""Extracao segura de pacotes ZIP (Fase 10, Secao 15 -- "Seguranca obrigatoria").

Extracao de arquivo compactado sem validacao de caminho pode sobrescrever
arquivos fora da pasta do programa. Cada entrada e validada ANTES de
extraida: nunca confiamos no nome recebido dentro do pacote.
"""

from __future__ import annotations

import shutil
import stat
import zipfile
from pathlib import Path


class PathTraversalError(RuntimeError):
    """Uma entrada do pacote tentou escapar do diretorio de staging."""


def _is_symlink_entry(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode) if mode else False


def _reject_unsafe_name(name: str) -> None:
    if not name or name.strip() == "":
        raise PathTraversalError("Entrada com nome vazio no pacote.")
    if "\\" in name:
        raise PathTraversalError(f"Entrada com separador invalido rejeitada: '{name}'.")
    if name.startswith("/"):
        raise PathTraversalError(f"Caminho absoluto rejeitado: '{name}'.")
    if len(name) >= 2 and name[1] == ":":
        raise PathTraversalError(f"Drive letter inesperada rejeitada: '{name}'.")
    parts = [part for part in name.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise PathTraversalError(f"Sequencia '..' rejeitada em: '{name}'.")


def _is_within_directory(directory: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def safe_extract_zip(archive_path: Path, destination_dir: Path) -> list[str]:
    """Extrai `archive_path` inteiramente dentro de `destination_dir`.
    Levanta PathTraversalError na primeira entrada suspeita, ANTES de
    extrair qualquer coisa -- validacao completa acontece antes da escrita
    do primeiro byte (Secao 15: 'garantir que todo arquivo extraido
    permaneca dentro do staging')."""
    destination_dir = destination_dir.resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        planned: list[tuple[zipfile.ZipInfo, Path]] = []
        for info in infos:
            name = info.filename
            if _is_symlink_entry(info):
                raise PathTraversalError(f"Entrada de symlink rejeitada: '{name}'.")
            _reject_unsafe_name(name)
            target_path = destination_dir / name
            if not _is_within_directory(destination_dir, target_path):
                raise PathTraversalError(f"Entrada escaparia do staging: '{name}'.")
            planned.append((info, target_path))

        extracted: list[str] = []
        for info, target_path in planned:
            if info.filename.endswith("/"):
                target_path.mkdir(parents=True, exist_ok=True)
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target_path.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            extracted.append(info.filename)
        return extracted
