from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from app.services.app_logging import get_logger


log = get_logger("sqlite")


class DatabaseSafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class DatabaseHealth:
    path: str
    exists: bool
    readable: bool
    writable: bool
    integrity_ok: bool
    foreign_key_errors: int
    detail: str = ""


def is_network_path(path: str | Path) -> bool:
    value = str(path)
    return value.startswith("\\\\") or value.startswith("//")


def inspect_database(path: str | Path, *, require_schema: bool = False, timeout: float = 8) -> DatabaseHealth:
    db_path = Path(path)
    if not db_path.exists():
        return DatabaseHealth(str(db_path), False, False, False, False, 0, "Arquivo nao encontrado.")
    readable = os.access(db_path, os.R_OK)
    writable = os.access(db_path, os.W_OK) and os.access(db_path.parent, os.W_OK)
    if not readable:
        return DatabaseHealth(str(db_path), True, False, writable, False, 0, "Sem permissao de leitura.")
    try:
        # SQLite URI authorities do not support Windows UNC hosts (file://server/...).
        # Open the native path and force query_only instead, which works for local and
        # shared paths without writing during diagnostics.
        with closing(sqlite3.connect(str(db_path), timeout=timeout)) as conn:
            conn.execute("PRAGMA query_only=ON")
            integrity_rows = conn.execute("PRAGMA integrity_check").fetchall()
            integrity_ok = len(integrity_rows) == 1 and str(integrity_rows[0][0]).lower() == "ok"
            foreign_errors = len(conn.execute("PRAGMA foreign_key_check").fetchall())
            if require_schema:
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                required = {"usuarios", "processos", "historico_status"}
                if not required.issubset(tables):
                    return DatabaseHealth(str(db_path), True, True, writable, False, foreign_errors, "Estrutura do sistema ausente.")
            detail = "ok" if integrity_ok else "; ".join(str(row[0]) for row in integrity_rows[:10])
            return DatabaseHealth(str(db_path), True, True, writable, integrity_ok, foreign_errors, detail)
    except sqlite3.Error as exc:
        log.exception("Falha ao validar banco | path=%s", db_path)
        return DatabaseHealth(str(db_path), True, True, writable, False, 0, str(exc))


def require_healthy_database(path: str | Path, *, require_schema: bool = False) -> DatabaseHealth:
    health = inspect_database(path, require_schema=require_schema)
    if not health.exists or not health.readable or not health.integrity_ok or health.foreign_key_errors:
        raise DatabaseSafetyError(
            "O banco selecionado nao esta integro e nao sera aberto. "
            "Use a area de Diagnostico para criar uma copia e tentar recuperacao."
        )
    return health


def safe_backup(source_path: str | Path, backup_dir: str | Path, reason: str) -> Path:
    source_path = Path(source_path)
    require_healthy_database(source_path)
    destination_dir = Path(backup_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    target = destination_dir / f"controle_producao_{reason}_{datetime.now():%Y%m%d_%H%M%S}.db"
    try:
        with closing(sqlite3.connect(str(source_path), timeout=30)) as source, closing(sqlite3.connect(str(target))) as destination:
            source.backup(destination)
    except sqlite3.Error as exc:
        target.unlink(missing_ok=True)
        raise DatabaseSafetyError(f"Nao foi possivel criar backup seguro: {exc}") from exc
    require_healthy_database(target)
    log.info("Backup seguro criado | motivo=%s | origem=%s | destino=%s", reason, source_path, target)
    return target


def create_daily_backup(source_path: str | Path, backup_dir: str | Path, keep_days: int = 30) -> Path | None:
    destination_dir = Path(backup_dir) / "daily"
    marker = destination_dir / f".backup_{datetime.now():%Y%m%d}"
    if marker.exists():
        return None
    target = safe_backup(source_path, destination_dir, "diario")
    marker.touch()
    backups = sorted(destination_dir.glob("controle_producao_diario_*.db"), key=lambda item: item.stat().st_mtime, reverse=True)
    for old in backups[max(1, keep_days):]:
        old.unlink(missing_ok=True)
    return target


def recover_database(source_path: str | Path, output_dir: str | Path) -> dict[str, str | bool]:
    source = Path(source_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    preserved = output / f"corrompido_original_{stamp}{source.suffix or '.db'}"
    shutil.copy2(source, preserved)
    recovered = output / f"controle_producao_recuperado_{stamp}.db"
    report_path = output / f"relatorio_recuperacao_{stamp}.json"
    report: dict[str, str | bool] = {"source": str(source), "preserved": str(preserved), "recovered": "", "success": False, "detail": ""}
    sqlite_cli = shutil.which("sqlite3")
    if sqlite_cli:
        sql_path = output / f"recover_{stamp}.sql"
        try:
            result = subprocess.run([sqlite_cli, str(preserved), ".recover"], capture_output=True, text=True, timeout=120)
            sql_path.write_text(result.stdout, encoding="utf-8")
            if result.returncode == 0 and result.stdout.strip():
                subprocess.run([sqlite_cli, str(recovered)], input=result.stdout, text=True, check=True, timeout=120)
                require_healthy_database(recovered)
                report.update(success=True, recovered=str(recovered), detail="Recuperacao SQLite concluida.")
            else:
                report["detail"] = result.stderr or "sqlite3 .recover nao produziu dados."
        except Exception as exc:
            report["detail"] = repr(exc)
    else:
        report["detail"] = "Utilitario sqlite3 nao encontrado; original preservado para recuperacao especializada."
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log.warning("Tentativa de recuperacao | relatorio=%s | sucesso=%s", report_path, report["success"])
    report["report"] = str(report_path)
    return report
