from __future__ import annotations

from pathlib import Path

from api.app.core.config import get_settings


def audit_spool_root() -> Path:
    settings = get_settings()
    configured = Path(settings.audit_spool_dir)
    if configured.is_absolute():
        return configured
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / configured


def pending_dir() -> Path:
    return audit_spool_root() / "pending"


def processed_dir() -> Path:
    return audit_spool_root() / "processed"


def failed_dir() -> Path:
    return audit_spool_root() / "failed"


def ensure_spool_dirs() -> None:
    for directory in (pending_dir(), processed_dir(), failed_dir()):
        directory.mkdir(parents=True, exist_ok=True)
