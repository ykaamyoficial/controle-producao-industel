from __future__ import annotations


def complete_production_items(parent, service, rows: list[dict], observation: str) -> tuple[list[dict], list[str]]:
    """Registra producao agrupada por proposta, independentemente de peso."""

    by_proposal: dict[int, list[dict]] = {}
    failures: list[str] = []
    for row in rows:
        if str(row.get("status_producao") or row.get("status_producao_item") or "").strip().upper() == "PARADO":
            failures.append(f"{row.get('proposta')}: a producao esta pausada; retome antes de registrar")
            continue
        proposal_id = row.get("api_proposal_id")
        if proposal_id:
            by_proposal.setdefault(int(proposal_id), []).append(row)
    completed: list[dict] = []
    for proposal_id, proposal_rows in by_proposal.items():
        item_ids = [int(row["api_id"]) for row in proposal_rows]
        try:
            service.update_status(proposal_id, "PRODUCAO", "FINALIZADO", observation, item_ids=item_ids)
            completed.extend(proposal_rows)
        except Exception as exc:
            failures.append(f"{proposal_rows[0].get('proposta')}: {exc}")
    return completed, failures
