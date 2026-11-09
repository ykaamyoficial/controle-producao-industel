from __future__ import annotations

from typing import Any, Callable

LOG_STAGES = ("reservada", "docs", "aprovada")
LOG_STAGE_LABELS = {
    "reservada": "Data reservada",
    "docs": "Documentação enviada",
    "aprovada": "Aprovada para entrega",
}
LINK_MAX_LENGTH = 500

ERROR_MESSAGES = {
    "LOGISTICS_LOG_NOT_FOUND": "LOG não encontrado. Atualize a lista.",
    "LOGISTICS_LOG_CODE_ALREADY_EXISTS": "Esse código LOG já existe.",
    "LOGISTICS_INVALID_STAGE": "O LOG mudou de etapa. Os dados foram atualizados.",
    "LOGISTICS_PROPOSAL_NOT_FOUND": "Proposta não encontrada. Atualize a lista.",
    "LOGISTICS_PROPOSAL_ALREADY_IN_LOG": "Essa proposta já está em outro LOG.",
    "LOGISTICS_ITEM_NOT_FOUND": "Proposta não encontrada neste LOG. Atualize os dados.",
    "LOGISTICS_ITEM_NOT_PENDING": "Essa inclusão já foi resolvida. Os dados foram atualizados.",
    "LOGISTICS_LOAD_NOT_FOUND": "Carga de entrega não encontrada. Atualize a lista.",
    "LOGISTICS_LOG_NOT_APPROVED": "Só LOGs aprovados para entrega entram em uma carga.",
    "LOGISTICS_LOG_ALREADY_IN_LOAD": "Esse LOG já está em outra carga de entrega.",
    "LOGISTICS_LOG_NOT_IN_THIS_LOAD": "Esse LOG não está nesta carga de entrega. Os dados foram atualizados.",
    "LOGISTICS_LOAD_LAST_LOG": "Este é o último LOG da carga. Use \"Desfazer carga\".",
    "VALIDATION_ERROR": "Dados inválidos. Confira os campos e tente novamente.",
    "PERMISSION_DENIED": "Seu usuário não tem permissão para esta operação.",
}

# Erros em que os dados mostrados ficaram velhos: a tela recarrega sozinha.
STALE_ERROR_CODES = frozenset({"LOGISTICS_INVALID_STAGE", "LOGISTICS_ITEM_NOT_PENDING", "LOGISTICS_LOG_NOT_IN_THIS_LOAD"})
INSPECTION_CONFIRMATION_CODE = "LOGISTICS_INSPECTION_CONFIRMATION_REQUIRED"


def inspection_confirmation_proposals(exc: Exception) -> list[dict[str, Any]] | None:
    """Propostas sem DOC BIM do 409 LOGISTICS_INSPECTION_CONFIRMATION_REQUIRED (`proposal_number`, `pd_code`, `inspection_stage`).
    None: não é esse 409. Lista vazia: 409 sem detalhes, mostre a mensagem da API."""
    if getattr(exc, "error_code", None) != INSPECTION_CONFIRMATION_CODE:
        return None
    details = getattr(exc, "details", None)
    proposals = details.get("proposals") if isinstance(details, dict) else None
    return [p for p in proposals or [] if isinstance(p, dict)]


def _flag(name: str, on: bool) -> dict[str, bool]:
    """Campo booleano só vai no corpo quando é True (ausente vale False na API)."""
    return {name: True} if on else {}


def _stage_fields(occurred_on: str | None = None, note: str | None = None, confirm_dates: bool = False) -> dict[str, Any]:
    """Andamento com data real: sem occurred_on a API usa hoje. `occurred_on` em AAAA-MM-DD."""
    return {
        **({"occurred_on": occurred_on} if occurred_on else {}),
        **({"note": note} if note else {}),
        **_flag("confirm_dates", confirm_dates),
    }


class LogisticsService:
    """Camada de servico da Logistica: fala so com a API (`storage.logistics_api()`
    devolve cliente, API e token) e traduz os erros da API em `AppError`."""

    def __init__(self, storage, wrap_error: Callable[[Exception], Exception]):
        self._storage = storage
        self._wrap_error = wrap_error

    def _call(self, operation: Callable[[Any, str], Any]) -> Any:
        client, api, token = self._storage.logistics_api()
        try:
            return operation(api, token)
        except Exception as exc:
            error = self._wrap_error(exc)
            message = ERROR_MESSAGES.get(getattr(error, "error_code", None))
            if message:
                error = type(error)(message, error_code=error.error_code, technical_message=getattr(error, "technical_message", None), details=getattr(error, "details", None))
            raise error from exc
        finally:
            client.close()

    # ---- LOGs ------------------------------------------------------------
    def list_logs(
        self, *, stage: str | None = None, search: str = "", in_load: bool | None = None, state: str | None = None,
        load_id: int | None = None, limit: int = 100, offset: int = 0,
    ) -> dict[str, Any]:
        return self._call(lambda api, token: api.list_logs(token, stage=stage, search=search, in_load=in_load, state=state, load_id=load_id, limit=limit, offset=offset))

    def list_log_states(self) -> list[str]:
        return self._call(lambda api, token: api.list_log_states(token))

    def eligible_proposals(self, *, search: str = "", limit: int = 200, offset: int = 0) -> dict[str, Any]:
        return self._call(lambda api, token: api.eligible_proposals(token, search=search, limit=limit, offset=offset))

    def get_log(self, log_id: int) -> dict[str, Any]:
        return self._call(lambda api, token: api.get_log(token, log_id))

    def create_log(self, payload: dict[str, Any], confirm_inspection: bool = False) -> dict[str, Any]:
        """`confirm_inspection` reenviado depois de um 409 LOGISTICS_INSPECTION_CONFIRMATION_REQUIRED."""
        body = {**payload, **_flag("confirm_inspection", confirm_inspection)}
        return self._call(lambda api, token: api.create_log(token, body))

    def update_log_dates(self, log_id: int, dates: dict[str, str], reason: str, confirm_dates: bool = False) -> dict[str, Any]:
        """`dates`: so as chaves que mudam (requested_date, reserved_date, loading_date, delivery_date), em AAAA-MM-DD."""
        payload = {**dates, "reason": reason, **({"confirm_dates": True} if confirm_dates else {})}
        return self._call(lambda api, token: api.update_log_dates(token, log_id, payload))

    def log_delivery(
        self, log_id: int, delivered_on: str, proof_link: str | None = None, reason: str | None = None,
        note: str | None = None, confirm_dates: bool = False,
    ) -> dict[str, Any]:
        """`proof_link` None nao mexe no comprovante; "" apaga. `delivered_on` é a data da entrega (sem occurred_on)."""
        payload: dict[str, Any] = {"delivered_on": delivered_on, **_stage_fields(note=note, confirm_dates=confirm_dates)}
        if proof_link is not None:
            payload["delivery_proof_link"] = proof_link
        if reason:
            payload["reason"] = reason
        return self._call(lambda api, token: api.log_delivery(token, log_id, payload))

    def send_docs(
        self, log_id: int, nf_link: str, xml_link: str, bim_link: str,
        occurred_on: str | None = None, note: str | None = None, confirm_dates: bool = False,
    ) -> dict[str, Any]:
        payload = {"nf_link": nf_link, "xml_link": xml_link, "bim_link": bim_link, **_stage_fields(occurred_on, note, confirm_dates)}
        return self._call(lambda api, token: api.log_action(token, log_id, "docs", payload))

    def approve_log(self, log_id: int, occurred_on: str | None = None, note: str | None = None, confirm_dates: bool = False) -> dict[str, Any]:
        payload = _stage_fields(occurred_on, note, confirm_dates)
        return self._call(lambda api, token: api.log_action(token, log_id, "approve", payload))

    def add_proposals(self, log_id: int, proposal_ids: list[int], confirm_inspection: bool = False) -> dict[str, Any]:
        """`confirm_inspection` reenviado depois de um 409 LOGISTICS_INSPECTION_CONFIRMATION_REQUIRED."""
        payload = {"proposal_ids": list(proposal_ids), **_flag("confirm_inspection", confirm_inspection)}
        return self._call(lambda api, token: api.log_action(token, log_id, "proposals", payload))

    def resolve_item(self, log_id: int, item_id: int, result: str) -> dict[str, Any]:
        return self._call(lambda api, token: api.log_action(token, log_id, f"items/{int(item_id)}/resolve", {"result": result}))

    def remove_item(self, log_id: int, item_id: int, reason: str) -> dict[str, Any]:
        """Devolve `{log_deleted, log}`; `log_deleted` True quando era a ultima proposta."""
        return self._call(lambda api, token: api.log_action(token, log_id, f"items/{int(item_id)}/remove", {"reason": reason}))

    # ---- cargas de entrega -----------------------------------------------
    def list_loads(self, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return self._call(lambda api, token: api.list_loads(token, limit=limit, offset=offset))

    def get_load(self, load_id: int) -> dict[str, Any]:
        return self._call(lambda api, token: api.get_load(token, load_id))

    def create_load(self, departure_date: str, log_ids: list[int], confirm_dates: bool = False) -> dict[str, Any]:
        return self._call(lambda api, token: api.create_load(token, departure_date=departure_date, log_ids=log_ids, confirm_dates=confirm_dates))

    def update_load(self, load_id: int, departure_date: str, reason: str, confirm_dates: bool = False) -> dict[str, Any]:
        return self._call(lambda api, token: api.update_load(token, load_id, departure_date=departure_date, reason=reason, confirm_dates=confirm_dates))

    def load_departed(self, load_id: int, departed_on: str, reason: str | None = None) -> dict[str, Any]:
        payload = {"departed_on": departed_on, **({"reason": reason} if reason else {})}
        return self._call(lambda api, token: api.load_departed(token, load_id, payload))

    def add_log_to_load(self, load_id: int, log_id: int, confirm_dates: bool = False) -> dict[str, Any]:
        return self._call(lambda api, token: api.add_log_to_load(token, load_id, log_id, confirm_dates))

    def remove_log_from_load(self, load_id: int, log_id: int) -> dict[str, Any]:
        return self._call(lambda api, token: api.remove_log_from_load(token, load_id, log_id))

    def delete_load(self, load_id: int) -> None:
        self._call(lambda api, token: api.delete_load(token, load_id))
