"""Layout de diretorios do Updater (Fase 10, Secao 10).

Reaproveita app.services.app_paths.get_app_data_dir() (Fase 01/dev) como raiz
-- nao cria um segundo sistema de resolucao de diretorios. Tudo do Updater
fica sob um subdiretorio proprio ('updater/'), inteiramente separado do
mecanismo legado em app.services.update_* (que usa get_updates_dir(), uma
pasta plana com pending_update.json/instaladores) para os dois nao colidirem.

install/            <- get_app_data_dir() nao mora aqui: install_dir vem do
                        UpdateRequest (pasta real da instalacao ativa).
updater/staging/<id>/   <- pacote novo em preparacao (Secao 10)
updater/backup/<id>/    <- snapshot local para desfazer a troca (Secao 19)
updater/journal/        <- UpdateJournal persistido (Secao 26)
updater/logs/            <- log tecnico proprio do Updater (Secao 3)
"""

from __future__ import annotations

from pathlib import Path

from app.services.app_paths import get_app_data_dir


def updater_root_dir() -> Path:
    return get_app_data_dir() / "updater"


def download_dir(request_id: str) -> Path:
    return updater_root_dir() / "downloads" / request_id


def staging_dir(request_id: str) -> Path:
    return updater_root_dir() / "staging" / request_id


def backup_dir(request_id: str) -> Path:
    return updater_root_dir() / "backup" / request_id


def journal_dir() -> Path:
    return updater_root_dir() / "journal"


def manifest_dir() -> Path:
    return updater_root_dir() / "manifest"


def quarantine_dir() -> Path:
    return updater_root_dir() / "quarantine"


def updater_logs_dir() -> Path:
    return updater_root_dir() / "logs"


def lock_path() -> Path:
    return updater_root_dir() / ".updater.lock"


def ensure_updater_dirs() -> None:
    for directory in (updater_root_dir(), journal_dir(), updater_logs_dir()):
        directory.mkdir(parents=True, exist_ok=True)
