from __future__ import annotations

import argparse
import csv
import getpass
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.integrations.api.auth_client import AuthApiClient
from app.integrations.api.client import DesktopApiClient
from app.integrations.api.config import DesktopApiSettings
from app.integrations.api.exceptions import ApiClientError
from app.integrations.api.proposals_client import ProposalsApiClient
from tools.legacy_sqlite_migration.proposal_sync import read_sqlite_snapshot


KNOWN_AREAS = {"CONTROLE_GERAL", "ALMOXARIFADO", "PRODUCAO", "GALVANIZACAO", "EXPEDICAO"}
DIFF_FIELDS = (
    "proposal_number",
    "customer_name",
    "project_name",
    "order_reference",
    "lot",
    "proposal_date",
    "deadline_date",
    "current_area",
    "current_status",
    "is_partial",
    "is_cancelled",
    "is_completed",
    "source_hash",
)
ITEM_DIFF_FIELDS = (
    "item_number",
    "product_code",
    "description",
    "quantity",
    "unit",
    "unit_weight",
    "total_weight",
    "produce_internally",
    "requires_galvanization",
    "flow_defined",
    "produced",
    "galvanized",
    "delivered",
    "source_hash",
)


@dataclass(frozen=True)
class Difference:
    category: str
    entity: str
    legacy_id: int | None
    proposal_number: str | None
    field: str | None
    sqlite_value: str | None
    postgresql_value: str | None
    severity: str
    recommendation: str


def fetch_api_snapshot(api_url: str, username: str, password: str) -> list[dict[str, Any]]:
    settings = DesktopApiSettings(enabled=True, base_url=api_url, connect_timeout=3, read_timeout=60)
    client = DesktopApiClient(settings)
    try:
        token = AuthApiClient(client).login(username, password)
        proposals_client = ProposalsApiClient(client)
        proposals: list[dict[str, Any]] = []
        offset = 0
        limit = 200
        while True:
            page = proposals_client.list_proposals(token.access_token, limit=limit, offset=offset, sort_by="legacy_updated_at", sort_dir="asc")
            items = page.get("items") or []
            for proposal in items:
                detail = proposals_client.get_proposal(token.access_token, int(proposal["id"]))
                detail["items"] = proposals_client.list_items(token.access_token, int(proposal["id"]))
                proposals.append(detail)
            offset += limit
            if offset >= int(page.get("total") or 0):
                break
        return proposals
    finally:
        client.close()


def build_inventory(sqlite_snapshot: list[dict[str, Any]]) -> dict[str, Any]:
    proposal_ids = [proposal["legacy_id"] for proposal in sqlite_snapshot]
    proposal_numbers = [proposal["proposal_number"] for proposal in sqlite_snapshot]
    all_items = [item for proposal in sqlite_snapshot for item in proposal.get("items", [])]
    item_ids = [item["legacy_id"] for item in all_items]
    areas = sorted({proposal.get("current_area") for proposal in sqlite_snapshot if proposal.get("current_area")})
    statuses = sorted({proposal.get("current_status") for proposal in sqlite_snapshot if proposal.get("current_status")})
    return {
        "total_proposals": len(sqlite_snapshot),
        "total_items": len(all_items),
        "proposals_without_items": sum(1 for proposal in sqlite_snapshot if not proposal.get("items")),
        "duplicate_proposal_legacy_ids": sorted([value for value, count in Counter(proposal_ids).items() if count > 1]),
        "duplicate_item_legacy_ids": sorted([value for value, count in Counter(item_ids).items() if count > 1]),
        "duplicate_proposal_numbers": sorted([value for value, count in Counter(proposal_numbers).items() if value and count > 1]),
        "empty_descriptions": sum(1 for item in all_items if not item.get("description")),
        "multiline_descriptions": sum(1 for item in all_items if "\n" in str(item.get("description") or "")),
        "zero_quantities": sum(1 for item in all_items if str(item.get("quantity")) in {"0", "0.0000"}),
        "negative_quantities": sum(1 for item in all_items if str(item.get("quantity", "0")).startswith("-")),
        "zero_weights": sum(1 for item in all_items if str(item.get("total_weight")) in {"0", "0.0000"}),
        "negative_weights": sum(1 for item in all_items if str(item.get("total_weight", "0")).startswith("-")),
        "areas": areas,
        "statuses": statuses,
        "unknown_areas": sorted(set(areas) - KNOWN_AREAS),
        "cancelled": sum(1 for proposal in sqlite_snapshot if proposal.get("is_cancelled")),
        "completed": sum(1 for proposal in sqlite_snapshot if proposal.get("is_completed")),
        "partial": sum(1 for proposal in sqlite_snapshot if proposal.get("is_partial")),
        "cp00000": sum(1 for proposal in sqlite_snapshot if proposal.get("proposal_number") == "CP00000"),
    }


def compare(sqlite_snapshot: list[dict[str, Any]], api_snapshot: list[dict[str, Any]], *, redact: bool) -> list[Difference]:
    differences: list[Difference] = []
    sqlite_by_id = {proposal["legacy_id"]: proposal for proposal in sqlite_snapshot}
    api_by_id = {proposal["legacy_id"]: proposal for proposal in api_snapshot}

    for legacy_id, proposal in sqlite_by_id.items():
        api_proposal = api_by_id.get(legacy_id)
        if api_proposal is None:
            differences.append(_diff("MISSING_IN_POSTGRESQL", "proposal", legacy_id, proposal, None, None, None, "critical", "Sincronizar novamente e investigar rejeicoes.", redact=redact))
            continue
        _compare_fields(differences, proposal, api_proposal, DIFF_FIELDS, "proposal", redact=redact)
        if proposal.get("current_area") not in (None, "") and proposal.get("current_area") not in KNOWN_AREAS:
            differences.append(_diff("UNKNOWN_AREA", "proposal", legacy_id, proposal, "current_area", proposal.get("current_area"), api_proposal.get("current_area"), "warning", "Preservar valor e revisar classificacao antes de criar regra."))
        sqlite_items = {item["legacy_id"]: item for item in proposal.get("items", [])}
        api_items = {item["legacy_id"]: item for item in api_proposal.get("items", [])}
        if len(sqlite_items) != len(api_items):
            differences.append(_diff("ITEM_COUNT_MISMATCH", "proposal", legacy_id, proposal, "items", len(sqlite_items), len(api_items), "important", "Verificar itens ausentes ou extras.", redact=redact))
        for item_id, item in sqlite_items.items():
            api_item = api_items.get(item_id)
            if api_item is None:
                differences.append(_diff("MISSING_IN_POSTGRESQL", "item", item_id, proposal, None, None, None, "critical", "Sincronizar novamente e verificar associacao do item.", redact=redact))
                continue
            _compare_fields(differences, item, api_item, ITEM_DIFF_FIELDS, "item", proposal=proposal, redact=redact)
        for item_id in sorted(set(api_items) - set(sqlite_items)):
            differences.append(_diff("MISSING_IN_SQLITE", "item", item_id, proposal, None, None, None, "critical", "Investigar registro extra na replica.", redact=redact))

    for legacy_id, proposal in api_by_id.items():
        if legacy_id not in sqlite_by_id:
            differences.append(_diff("MISSING_IN_SQLITE", "proposal", legacy_id, proposal, None, None, None, "critical", "Registro existe apenas na replica; confirmar politica de exclusao.", redact=redact))

    seen_proposals = Counter(proposal["legacy_id"] for proposal in sqlite_snapshot)
    for legacy_id, count in seen_proposals.items():
        if count > 1:
            differences.append(Difference("DUPLICATE_LEGACY_ID", "proposal", legacy_id, None, "legacy_id", str(count), None, "critical", "Corrigir duplicidade na fonte antes de confiar na replica."))
    return differences


def _compare_fields(differences: list[Difference], sqlite_obj: dict[str, Any], api_obj: dict[str, Any], fields: tuple[str, ...], entity: str, *, proposal: dict[str, Any] | None = None, redact: bool) -> None:
    proposal_ref = proposal or sqlite_obj
    for field in fields:
        left = _normalize(sqlite_obj.get(field))
        right = _normalize(api_obj.get(field))
        if left == right:
            continue
        category = "HASH_MISMATCH" if field == "source_hash" else "FIELD_MISMATCH"
        severity = "critical" if field in {"quantity", "current_area", "current_status", "source_hash"} else "important"
        differences.append(_diff(category, entity, sqlite_obj.get("legacy_id"), proposal_ref, field, left, right, severity, "Revisar mapeamento, normalizacao ou sincronizar novamente.", redact=redact))


def _diff(category: str, entity: str, legacy_id: int | None, proposal: dict[str, Any] | None, field: str | None, sqlite_value: Any, postgresql_value: Any, severity: str, recommendation: str, *, redact: bool = False) -> Difference:
    proposal_number = proposal.get("proposal_number") if proposal else None
    return Difference(
        category=category,
        entity=entity,
        legacy_id=legacy_id,
        proposal_number=None if redact else proposal_number,
        field=field,
        sqlite_value=_safe_value(sqlite_value, redact),
        postgresql_value=_safe_value(postgresql_value, redact),
        severity=severity,
        recommendation=recommendation,
    )


def _normalize(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).replace("\r\n", "\n").strip()


def _safe_value(value: Any, redact: bool) -> str | None:
    normalized = _normalize(value)
    if normalized is None:
        return None
    if redact and len(normalized) > 8:
        return f"<redacted:{len(normalized)}>"
    return normalized[:240]


def write_reports(differences: list[Difference], inventory: dict[str, Any], *, reports_dir: Path) -> dict[str, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = reports_dir / f"proposals_replica_validation_{stamp}.json"
    csv_path = reports_dir / f"proposals_replica_validation_{stamp}.csv"
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "inventory": inventory,
        "summary": summarize(differences, inventory),
        "differences": [asdict(diff) for diff in differences],
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(Difference("", "", None, None, None, None, None, "", "")).keys()))
        writer.writeheader()
        writer.writerows(asdict(diff) for diff in differences)
    return {"json": json_path, "csv": csv_path}


def summarize(differences: list[Difference], inventory: dict[str, Any]) -> dict[str, Any]:
    severity = Counter(diff.severity for diff in differences)
    category = Counter(diff.category for diff in differences)
    return {
        "total_sqlite": inventory["total_proposals"],
        "total_sqlite_items": inventory["total_items"],
        "divergent": len(differences),
        "critical": severity.get("critical", 0),
        "important": severity.get("important", 0),
        "warning": severity.get("warning", 0),
        "categories": dict(sorted(category.items())),
    }


def validate(sqlite_path: Path, *, api_url: str, username: str, password: str, reports_dir: Path, redact: bool) -> tuple[dict[str, Any], dict[str, Path]]:
    sqlite_snapshot = read_sqlite_snapshot(sqlite_path)
    api_snapshot = fetch_api_snapshot(api_url, username, password)
    inventory = build_inventory(sqlite_snapshot)
    differences = compare(sqlite_snapshot, api_snapshot, redact=redact)
    paths = write_reports(differences, inventory, reports_dir=reports_dir)
    return summarize(differences, inventory), paths


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m tools.legacy_sqlite_migration.validate_proposals_replica")
    parser.add_argument("--sqlite-path", required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", required=True)
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--redact", action="store_true")
    args = parser.parse_args()
    password = getpass.getpass("Senha da API: ")
    try:
        summary, paths = validate(Path(args.sqlite_path), api_url=args.api_url, username=args.username, password=password, reports_dir=Path(args.reports_dir), redact=args.redact)
    except ApiClientError as exc:
        print(f"Falha: {exc.user_message}")
        raise SystemExit(1) from exc
    print(f"Total SQLite: {summary['total_sqlite']}")
    print(f"Total itens SQLite: {summary['total_sqlite_items']}")
    print(f"Divergentes: {summary['divergent']}")
    print(f"Criticos: {summary['critical']}")
    print(f"Importantes: {summary['important']}")
    print(f"Avisos: {summary['warning']}")
    print(f"JSON: {paths['json']}")
    print(f"CSV: {paths['csv']}")


if __name__ == "__main__":
    main()
