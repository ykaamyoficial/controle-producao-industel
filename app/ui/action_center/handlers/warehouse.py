from __future__ import annotations

from app.ui.action_center.context import ProposalActionContext
from app.ui.action_center.descriptor import ActionDescriptor
from app.ui.action_center.result import ActionResult


class WarehouseStatusHandler:
    """STATUS no Almoxarifado: precisa/nao precisa de almoxarifado, confirmar
    separacao, confirmar entrega e entrega parcial sao todas transicoes
    simples de proposta - mesmo `service.update_status(process_id,
    "ALMOXARIFADO", status, observation)` que o StatusDialog monolitico
    chamava, sem selecao de itens nem confirmacao adicional (nenhuma delas
    exigia antes). Um unico handler cobre as cinco transicoes conhecidas
    (`next_status_options()`/`process_actions()` decidem quais existem a
    cada momento) em vez de um handler por status.

    Fica aberto e recarrega o contexto apos sucesso (`reload_on_success`),
    igual ao pedido explicito desta fase: o usuario nao deve precisar fechar
    e reabrir a Central para ver o proximo passo do fluxo."""

    def execute(self, context: ProposalActionContext, action: ActionDescriptor, dialog) -> ActionResult:
        status = action.status
        observation = dialog.observation.toPlainText().strip()
        dialog._run_background_action(
            lambda: dialog.service.update_status(context.proposal_id, action.area, status, observation),
            reload_on_success=True,
        )
        return ActionResult(success=True, changed=True, refresh_required=True, close_action_center=False)
