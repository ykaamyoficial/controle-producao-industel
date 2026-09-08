from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote


def create_snapshot(source_path: Path, *, output_dir: Path) -> dict[str, Any]:
    source = source_path.resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = output_dir / f"controle_producao_snapshot_{stamp}.db"
    uri = f"file:{quote(str(source).replace(chr(92), '/'), safe=':/')}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=30)) as source_conn:
        with closing(sqlite3.connect(target)) as target_conn:
            source_conn.backup(target_conn)
    metadata = inspect_sqlite(target, source_path=source)
    metadata_path = output_dir / f"controle_producao_snapshot_{stamp}.json"
    metadata["snapshot_path"] = str(target)
    metadata["metadata_path"] = str(metadata_path)
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return metadata


def inspect_sqlite(path: Path, *, source_path: Path | None = None) -> dict[str, Any]:
    db_path = path.resolve()
    with closing(sqlite3.connect(f"file:{quote(str(db_path).replace(chr(92), '/'), safe=':/')}?mode=ro", uri=True, timeout=30)) as conn:
        conn.row_factory = sqlite3.Row
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        metadata = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source_path": _mask_path(source_path) if source_path else None,
            "database_path": _mask_path(db_path),
            "size_bytes": db_path.stat().st_size,
            "sha256": _sha256(db_path),
            "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_check": _foreign_key_check(conn),
            "journal_mode": conn.execute("PRAGMA journal_mode").fetchone()[0],
            "user_version": conn.execute("PRAGMA user_version").fetchone()[0],
            "page_count": conn.execute("PRAGMA page_count").fetchone()[0],
            "table_count": len(tables),
            "tables": tables,
            "inventory": _inventory(conn, tables),
        }
    return metadata


def _inventory(conn: sqlite3.Connection, tables: list[str]) -> dict[str, Any]:
    has = set(tables)
    proposal_rows = _fetch_all(conn, "SELECT * FROM processos") if "processos" in has else []
    item_rows = _fetch_all(conn, "SELECT * FROM proposta_itens") if "proposta_itens" in has else []
    history_count = _count(conn, "historico_status") if "historico_status" in has else 0
    load_count = _count(conn, "cargas_galvanizacao") if "cargas_galvanizacao" in has else 0
    item_process_ids = {row.get("processo_principal_id") for row in item_rows}
    proposal_ids = {row.get("id") for row in proposal_rows}
    proposal_numbers = [str(row.get("proposta") or "").strip() for row in proposal_rows]
    area_status = Counter(_current_area_status(row) for row in proposal_rows)
    statuses = Counter()
    for row in proposal_rows:
        for key in ("status_geral", "status_producao", "status_galvanizacao", "status_expedicao", "status_almoxarifado"):
            value = str(row.get(key) or "").strip()
            if value:
                statuses[f"{key}:{value}"] += 1
    return {
        "total_proposals": len(proposal_rows),
        "total_items": len(item_rows),
        "total_history": history_count,
        "total_loads": load_count,
        "partial_links": sum(1 for row in proposal_rows if row.get("processo_pai_id")),
        "proposals_without_items": sum(1 for row in proposal_rows if row.get("id") not in item_process_ids),
        "orphan_items": sum(1 for row in item_rows if row.get("processo_principal_id") not in proposal_ids),
        "partial_proposals": sum(1 for row in proposal_rows if row.get("processo_pai_id") or (row.get("numero_parcial") or 0)),
        "cancelled_proposals": sum(1 for row in proposal_rows if str(row.get("status_geral") or "").upper() == "CANCELADA"),
        "completed_proposals": sum(1 for row in proposal_rows if str(row.get("status_geral") or "").upper() in {"ENTREGUE", "FINALIZADO"}),
        "cp00000": sum(1 for value in proposal_numbers if value == "CP00000"),
        "duplicate_proposal_numbers": sorted(value for value, count in Counter(proposal_numbers).items() if value and count > 1),
        "duplicate_proposal_legacy_ids": [],
        "duplicate_item_legacy_ids": [],
        "empty_descriptions": sum(1 for row in item_rows if not str(row.get("descricao") or "").strip()),
        "multiline_descriptions": sum(1 for row in item_rows if "\n" in str(row.get("descricao") or "") or "\r" in str(row.get("descricao") or "")),
        "null_quantities": sum(1 for row in item_rows if row.get("quantidade") is None),
        "null_weights": sum(1 for row in item_rows if row.get("peso") is None),
        "undefined_flags": sum(1 for row in item_rows if row.get("produzir_internamente") in (None, "") or row.get("precisa_galvanizacao") in (None, "")),
        "areas": dict(sorted(area_status.items())),
        "statuses": dict(sorted(statuses.items())),
    }


def _fetch_all(conn: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql)]


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _foreign_key_check(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    return [dict(row) if isinstance(row, sqlite3.Row) else {"row": list(row)} for row in rows]


def _current_area_status(row: dict[str, Any]) -> str:
    for area, key in (("EXPEDICAO", "status_expedicao"), ("GALVANIZACAO", "status_galvanizacao"), ("PRODUCAO", "status_producao"), ("ALMOXARIFADO", "status_almoxarifado"), ("CONTROLE_GERAL", "status_geral")):
        value = str(row.get(key) or "").strip()
        if value:
            return f"{area}:{value}"
    return "SEM_AREA:SEM_STATUS"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mask_path(path: Path | None) -> str | None:
    if path is None:
        return None
    parts = path.resolve().parts
    if len(parts) <= 4:
        return str(path)
    return str(Path(*parts[-4:]))


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m tools.legacy_sqlite_migration.sqlite_real_snapshot")
    parser.add_argument("--source", required=True)
    parser.add_argument("--output-dir", default="reports/snapshots")
    args = parser.parse_args()
    metadata = create_snapshot(Path(args.source), output_dir=Path(args.output_dir))
    print(json.dumps({key: metadata[key] for key in ("snapshot_path", "metadata_path", "size_bytes", "sha256", "integrity_check", "table_count")}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
