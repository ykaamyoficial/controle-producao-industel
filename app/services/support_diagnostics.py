from __future__ import annotations

import json
import os
import platform
import zipfile
from datetime import datetime
from pathlib import Path

from app.services.app_logging import get_logger
from app.services.app_paths import get_diagnostics_dir, get_logs_dir
from app.services.network_diagnostics import diagnose_update_endpoint
from app.services.sqlite_safety import inspect_database
from app.services.update_checker import RELEASES_API_URL
from app.version import APP_VERSION


log = get_logger("diagnostics")


def build_diagnostic_report(db_path: str) -> dict:
    health = inspect_database(db_path, require_schema=True)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "app_version": APP_VERSION,
        "computer": platform.node(),
        "windows_user": os.environ.get("USERNAME", "-"),
        "platform": platform.platform(),
        "database": health.__dict__,
        "updates": diagnose_update_endpoint(RELEASES_API_URL),
    }


def export_diagnostic_zip(db_path: str) -> Path:
    output_dir = get_diagnostics_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"diagnostico_{stamp}.json"
    report_path.write_text(json.dumps(build_diagnostic_report(db_path), ensure_ascii=False, indent=2), encoding="utf-8")
    zip_path = output_dir / f"pacote_diagnostico_{stamp}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(report_path, report_path.name)
        for log_path in get_logs_dir().glob("*.log*"):
            archive.write(log_path, f"logs/{log_path.name}")
    log.info("Pacote de diagnostico exportado | path=%s", zip_path)
    return zip_path
