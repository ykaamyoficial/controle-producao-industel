from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.services.app_logging import get_logger
from app.services.app_paths import get_updates_dir
from app.services.update_checker import is_newer_version
from app.version import APP_VERSION


log = get_logger("updates.state")
PENDING_UPDATE_FILE = "pending_update.json"


def pending_update_path() -> Path:
    return get_updates_dir() / PENDING_UPDATE_FILE


def write_pending_update(
    *,
    target_version: str,
    installer_path: str | Path,
    current_version: str = APP_VERSION,
    sha256: str | None = None,
    backup_path: str | None = None,
) -> Path:
    path = pending_update_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "target_version": target_version,
        "current_version": current_version,
        "installer_path": str(installer_path),
        "sha256": sha256,
        "backup_path": backup_path,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "status": "pending",
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Atualizacao pendente registrada | versao_atual=%s | destino=%s", current_version, target_version)
    return path


def read_pending_update() -> dict[str, Any] | None:
    path = pending_update_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Nao foi possivel ler estado pendente de atualizacao | erro=%s", exc)
        return None
    return payload if isinstance(payload, dict) else None


def clear_pending_update() -> None:
    try:
        pending_update_path().unlink(missing_ok=True)
    except OSError as exc:
        log.warning("Nao foi possivel limpar estado pendente de atualizacao | erro=%s", exc)


def evaluate_pending_update(current_version: str = APP_VERSION) -> dict[str, Any]:
    pending = read_pending_update()
    if not pending:
        return {"has_pending": False, "status": "none"}

    target_version = str(pending.get("target_version") or "")
    if target_version and not is_newer_version(target_version, current_version):
        clear_pending_update()
        log.info("Atualizacao concluida confirmada | versao_instalada=%s | destino=%s", current_version, target_version)
        return {"has_pending": True, "status": "completed", "target_version": target_version}

    log.warning(
        "Atualizacao pendente nao concluida | versao_instalada=%s | destino=%s",
        current_version,
        target_version or "-",
    )
    return {
        "has_pending": True,
        "status": "failed_or_incomplete",
        "target_version": target_version,
        "installer_path": pending.get("installer_path"),
        "started_at": pending.get("started_at"),
    }
