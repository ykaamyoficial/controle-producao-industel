"""PRECHECK_LOCAL (Fase 10, Secao 17): ultima confirmacao antes de fechar o
Desktop e trocar arquivos. Falha em qualquer item = nenhuma alteracao na
instalacao ativa (nada aqui escreve em install_dir)."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.updater.contract import UpdateRequest
from app.updater.validation import PackageValidationResult, PackageValidationStatus


@dataclass(frozen=True)
class PrecheckResult:
    ok: bool
    reason: str | None = None


def run_local_precheck(
    *,
    request: UpdateRequest,
    staging_dir: Path,
    backup_dir: Path,
    validation_result: PackageValidationResult,
    min_free_space_mb: int = 200,
    disk_usage_fn=shutil.disk_usage,
) -> PrecheckResult:
    if not staging_dir.is_dir() or not any(staging_dir.iterdir()):
        return PrecheckResult(False, f"Staging incompleto ou vazio: '{staging_dir}'.")

    if validation_result.status not in (PackageValidationStatus.VALID, PackageValidationStatus.MISSING_METADATA):
        return PrecheckResult(False, f"Pacote nao validado: {validation_result.status.value} -- {validation_result.detail}")

    install_dir = Path(request.install_dir)
    probe_dir = install_dir if install_dir.exists() else install_dir.parent
    if not probe_dir.exists():
        return PrecheckResult(False, f"install_dir nao existe e o diretorio pai tambem nao: '{probe_dir}'.")
    if not _is_writable(probe_dir):
        return PrecheckResult(False, f"Sem permissao de escrita em '{probe_dir}' -- pode exigir elevacao administrativa.")

    if backup_dir.exists():
        return PrecheckResult(False, f"Diretorio de backup ja existe (troca anterior nao foi limpa): '{backup_dir}'.")

    try:
        usage = disk_usage_fn(probe_dir)
    except OSError as exc:
        return PrecheckResult(False, f"Nao foi possivel medir espaco livre em '{probe_dir}': {exc}")
    free_mb = usage.free / (1024 * 1024)
    if free_mb < min_free_space_mb:
        return PrecheckResult(False, f"Espaco livre insuficiente em '{probe_dir}': {free_mb:.0f}MB disponiveis, minimo {min_free_space_mb}MB.")

    return PrecheckResult(True)


def _is_writable(directory: Path) -> bool:
    probe = directory / ".updater-write-check.tmp"
    try:
        probe.write_text("x", encoding="utf-8")
        return True
    except OSError:
        return False
    finally:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass
