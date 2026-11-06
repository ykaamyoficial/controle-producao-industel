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

    def request(self, inspection_id: int, pd_registered: bool) -> dict[str, Any]:
        return self._call(lambda api, token: api.action(token, inspection_id, "request", {"pd_registered": bool(pd_registered)}))

    def register_pd(self, inspection_id: int) -> dict[str, Any]:
        return self._call(lambda api, token: api.action(token, inspection_id, "register-pd"))

    def register_nqt(self, inspection_id: int, nqt_code: str) -> dict[str, Any]:
        return self._call(lambda api, token: api.action(token, inspection_id, "nqt", {"nqt_code": nqt_code}))

    def decide(self, inspection_id: int, decision: str, visit_date: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"decision": decision}
        if visit_date:
            payload["visit_date"] = visit_date
        return self._call(lambda api, token: api.action(token, inspection_id, "decision", payload))

    def register_pit(self, inspection_id: int, pit_link: str) -> dict[str, Any]:
        return self._call(lambda api, token: api.action(token, inspection_id, "pit", {"pit_link": pit_link}))

    def approve(self, inspection_id: int) -> dict[str, Any]:
        return self._call(lambda api, token: api.action(token, inspection_id, "approve"))

    def reject(self, inspection_id: int, reason: str) -> dict[str, Any]:
        return self._call(lambda api, token: api.action(token, inspection_id, "reject", {"reason": reason}))

    def register_doc(self, inspection_id: int, doc_link: str) -> dict[str, Any]:
        return self._call(lambda api, token: api.action(token, inspection_id, "doc", {"doc_link": doc_link}))
