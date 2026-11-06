from __future__ import annotations

from app.ui.action_center.context import ProposalActionContext
from app.ui.action_center.descriptor import ActionDescriptor
from app.ui.action_center.result import ActionResult
from app.ui.inspection_dialogs import start_inspection_for_proposal


class AddToInspectionHandler:
    """ADD_TO_INSPECTION no Controle Geral: abre o diálogo "Iniciar inspeção" da proposta.
    Quem decide se a ação existe é `process_actions()` (permissões e proposta cancelada);
    o PD e as regras de conflito ficam na API. Uma proposta por vez."""

    def execute(self, context: ProposalActionContext, action: ActionDescriptor, dialog) -> ActionResult:
        label = f"Proposta {context.proposal_number} · {context.client_name or ''}"
        changed = start_inspection_for_proposal(dialog.service, context.proposal_id, dialog, proposal_label=label)
        if changed:
            dialog.accept()
        return ActionResult(success=True, changed=changed, refresh_required=changed, close_action_center=changed)
