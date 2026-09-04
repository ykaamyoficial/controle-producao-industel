from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import math
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.integrations.api.auth_client import AuthApiClient
from app.integrations.api.client import DesktopApiClient
from app.integrations.api.config import DesktopApiSettings
from app.integrations.api.exceptions import ApiClientError


DEFAULT_BATCH_SIZE = 100


@dataclass(frozen=True)
class SyncReport:
    received: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    rejected: int = 0
    item_created: int = 0
    item_updated: int = 0
    item_unchanged: int = 0


def read_sqlite_snapshot(sqlite_path: Path) -> list[dict[str, Any]]:
    uri = f"file:{quote(str(sqlite_path.resolve()).replace(chr(92), '/'), safe=':/')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN")
        processes = [dict(row) for row in conn.execute("SELECT * FROM processos ORDER BY id")]
        if _table_exists(conn, "proposta_itens"):
            items = [dict(row) for row in conn.execute("SELECT * FROM proposta_itens ORDER BY processo_principal_id, CAST(numero_item AS INTEGER), numero_item, id")]
        else:
            items = []
        conn.execute("COMMIT")
    finally:
        conn.close()
    items_by_process: dict[int, list[dict[str, Any]]] = {}
    for item in items:
        items_by_process.setdefault(int(item["processo_principal_id"]), []).append(item)
    return [map_process(process, items_by_process.get(int(process["id"]), [])) for process in processes]


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)).fetchone() is not None


def map_process(row: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    current_area, current_status = _current_area_status(row)
    proposal = {
        "legacy_id": int(row["id"]),
        "proposal_number": _text(row.get("proposta")),
        "customer_name": _text(row.get("cliente")),
        "project_name": _text(row.get("obra_site")) or None,
        "order_reference": _text(row.get("pedido_compra")) or None,
        "lot": _text(row.get("lote")) or None,
        "proposal_date": _date(row.get("data_entrada") or row.get("data_cadastro")),
        "deadline_date": _date(row.get("prazo_entrega")),
        "current_area": current_area,
        "current_status": current_status,
        "general_status": _text(row.get("status_geral")) or None,
        "production_status": _text(row.get("status_producao")) or None,
        "galvanization_status": _text(row.get("status_galvanizacao")) or None,
        "shipping_status": _text(row.get("status_expedicao")) or None,
        "warehouse_status": _text(row.get("status_almoxarifado")) or None,
        "flow_situation": _text(row.get("situacao_fluxo")) or None,
        "has_production_pending": bool(row.get("tem_pendencia_producao") or False),
        "process_type": _text(row.get("tipo_processo")) or None,
        "parent_legacy_id": int(row["processo_pai_id"]) if row.get("processo_pai_id") else None,
        "partial_number": int(row["numero_parcial"]) if row.get("numero_parcial") is not None else None,
        "is_partial": bool(row.get("processo_pai_id") or int(row.get("numero_parcial") or 0) > 0 or _text(row.get("tipo_processo")).upper() == "PARCIAL"),
        "is_cancelled": _text(row.get("status_geral")).upper() == "CANCELADA",
        "is_completed": _text(row.get("status_geral")).upper() in {"ENTREGUE", "FINALIZADO"},
        "source": "sqlite",
        "legacy_created_at": _datetime(row.get("data_cadastro")),
        "legacy_updated_at": _datetime(row.get("atualizado_em") or row.get("data_cadastro")),
        "items": [map_item(item) for item in items],
    }
    proposal["source_hash"] = source_hash({key: value for key, value in proposal.items() if key not in {"items", "source_hash"}})
    return proposal


def map_item(row: dict[str, Any]) -> dict[str, Any]:
    quantity = _decimal(row.get("quantidade"))
    unit_weight = _decimal(row.get("peso"))
    # O restante do sistema (service.py: rotas de galvanizacao/expedicao/producao)
    # compara esses campos contra "SIM"/"NAO"/"INDEFINIDO" em maiusculo -- o
    # SQLite legado guarda em minusculo, entao normalizamos aqui na origem.
    produce_internally = (_text(row.get("produzir_internamente")) or "indefinido").upper()
    requires_galvanization = (_text(row.get("precisa_galvanizacao")) or "indefinido").upper()
    item = {
        "legacy_id": int(row["id"]),
        "legacy_current_process_id": int(row["processo_atual_id"]) if row.get("processo_atual_id") else None,
        "item_number": _text(row.get("numero_item")),
        "product_code": _text(row.get("codigo_produto")) or None,
        "description": row.get("descricao") if row.get("descricao") is not None else None,
        "quantity": str(quantity),
        "unit": "un",
        "unit_weight": str(unit_weight),
        "total_weight": str((quantity * unit_weight).quantize(Decimal("0.0001"))),
        "produce_internally": produce_internally,
        "requires_galvanization": requires_galvanization,
        # Mesma regra de "fluxo definido" usada pelo restante do sistema
        # (service.py, linha ~3978): so conta como definido quando os dois
        # eixos foram decididos, nao apenas um.
        "flow_defined": produce_internally != "INDEFINIDO" and requires_galvanization != "INDEFINIDO",
        "produced": bool(row.get("produzido") or False),
        "galvanized": bool(row.get("galvanizado") or False),
        "delivered": bool(row.get("entregue") or False),
        "delivered_at": _datetime(row.get("entregue_em")),
        "legacy_created_at": None,
        "legacy_updated_at": _datetime(row.get("atualizado_em")),
    }
    item["source_hash"] = source_hash({key: value for key, value in item.items() if key != "source_hash"})
    return item


def source_hash(payload: dict[str, Any]) -> str:
    normalized = json.dumps(_canonicalize(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonicalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    if isinstance(value, str):
        return value.replace("\r\n", "\n").replace("\r", "\n")
    if isinstance(value, Decimal):
        return str(value)
    return value


def sync(sqlite_path: Path, *, api_url: str, username: str, password: str, dry_run: bool, batch_size: int) -> SyncReport:
    proposals = read_sqlite_snapshot(sqlite_path)
    settings = DesktopApiSettings(enabled=True, base_url=api_url, connect_timeout=3, read_timeout=30)
    client = DesktopApiClient(settings)
    try:
        token = AuthApiClient(client).login(username, password)
        total_batches = max(1, math.ceil(len(proposals) / batch_size))
        report = SyncReport()
        for index in range(0, len(proposals), batch_size):
            batch_number = index // batch_size + 1
            payload = {
                "source_identifier": str(sqlite_path.resolve()),
                "dry_run": dry_run,
                "batch_number": batch_number,
                "batch_total": total_batches,
                "proposals": proposals[index:index + batch_size],
            }
            response = client.post("/api/v1/admin/sync/proposals", json_payload=payload, access_token=token.access_token).data
            report = _merge_report(report, response)
            print(f"Lote {batch_number}/{total_batches}: recebidas={response.get('received')} criadas={response.get('created')} atualizadas={response.get('updated')} sem_alteracao={response.get('unchanged')} rejeitadas={response.get('rejected')}")
        return report
    finally:
        client.close()


def _merge_report(current: SyncReport, response: dict[str, Any]) -> SyncReport:
    return SyncReport(
        received=current.received + int(response.get("received") or 0),
        created=current.created + int(response.get("created") or 0),
        updated=current.updated + int(response.get("updated") or 0),
        unchanged=current.unchanged + int(response.get("unchanged") or 0),
        rejected=current.rejected + int(response.get("rejected") or 0),
        item_created=current.item_created + int(response.get("item_created") or 0),
        item_updated=current.item_updated + int(response.get("item_updated") or 0),
        item_unchanged=current.item_unchanged + int(response.get("item_unchanged") or 0),
    )


def _current_area_status(row: dict[str, Any]) -> tuple[str | None, str | None]:
    for area, key in (("EXPEDICAO", "status_expedicao"), ("GALVANIZACAO", "status_galvanizacao"), ("PRODUCAO", "status_producao"), ("ALMOXARIFADO", "status_almoxarifado"), ("CONTROLE_GERAL", "status_geral")):
        value = _text(row.get(key))
        if value:
            return area, value
    return None, None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0.0000")
    return Decimal(str(value).replace(",", ".")).quantize(Decimal("0.0001"))


def _date(value: Any) -> str | None:
    parsed = _parse_datetime(value)
    return parsed.date().isoformat() if parsed else None


def _datetime(value: Any) -> str | None:
    parsed = _parse_datetime(value)
    return parsed.isoformat() if parsed else None


def _parse_datetime(value: Any) -> datetime | None:
    text_value = _text(value)
    if not text_value:
        return None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text_value, fmt)
            return parsed
        except ValueError:
            continue
    try:
        if len(text_value) == 10:
            return datetime.combine(date.fromisoformat(text_value), datetime.min.time())
        return datetime.fromisoformat(text_value)
    except ValueError:
        return None


def main() -> None:
    if os.environ.get("ALLOW_DEPRECATED_PROPOSAL_SYNC") != "1":
        print(
            "Ferramenta de migracao de dados legados (SQLite -> API). "
            "Requer confirmacao explicita: defina ALLOW_DEPRECATED_PROPOSAL_SYNC=1 "
            "para confirmar que voce quer importar um banco SQLite legado real "
            "para o PostgreSQL oficial via POST /api/v1/admin/sync/proposals.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    parser = argparse.ArgumentParser(prog="python -m tools.legacy_sqlite_migration.proposal_sync")
    parser.add_argument("--sqlite-path", required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", required=True)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    password = getpass.getpass("Senha da API: ")
    try:
        report = sync(Path(args.sqlite_path), api_url=args.api_url, username=args.username, password=password, dry_run=args.dry_run, batch_size=args.batch_size)
    except ApiClientError as exc:
        print(f"Falha: {exc.user_message}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(
        "Resumo: "
        f"recebidas={report.received} criadas={report.created} atualizadas={report.updated} "
        f"sem_alteracao={report.unchanged} rejeitadas={report.rejected} "
        f"itens_criados={report.item_created} itens_atualizados={report.item_updated}"
    )


if __name__ == "__main__":
    main()
