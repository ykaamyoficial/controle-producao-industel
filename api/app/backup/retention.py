from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("api.backup")


@dataclass(frozen=True)
class RetentionPolicy:
    """Politica conservadora de retencao (Secao 21). Defaults seguros e
    documentados: mantem os 10 backups validos mais recentes, nunca remove nada
    com menos de 7 dias, e nunca remove o backup que acabou de proteger o
    deployment atual, mesmo que ele já esteja fora da janela de contagem/idade."""

    keep_last_successful: int = 10
    minimum_age_before_delete_days: int = 7
    protect_current_backup_id: bool = True


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def apply_retention(backup_dir: Path, *, policy: RetentionPolicy, current_backup_id: str | None) -> list[str]:
    """Remove backups antigos reconhecidos pelo mecanismo oficial (possuem
    manifest *.manifest.json valido) que estejam fora da janela de quantidade E
    fora da janela de idade minima. Nunca toca em arquivo sem manifest
    reconhecido, e nunca remove current_backup_id quando protect_current_backup_id.

    Retorna a lista de backup_ids removidos.
    """
    if not backup_dir.exists():
        return []

    entries: list[tuple[Path, dict]] = []
    for manifest_path in backup_dir.glob("*.manifest.json"):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or data.get("validation") != "VALID":
            continue
        created_at = _parse_iso(data.get("created_at_utc"))
        if created_at is None:
            continue
        entries.append((manifest_path, data, created_at))

    entries.sort(key=lambda item: item[2], reverse=True)

    keep_ids = {current_backup_id} if (policy.protect_current_backup_id and current_backup_id) else set()
    now = datetime.now(timezone.utc)
    removed: list[str] = []

    for index, (manifest_path, data, created_at) in enumerate(entries):
        backup_id = data.get("backup_id")
        if backup_id in keep_ids:
            continue
        if index < policy.keep_last_successful:
            continue
        age_days = (now - created_at).total_seconds() / 86400
        if age_days < policy.minimum_age_before_delete_days:
            continue

        dump_path = Path(data["file_path"]) if data.get("file_path") else None
        try:
            manifest_path.unlink(missing_ok=True)
            if dump_path is not None:
                dump_path.unlink(missing_ok=True)
        except OSError:
            log.warning("backup_retention_delete_failed | backup_id=%s", backup_id)
            continue
        log.info("BACKUP_RETENTION_APPLIED | backup_id=%s | age_days=%.1f", backup_id, age_days)
        removed.append(str(backup_id))

    return removed
