from __future__ import annotations

import argparse
import getpass
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.integrations.api.auth_client import AuthApiClient
from app.integrations.api.client import DesktopApiClient
from app.integrations.api.config import DesktopApiSettings
from app.integrations.api.exceptions import ApiClientError
from tools.legacy_sqlite_migration.proposal_sync import _date, _datetime, _decimal, _text, source_hash


DEFAULT_BATCH_SIZE = 100

AREA_PERMISSION_MAP: dict[str, dict[str, list[str]]] = {
    "control_general": {"VIEW": ["proposals.view"], "EDIT": ["proposals.view", "proposals.create", "proposals.update", "proposals.change_status"]},
    "production": {"VIEW": ["production.view"], "EDIT": ["production.view", "production.update"]},
    "galvanization": {"VIEW": ["galvanization.view"], "EDIT": ["galvanization.view", "galvanization.update"]},
    "expedition": {"VIEW": ["expedition.view"], "EDIT": ["expedition.view", "expedition.update"]},
    "fiscal": {"VIEW": ["fiscal.view"], "EDIT": ["fiscal.view", "fiscal.register_emission"]},
    "users_permissions": {"VIEW": ["users.view"], "EDIT": ["users.view", "users.manage_permissions", "roles.view"]},
    "history": {"VIEW": ["audit.view"], "EDIT": ["audit.view"]},
}


def _connect_ro(sqlite_path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(sqlite_path.resolve()).replace(chr(92), '/'), safe=':/')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)).fetchone() is not None


def read_users_snapshot(sqlite_path: Path) -> list[dict[str, Any]]:
    conn = _connect_ro(sqlite_path)
    try:
        users = [dict(row) for row in conn.execute("SELECT * FROM usuarios ORDER BY id")]
        permissions = [dict(row) for row in conn.execute("SELECT * FROM usuario_permissoes ORDER BY usuario_id")]
    finally:
        conn.close()
    permissions_by_user: dict[int, list[dict[str, Any]]] = {}
    for perm in permissions:
        permissions_by_user.setdefault(int(perm["usuario_id"]), []).append(perm)
    payloads = []
    for user in users:
        if _text(user.get("login")).lower() == "admin":
            continue
        payloads.append(map_user(user, permissions_by_user.get(int(user["id"]), [])))
    return payloads


def map_user(row: dict[str, Any], permissions: list[dict[str, Any]]) -> dict[str, Any]:
    codes: set[str] = set()
    for perm in permissions:
        area = _text(perm.get("area_key"))
        level = _text(perm.get("access_level")).upper()
        codes.update(AREA_PERMISSION_MAP.get(area, {}).get(level, []))
    payload = {
        "legacy_id": int(row["id"]),
        "username": _text(row.get("login")),
        "display_name": _text(row.get("nome")) or _text(row.get("login")),
        "active": bool(row.get("ativo") if row.get("ativo") is not None else True),
        "is_superuser": _text(row.get("perfil")).lower() == "admin",
        "permission_codes": sorted(codes),
    }
    payload["source_hash"] = source_hash({key: value for key, value in payload.items() if key != "source_hash"})
    return payload


def read_galvanization_snapshot(sqlite_path: Path) -> list[dict[str, Any]]:
    conn = _connect_ro(sqlite_path)
    try:
        loads = [dict(row) for row in conn.execute("SELECT * FROM cargas_galvanizacao ORDER BY id")]
        items = [dict(row) for row in conn.execute("SELECT * FROM cargas_galvanizacao_item_detalhes ORDER BY carga_id, id")]
    finally:
        conn.close()
    items_by_load: dict[int, list[dict[str, Any]]] = {}
    for item in items:
        items_by_load.setdefault(int(item["carga_id"]), []).append(item)
    return [map_galvanization_load(load, items_by_load.get(int(load["id"]), [])) for load in loads]


def map_galvanization_load(row: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {
        "legacy_id": int(row["id"]),
        "driver_name": _text(row.get("motorista")) or "Nao informado",
        "max_weight": str(_decimal(row.get("peso_maximo"))) if row.get("peso_maximo") is not None else None,
        "total_weight": str(_decimal(row.get("peso_total"))),
        "status": _text(row.get("status")) or "AGUARDANDO_LIBERACAO",
        "expected_return_date": _date(row.get("data_prevista_retorno")),
        "sent_at": _datetime(row.get("criado_em")),
        "returned_at": _datetime(row.get("data_retorno")),
        "closed_at": _datetime(row.get("data_retorno")) if _text(row.get("status")) == "RETORNADA_GALVANIZACAO" else None,
        "notes": row.get("observacao") or None,
        "items": [map_galvanization_item(item) for item in items],
    }
    payload["source_hash"] = source_hash({key: value for key, value in payload.items() if key not in {"items", "source_hash"}})
    return payload


def map_galvanization_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "proposal_item_legacy_id": int(row["proposta_item_id"]),
        "sent_quantity": str(_decimal(row.get("quantidade_enviada"))),
        "returned_quantity": str(_decimal(row.get("quantidade_retornada"))),
        "unit_weight": str(_decimal(row.get("peso_unitario"))) if row.get("peso_unitario") is not None else None,
        "sent_weight": str(_decimal(row.get("peso_enviado"))) if row.get("peso_enviado") is not None else None,
        "returned_weight": str(_decimal(row.get("peso_retornado"))) if row.get("peso_retornado") is not None else None,
        "status": _text(row.get("status_retorno")) or "AGUARDANDO_RETORNO",
        "returned_at": _datetime(row.get("atualizado_em")),
    }


def read_fiscal_snapshot(sqlite_path: Path) -> list[dict[str, Any]]:
    conn = _connect_ro(sqlite_path)
    try:
        records = [dict(row) for row in conn.execute("SELECT * FROM fiscal_processos ORDER BY id")]
        items = [dict(row) for row in conn.execute("SELECT * FROM fiscal_itens ORDER BY fiscal_processo_id, id")]
        emissions = [dict(row) for row in conn.execute("SELECT * FROM fiscal_emissoes ORDER BY fiscal_processo_id, id")]
        emission_items = [dict(row) for row in conn.execute("SELECT * FROM fiscal_emissao_itens ORDER BY fiscal_emissao_id, id")]
    finally:
        conn.close()
    items_by_record: dict[int, list[dict[str, Any]]] = {}
    for item in items:
        items_by_record.setdefault(int(item["fiscal_processo_id"]), []).append(item)
    emission_items_by_emission: dict[int, list[dict[str, Any]]] = {}
    for line in emission_items:
        emission_items_by_emission.setdefault(int(line["fiscal_emissao_id"]), []).append(line)
    emissions_by_record: dict[int, list[dict[str, Any]]] = {}
    for emission in emissions:
        emissions_by_record.setdefault(int(emission["fiscal_processo_id"]), []).append(emission)
    return [
        map_fiscal_record(
            record,
            items_by_record.get(int(record["id"]), []),
            emissions_by_record.get(int(record["id"]), []),
            emission_items_by_emission,
            items_by_record.get(int(record["id"]), []),
        )
        for record in records
    ]


def map_fiscal_record(
    row: dict[str, Any],
    items: list[dict[str, Any]],
    emissions: list[dict[str, Any]],
    emission_items_by_emission: dict[int, list[dict[str, Any]]],
    record_items: list[dict[str, Any]],
) -> dict[str, Any]:
    item_id_to_proposal_item_legacy_id = {int(item["id"]): int(item["item_id"]) for item in record_items}
    payload = {
        "legacy_id": int(row["id"]),
        "proposal_legacy_id": int(row["processo_id"]),
        "status_fiscal": _text(row.get("status_fiscal")) or "FALTA_EMITIR_NOTA_FISCAL",
        "fiscal_situation": _text(row.get("situacao_fiscal")) or "AGUARDANDO_NF",
        "entry_date": _date(row.get("data_entrada_fiscal")) or _date(row.get("data_ultima_emissao")) or "2026-01-01",
        "last_emission_at": _datetime(row.get("data_ultima_emissao")),
        "invoice_withdrawn_at": _datetime(row.get("data_retirada_nf")),
        "withdrawal_observation": row.get("observacao_retirada_nf") or None,
        "observation": row.get("observacao") or None,
        "items": [map_fiscal_item(item) for item in items],
        "invoices": [map_fiscal_invoice(emission, emission_items_by_emission.get(int(emission["id"]), []), item_id_to_proposal_item_legacy_id) for emission in emissions],
    }
    payload["source_hash"] = source_hash({key: value for key, value in payload.items() if key not in {"items", "invoices", "source_hash"}})
    return payload


def map_fiscal_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "proposal_item_legacy_id": int(row["item_id"]),
        "total_quantity": str(_decimal(row.get("quantidade_total"))),
        "billed_quantity": str(_decimal(row.get("quantidade_faturada"))),
        "total_weight": str(_decimal(row.get("peso_total"))) if row.get("peso_total") is not None else None,
        "billed_weight": str(_decimal(row.get("peso_faturado"))),
        "status": _text(row.get("status_item_fiscal")) or "PENDENTE",
    }


def map_fiscal_invoice(row: dict[str, Any], lines: list[dict[str, Any]], item_id_to_proposal_item_legacy_id: dict[int, int]) -> dict[str, Any]:
    invoice_items = []
    for line in lines:
        proposal_item_legacy_id = item_id_to_proposal_item_legacy_id.get(int(line["item_id"]))
        if proposal_item_legacy_id is None:
            continue
        invoice_items.append(
            {
                "proposal_item_legacy_id": proposal_item_legacy_id,
                "quantity": str(_decimal(line.get("quantidade_emitida"))),
                "weight": str(_decimal(line.get("peso_emitido"))) if line.get("peso_emitido") is not None else None,
            }
        )
    return {
        "legacy_id": int(row["id"]),
        "invoice_number": _text(row.get("numero_controle")) or f"LEGADO{row['id']}",
        "series": None,
        "issued_at": _datetime(row.get("data_emissao")) or "2026-01-01T00:00:00",
        "emission_type": _text(row.get("tipo_emissao")) or "PARCIAL",
        "observation": row.get("observacao") or None,
        "source": "MANUAL",
        "items": invoice_items,
    }


def _login(client: DesktopApiClient, username: str, password: str) -> str:
    return AuthApiClient(client).login(username, password).access_token


def _send_batches(client: DesktopApiClient, token: str, path: str, *, list_key: str, source_identifier: str, records: list[dict[str, Any]], dry_run: bool, batch_size: int, extra_fields: dict[str, Any] | None = None) -> None:
    total_batches = max(1, (len(records) + batch_size - 1) // batch_size)
    for index in range(0, len(records), batch_size):
        batch_number = index // batch_size + 1
        payload = {
            "source_identifier": source_identifier,
            "dry_run": dry_run,
            "batch_number": batch_number,
            "batch_total": total_batches,
            list_key: records[index:index + batch_size],
        }
        if extra_fields:
            payload.update(extra_fields)
        response = client.post(path, json_payload=payload, access_token=token).data
        print(
            f"{path} lote {batch_number}/{total_batches}: recebidos={response.get('received')} "
            f"criados={response.get('created')} atualizados={response.get('updated')} "
            f"sem_alteracao={response.get('unchanged')} rejeitados={response.get('rejected')} "
            f"itens_criados={response.get('item_created')} itens_atualizados={response.get('item_updated')}"
        )
        if response.get("errors"):
            for error in response["errors"]:
                print(f"  erro: {error}")


def run(
    sqlite_path: Path,
    *,
    api_url: str,
    username: str,
    password: str,
    default_password: str,
    dry_run: bool,
    batch_size: int,
    skip_users: bool,
    skip_galvanization: bool,
    skip_fiscal: bool,
    skip_expedition: bool,
) -> None:
    settings = DesktopApiSettings(enabled=True, base_url=api_url, connect_timeout=3, read_timeout=60)
    client = DesktopApiClient(settings)
    try:
        token = _login(client, username, password)
        source_identifier = str(sqlite_path.resolve())

        if not skip_users:
            users = read_users_snapshot(sqlite_path)
            _send_batches(client, token, "/api/v1/users/admin/sync", list_key="users", source_identifier=source_identifier, records=users, dry_run=dry_run, batch_size=batch_size, extra_fields={"default_password": default_password})

        if not skip_galvanization:
            loads = read_galvanization_snapshot(sqlite_path)
            _send_batches(client, token, "/api/v1/admin/sync/galvanization", list_key="loads", source_identifier=source_identifier, records=loads, dry_run=dry_run, batch_size=batch_size)

        if not skip_fiscal:
            records = read_fiscal_snapshot(sqlite_path)
            _send_batches(client, token, "/api/v1/admin/sync/fiscal", list_key="records", source_identifier=source_identifier, records=records, dry_run=dry_run, batch_size=batch_size)

        if not skip_expedition and not dry_run:
            response = client.post("/api/v1/admin/sync/expedition-backfill", json_payload={}, access_token=token).data
            print(f"/api/v1/admin/sync/expedition-backfill: recebidos={response.get('received')} criados={response.get('created')} sem_alteracao={response.get('unchanged')}")
    finally:
        client.close()


def main() -> None:
    if os.environ.get("ALLOW_DEPRECATED_PROPOSAL_SYNC") != "1":
        print(
            "Ferramenta de migracao de dados legados (SQLite -> API). "
            "Requer confirmacao explicita: defina ALLOW_DEPRECATED_PROPOSAL_SYNC=1 "
            "para confirmar que voce quer importar um banco SQLite legado real "
            "(usuarios, galvanizacao, fiscal, expedicao) para o PostgreSQL oficial.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    parser = argparse.ArgumentParser(prog="python -m tools.legacy_sqlite_migration.full_sync")
    parser.add_argument("--sqlite-path", required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", required=True)
    parser.add_argument("--default-password", default="2026", help="Senha temporaria atribuida aos usuarios importados (password_must_change=True).")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-users", action="store_true")
    parser.add_argument("--skip-galvanization", action="store_true")
    parser.add_argument("--skip-fiscal", action="store_true")
    parser.add_argument("--skip-expedition", action="store_true")
    args = parser.parse_args()
    password = getpass.getpass("Senha da API: ")
    try:
        run(
            Path(args.sqlite_path),
            api_url=args.api_url,
            username=args.username,
            password=password,
            default_password=args.default_password,
            dry_run=args.dry_run,
            batch_size=args.batch_size,
            skip_users=args.skip_users,
            skip_galvanization=args.skip_galvanization,
            skip_fiscal=args.skip_fiscal,
            skip_expedition=args.skip_expedition,
        )
    except ApiClientError as exc:
        print(f"Falha: {exc.user_message}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
