from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QTextEdit, QVBoxLayout

from app.ui.action_center.context import ProposalActionContext
from app.ui.action_center.descriptor import ActionDescriptor
from app.ui.action_center.result import ActionResult
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import style_dialog_from_parent
from app.ui.flow_review_dialog import FlowReviewDialog
from app.ui.icons import AppIcons
from app.ui.item_weight_dialog import ItemWeightDialog
from app.ui.production_registration_dialog import ProductionRegistrationDialog


class ProductionPauseDialog(QDialog):
    """Solicitacao curta e obrigatoria do motivo da interrupcao."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pause_reason = ""
        self.setWindowTitle("Pausar produção")
        self.setMinimumWidth(460)
        style_dialog_from_parent(self, parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)
        title = QLabel("Motivo da pausa")
        title.setStyleSheet("font-size: 15px; font-weight: 800;")
        help_text = QLabel("Informe por que a fabricação será interrompida temporariamente.")
        help_text.setWordWrap(True)
        help_text.setObjectName("Caption")
        self.reason = QTextEdit()
        self.reason.setPlaceholderText("Ex.: Aguardando matéria-prima")
        self.reason.setFixedHeight(88)

        footer = QHBoxLayout()
        footer.addStretch()
        cancel = ModernButton("Cancelar", AppIcons.CLOSE)
        pause = ModernButton("Pausar produção", AppIcons.CIRCLE_PAUSE, accent=True)
        cancel.clicked.connect(self.reject)
        pause.clicked.connect(self._accept_pause)
        footer.addWidget(cancel)
        footer.addWidget(pause)

        root.addWidget(title)
        root.addWidget(help_text)
        root.addWidget(self.reason)
        root.addLayout(footer)
        self.reason.setFocus()

    def _accept_pause(self):
        reason = self.reason.toPlainText().strip()
        if not reason:
            QMessageBox.warning(self, "Pausar produção", "Informe o motivo da pausa.")
            return
        self.pause_reason = reason
        self.accept()


class RegisterProductionHandler:
    """REGISTER_PRODUCTION: se houver itens sem fluxo definido, oferece
    definir o fluxo primeiro; senao abre o registro de producao. Replica
    `StatusDialog._register_production` sem alterar a regra."""

    def execute(self, context: ProposalActionContext, action: ActionDescriptor, dialog) -> ActionResult:
        summary = dialog.service.item_flow_summary(context.proposal_id)
        if summary.get("undefined_count"):
            answer = QMessageBox.question(
                dialog,
                "Fluxo dos itens",
                "Existem itens sem definicao de fluxo. Deseja definir agora antes de registrar a producao?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer == QMessageBox.Yes:
                flow_dialog = FlowReviewDialog(dialog.service, [context.proposal_id], dialog, origin="Producao")
                if flow_dialog.exec():
                    dialog.accept()
                    return ActionResult(success=True, changed=True, refresh_required=True)
            return ActionResult(success=True, changed=False, close_action_center=False)
        registration_dialog = ProductionRegistrationDialog(
            dialog.service,
            [context.proposal_id],
            dialog,
            observation=dialog.observation.toPlainText().strip(),
        )
        if registration_dialog.exec():
            dialog.accept()
            return ActionResult(success=True, changed=True, refresh_required=True)
        return ActionResult(success=True, changed=False, close_action_center=False)


class DefineItemFlowHandler:
    """DEFINE_ITEM_FLOW: abre a revisao de fluxo dos itens."""

    def execute(self, context: ProposalActionContext, action: ActionDescriptor, dialog) -> ActionResult:
        flow_dialog = FlowReviewDialog(dialog.service, [context.proposal_id], dialog, origin="Producao")
        if flow_dialog.exec():
            dialog.accept()
            return ActionResult(success=True, changed=True, refresh_required=True)
        return ActionResult(success=True, changed=False, close_action_center=False)


class EditItemWeightsHandler:
    """EDIT_ITEM_WEIGHTS: abre o cadastro/atualizacao de pesos dos itens."""

    def execute(self, context: ProposalActionContext, action: ActionDescriptor, dialog) -> ActionResult:
        weight_dialog = ItemWeightDialog(dialog.service, context.proposal_id, dialog)
        if weight_dialog.exec():
            dialog.accept()
            return ActionResult(success=True, changed=True, refresh_required=True)
        return ActionResult(success=True, changed=False, close_action_center=False)


class ProductionStatusHandler:
    """STATUS na area de Producao: iniciar/retomar (INICIADO) e pausar
    (PARADO exige motivo via ProductionPauseDialog). Replica o branch STATUS
    de `StatusDialog.run_action` sem alterar a regra ou o endpoint."""

    def execute(self, context: ProposalActionContext, action: ActionDescriptor, dialog) -> ActionResult:
        status = action.status
        observation = dialog.observation.toPlainText().strip()
        if context.area == "PRODUCAO" and status == "PARADO":
            pause_dialog = ProductionPauseDialog(dialog)
            if not pause_dialog.exec():
                return ActionResult(success=True, changed=False, close_action_center=False)
            observation = pause_dialog.pause_reason
            dialog.success_message = "Produção pausada com sucesso."
        elif context.area == "PRODUCAO" and status == "INICIADO" and context.current_status == "PARADO":
            dialog.success_message = "Produção retomada com sucesso."
        dialog._run_background_action(
            lambda: dialog.service.update_status(context.proposal_id, action.area, status, observation)
        )
        return ActionResult(success=True, changed=True, refresh_required=True)
