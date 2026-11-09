from __future__ import annotations

from typing import Any, Callable

STAGES = ("pendente", "cadastro", "solicitada", "nqt", "dispensa", "inloco", "doc", "fim")
STAGE_LABELS = {
    "pendente": "Solicitação pendente",
    "cadastro": "Aguardando cadastro do PD",
    "solicitada": "Inspeção solicitada",
    "nqt": "NQT gerado",
    "dispensa": "Dispensada, falta o PIT",
    "inloco": "Inspeção in loco",
    "doc": "Aguardando DOC BIM",
    "fim": "Inspeção finalizada",
    # Linha "A solicitar": proposta marcada que ainda nao tem inspecao (nao e etapa da API).
    "to_request": "A solicitar",
}
LINK_MAX_LENGTH = 500

ERROR_MESSAGES = {
    "INSPECTION_NOT_FOUND": "Inspeção não encontrada. Atualize a lista.",
    "INSPECTION_PD_NOT_FOUND": "Esse PD não existe nas propostas ativas. Confira o número do pedido.",
    "INSPECTION_PROPOSAL_NOT_FOUND": "Não achei proposta ativa com esse número. Confira o número (ex.: CP 05610).",
    "INSPECTION_ALREADY_EXISTS": "Já existe uma inspeção para esse PD.",
    "INSPECTION_NQT_ALREADY_EXISTS": "Esse NQT já está registrado em outro PD.",
    "INSPECTION_INVALID_STAGE": "A inspeção mudou de etapa. Os dados foram atualizados.",
    "PROPOSAL_NOT_FOUND": "Proposta não encontrada. Atualize a lista.",
    "PROPOSAL_CANCELLED_TERMINAL": "A proposta está cancelada e não pode entrar na inspeção.",
    "INSPECTION_PD_DIFFERS_FROM_ORDER": "O PD informado difere do Pedido já preenchido na proposta. Use o PD do Pedido.",
    "INSPECTION_PD_CUSTOMER_CONFLICT": "Esse PD já é Pedido de proposta de outro cliente. Confirme para continuar.",
}


class InspectionService:
    """Camada de servico da Inspecao: fala so com a API (`storage.inspections_api()`
    devolve cliente, API e token) e traduz os erros da API em `AppError`."""

    def __init__(self, storage, wrap_error: Callable[[Exception], Exception]):
        self._storage = storage
        self._wrap_error = wrap_error

    def _call(self, operation: Callable[[Any, str], Any]) -> Any:
        client, api, token = self._storage.inspections_api()
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

    def list_inspections(self, *, stage: str | None = None, search: str = "", limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return self._call(lambda api, token: api.list(token, stage=stage, search=search, limit=limit, offset=offset))

    def get(self, inspection_id: int) -> dict[str, Any]:
        return self._call(lambda api, token: api.get(token, inspection_id))

    def create(self, pd_code: str) -> dict[str, Any]:
        return self._call(lambda api, token: api.create(token, pd_code=pd_code))

    def proposal_lookup(self, number: str) -> dict[str, Any]:
        return self._call(lambda api, token: api.proposal_lookup(token, number))

    def pd_suggestion(self, proposal_id: int) -> dict[str, Any]:
        return self._call(lambda api, token: api.pd_suggestion(token, proposal_id))

    def start_from_proposal(self, proposal_id: int, pd_code: str, confirm_customer_conflict: bool = False) -> dict[str, Any]:
        return self._call(
            lambda api, token: api.from_proposal(
                token,
                proposal_id=proposal_id,
                pd_code=pd_code,
                confirm_customer_conflict=confirm_customer_conflict,
            )
        )

    def transition(self, inspection_id: int, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """`action`: request, register-pd, nqt, decision, pit, approve, reject ou doc. O corpo leva os campos da
        etapa mais `occurred_on`, `note` e (so em `decision`) `confirm_dates`."""
        return self._call(lambda api, token: api.action(token, inspection_id, action, payload or {}))

    def catch_up(self, inspection_id: int, steps: list[dict[str, Any]], confirm_dates: bool = False) -> dict[str, Any]:
        payload = {"steps": steps, **({"confirm_dates": True} if confirm_dates else {})}
        return self._call(lambda api, token: api.catch_up(token, inspection_id, payload))

    def reschedule_visit(self, inspection_id: int, visit_date: str, reason: str, confirm_dates: bool = False) -> dict[str, Any]:
        payload = {"visit_date": visit_date, "reason": reason, **({"confirm_dates": True} if confirm_dates else {})}
        return self._call(lambda api, token: api.reschedule_visit(token, inspection_id, payload))

    def correct_occurred_on(self, inspection_id: int, event_id: int, occurred_on: str, reason: str) -> dict[str, Any]:
        payload = {"occurred_on": occurred_on, "reason": reason}
        return self._call(lambda api, token: api.correct_occurred_on(token, inspection_id, event_id, payload))
