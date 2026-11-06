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
    "LOGISTICS_INSPECTION_NOT_FINISHED": "A inspeção dessa proposta ainda não foi finalizada.",
    "LOGISTICS_PROPOSAL_ALREADY_IN_LOG": "Essa proposta já está em outro LOG.",
    "LOGISTICS_ITEM_NOT_FOUND": "Proposta não encontrada neste LOG. Atualize os dados.",
    "LOGISTICS_ITEM_NOT_PENDING": "Essa inclusão já foi resolvida. Os dados foram atualizados.",
    "LOGISTICS_LOG_IN_LOAD": "Este LOG está em uma carga de entrega. Desfaça a carga para remover propostas.",
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
                error = type(error)(message, error_code=error.error_code, technical_message=getattr(error, "technical_message", None))
            raise error from exc
        finally:
            client.close()

    # ---- LOGs ------------------------------------------------------------
    def list_logs(self, *, stage: str | None = None, search: str = "", in_load: bool | None = None, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return self._call(lambda api, token: api.list_logs(token, stage=stage, search=search, in_load=in_load, limit=limit, offset=offset))

    def eligible_proposals(self, *, search: str = "", limit: int = 200, offset: int = 0) -> dict[str, Any]:
        return self._call(lambda api, token: api.eligible_proposals(token, search=search, limit=limit, offset=offset))

    def get_log(self, log_id: int) -> dict[str, Any]:
        return self._call(lambda api, token: api.get_log(token, log_id))

    def create_log(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._call(lambda api, token: api.create_log(token, payload))

    def send_docs(self, log_id: int, nf_link: str, xml_link: str, bim_link: str) -> dict[str, Any]:
        payload = {"nf_link": nf_link, "xml_link": xml_link, "bim_link": bim_link}
        return self._call(lambda api, token: api.log_action(token, log_id, "docs", payload))

    def approve_log(self, log_id: int) -> dict[str, Any]:
        return self._call(lambda api, token: api.log_action(token, log_id, "approve"))

    def add_proposals(self, log_id: int, proposal_ids: list[int]) -> dict[str, Any]:
        return self._call(lambda api, token: api.log_action(token, log_id, "proposals", {"proposal_ids": list(proposal_ids)}))

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

    def create_load(self, departure_date: str, log_ids: list[int]) -> dict[str, Any]:
        return self._call(lambda api, token: api.create_load(token, departure_date=departure_date, log_ids=log_ids))

    def update_load(self, load_id: int, departure_date: str) -> dict[str, Any]:
        return self._call(lambda api, token: api.update_load(token, load_id, departure_date=departure_date))

    def add_log_to_load(self, load_id: int, log_id: int) -> dict[str, Any]:
        return self._call(lambda api, token: api.add_log_to_load(token, load_id, log_id))

    def remove_log_from_load(self, load_id: int, log_id: int) -> dict[str, Any]:
        return self._call(lambda api, token: api.remove_log_from_load(token, load_id, log_id))

    def delete_load(self, load_id: int) -> None:
        self._call(lambda api, token: api.delete_load(token, load_id))
