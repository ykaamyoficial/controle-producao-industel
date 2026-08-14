"""Estrategia de swap no Windows (Fase 10, Secao 20): rename da pasta ativa
para backup, rename do staging para ativa, rollback por rename se qualquer
etapa falhar -- nunca copia centenas de arquivos diretamente sobre a pasta
ativa. `Path.rename` de uma pasta inteira e uma operacao unica no NTFS
(muito mais proxima de atomica do que copiar arquivo por arquivo), mas ainda
pode falhar por sharing violation se algum arquivo dentro da pasta estiver
aberto (Secao 21) -- por isso o orquestrador so chama isto depois de
confirmar que o processo pai (Desktop) encerrou (Secao 18).
"""

from __future__ import annotations

import time
from pathlib import Path


class SwapError(RuntimeError):
    def __init__(self, message: str, *, sharing_violation: bool = False):
        super().__init__(message)
        self.sharing_violation = sharing_violation


def _rename_with_retry(source: Path, destination: Path, *, retries: int, retry_delay_seconds: float, what: str) -> None:
    last_exc: Exception | None = None
    for _ in range(retries):
        try:
            source.rename(destination)
            return
        except (PermissionError, OSError) as exc:
            last_exc = exc
            time.sleep(retry_delay_seconds)
    sharing = isinstance(last_exc, PermissionError) or getattr(last_exc, "winerror", None) == 32
    raise SwapError(f"Falha ao renomear ({what}): '{source}' -> '{destination}': {last_exc}", sharing_violation=sharing) from last_exc


def demote_to_backup(*, install_dir: Path, backup_dir: Path, retries: int = 5, retry_delay_seconds: float = 1.0) -> None:
    """1a etapa do swap: install_dir -> backup_dir."""
    if backup_dir.exists():
        raise SwapError(f"Diretorio de backup ja existe: '{backup_dir}' (troca anterior nao foi limpa).")
    backup_dir.parent.mkdir(parents=True, exist_ok=True)
    _rename_with_retry(install_dir, backup_dir, retries=retries, retry_delay_seconds=retry_delay_seconds, what="instalacao atual -> backup")


def promote_staging(*, staging_dir: Path, install_dir: Path, backup_dir: Path, retries: int = 5, retry_delay_seconds: float = 1.0) -> None:
    """2a etapa do swap: staging_dir -> install_dir. Se falhar, desfaz a 1a
    etapa automaticamente (restaura backup_dir -> install_dir) para nunca
    deixar o sistema sem NENHUM install_dir valido."""
    try:
        _rename_with_retry(staging_dir, install_dir, retries=retries, retry_delay_seconds=retry_delay_seconds, what="staging -> instalacao ativa")
    except SwapError:
        try:
            _rename_with_retry(backup_dir, install_dir, retries=retries, retry_delay_seconds=retry_delay_seconds, what="restauracao de emergencia apos falha no swap")
        except SwapError as restore_exc:
            raise SwapError(
                f"Falha critica: nao foi possivel completar a troca NEM restaurar o backup automaticamente. "
                f"install_dir='{install_dir}' pode estar ausente; backup preservado em '{backup_dir}'. "
                f"Erro de restauracao: {restore_exc}"
            ) from restore_exc
        raise


def apply_swap(*, install_dir: Path, staging_dir: Path, backup_dir: Path, retries: int = 5, retry_delay_seconds: float = 1.0) -> None:
    """Composicao simples das duas etapas, sem nenhum passo intermediario --
    usada quando nao ha necessidade de preservar arquivos persistentes entre
    as duas renomeacoes (ver app.updater.orchestrator para o fluxo completo,
    que injeta a copia de arquivos protegidos entre demote_to_backup e
    promote_staging)."""
    demote_to_backup(install_dir=install_dir, backup_dir=backup_dir, retries=retries, retry_delay_seconds=retry_delay_seconds)
    promote_staging(staging_dir=staging_dir, install_dir=install_dir, backup_dir=backup_dir, retries=retries, retry_delay_seconds=retry_delay_seconds)


def rollback_swap(*, install_dir: Path, backup_dir: Path, retries: int = 5, retry_delay_seconds: float = 1.0) -> Path | None:
    """Desfaz uma troca ja aplicada: manda a instalacao atual (com problema)
    para quarentena e restaura o backup como install_dir. Retorna o caminho
    de quarentena (para diagnostico), se houve algo a mover."""
    if not backup_dir.exists():
        raise SwapError(f"Nao existe backup para restaurar em '{backup_dir}'.")

    quarantine: Path | None = None
    if install_dir.exists():
        quarantine = install_dir.parent / f"{install_dir.name}.failed-{int(time.time())}"
        _rename_with_retry(install_dir, quarantine, retries=retries, retry_delay_seconds=retry_delay_seconds, what="instalacao com problema -> quarentena")

    _rename_with_retry(backup_dir, install_dir, retries=retries, retry_delay_seconds=retry_delay_seconds, what="backup -> instalacao restaurada")
    return quarantine
