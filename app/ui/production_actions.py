from __future__ import annotations

from PySide6.QtWidgets import QInputDialog

from app.ui.components.toast_notification import ToastNotification


def _has_weight(row: dict) -> bool:
    try:
        return float(str(row.get("peso") or "0").replace(",", ".")) > 0
    except ValueError:
        return False


def ensure_item_weights(parent, service, rows: list[dict]) -> bool:
    """Pergunta o peso, em sequencia, de cada item sem peso registrado.
    Devolve False se o usuario cancelar/informar peso invalido em algum."""
    for item in [row for row in rows if not _has_weight(row)]:
        weight, ok = QInputDialog.getDouble(
            parent,
            "Peso produzido",
            f"Peso total produzido para o item {item.get('numero_item')} ({item.get('descricao')}) — proposta {item.get('proposta')}:",
            0.0,
            0.0,
            999999.0,
            4,
        )
        if not ok or weight <= 0:
            ToastNotification(parent.window(), "Operacao cancelada: informe um peso valido para continuar.", "error")
            return False
        try:
            service.update_item_weights(int(item["api_proposal_id"]), {int(item["api_id"]): weight})
            item["peso"] = str(weight)
        except Exception as exc:
            ToastNotification(parent.window(), str(exc), "error")
            return False
    return True


def complete_production_items(parent, service, rows: list[dict], observation: str) -> tuple[list[dict], list[str]]:
    """Registra producao dos itens informados (assume que ja passaram pela
    checagem de peso). Agrupa por proposta pra chamar a API uma vez por
    proposta. Devolve (itens completados com sucesso, falhas)."""
    by_proposal: dict[int, list[dict]] = {}
    for row in rows:
        proposal_id = row.get("api_proposal_id")
        if proposal_id:
            by_proposal.setdefault(int(proposal_id), []).append(row)
    completed: list[dict] = []
    failures: list[str] = []
    for proposal_id, proposal_rows in by_proposal.items():
        item_ids = [int(row["api_id"]) for row in proposal_rows]
        try:
            service.update_status(proposal_id, "PRODUCAO", "FINALIZADO", observation, item_ids=item_ids)
            completed.extend(proposal_rows)
        except Exception as exc:
            failures.append(f"{proposal_rows[0].get('proposta')}: {exc}")
    return completed, failures
