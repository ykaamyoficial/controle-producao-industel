from __future__ import annotations

from uuid import uuid4

from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QMessageBox, QTextEdit, QVBoxLayout,
)

from app.ui.action_center.handlers.control_general import ControlGeneralStatusHandler
from app.ui.action_center.handlers.expedition import ExpeditionStatusHandler, RegisterDeliveryHandler
from app.ui.action_center.handlers.galvanization import (
    ManageGalvanizationLoadExistingHandler, ManageGalvanizationLoadNewHandler, OpenRelatedGalvanizationLoadHandler,
    register_galvanization_return_legacy,
)
from app.ui.action_center.handlers.legacy import LegacyActionHandler
from app.ui.action_center.handlers.production import (
    DefineItemFlowHandler, EditItemWeightsHandler, ProductionPauseDialog, ProductionStatusHandler,
    RegisterProductionHandler,
)
from app.ui.action_center.handlers.warehouse import WarehouseStatusHandler
from app.ui.action_center.provider import (
    CATEGORY_TO_CARD_TYPE, GalvanizationActionProvider, action_category, action_description, action_icon,
    primary_action_index,
)
from app.ui.action_center.proposal_action_center import ProposalActionCenter
from app.ui.action_center.registry import ActionRegistry
from app.ui.components.modern_button import ModernButton

# Re-exported for backwards compatibility: callers/tests that imported
# ProductionPauseDialog from this module keep working - the dialog itself
# now lives with the production handler that opens it
# (app/ui/action_center/handlers/production.py).
__all__ = ["ManualStatusDialog", "ProductionPauseDialog", "StatusDialog", "open_proposal_action_center"]


def open_proposal_action_center(service, process_id: int, parent, area: str | None = None, row_context: dict | None = None) -> "StatusDialog":
    """Ponto unico de abertura da Central de Acoes por proposal_id (Fase 8,
    secao 6) - botao "Acoes", menu contextual, atalho de tabela e o botao
    "Acoes" de `ProcessDetailDialog` convergem todos para esta funcao em vez
    de cada um resolver a area e instanciar `StatusDialog` por conta propria.

    `area` e a area preferida de quem esta chamando (ex.: a area da pagina
    atual) - so e usada se estiver entre as areas visiveis ao usuario
    corrente; caso contrario (incluindo area=None, o caso de
    `ProcessDetailDialog`, que nao sabe de antemao em qual area a proposta
    esta) a area real e resolvida pelo proprio `ProposalActionCenter` via
    `service.current_location()`, exatamente como antes desta fase - nenhum
    comportamento mudou, so o local onde a checagem `in visible_areas()`
    vive deixou de estar duplicado."""
    resolved_area = area if area in service.visible_areas() else None
    return StatusDialog(service, process_id, resolved_area, parent, row_context=row_context)


class StatusDialog(ProposalActionCenter):
    """Instancia de Producao da Central de Acoes (`ProposalActionCenter`):
    apresentacao + descoberta ficam na classe base; aqui so registramos os
    handlers de dominio e a camada de compatibilidade (`LegacyActionHandler`)
    para as acoes de Galvanizacao que esta fase ainda nao migra."""

    def __init__(self, service, process_id: int, area: str | None, parent=None, row_context: dict | None = None):
        provider = GalvanizationActionProvider(service)
        registry = self._build_registry()
        super().__init__(service, process_id, area, provider, registry, parent, row_context=row_context)

    @staticmethod
    def _build_registry() -> ActionRegistry:
        registry = ActionRegistry()
        registry.register("REGISTER_PRODUCTION", RegisterProductionHandler())
        registry.register("DEFINE_ITEM_FLOW", DefineItemFlowHandler())
        registry.register("EDIT_ITEM_WEIGHTS", EditItemWeightsHandler())
        registry.register("STATUS", ProductionStatusHandler(), area="PRODUCAO")
        registry.register("STATUS", ControlGeneralStatusHandler(), area="CONTROLE GERAL")
        registry.register("STATUS", WarehouseStatusHandler(), area="ALMOXARIFADO")
        registry.register("STATUS", ExpeditionStatusHandler(), area="EXPEDICAO")
        registry.register("REGISTER_DELIVERY", RegisterDeliveryHandler())
        # MANAGE_LOAD chega do backend como uma unica acao, mas
        # GalvanizationActionProvider ja a divide em dois descriptors de UI
        # antes de renderizar os cards (Fase 8) - cada um com handler proprio.
        registry.register(
            "MANAGE_LOAD_EXISTING", ManageGalvanizationLoadExistingHandler(), area="GALVANIZACAO"
        )
        registry.register("MANAGE_LOAD_NEW", ManageGalvanizationLoadNewHandler(), area="GALVANIZACAO")
        # REGISTER_GALVANIZATION_RETURN continua no LegacyActionHandler de proposito
        # (Fase 6, secoes 21-25): o fluxo preferencial passa a ser navegar ate a carga
        # e registrar o retorno por la (OPEN_RELATED_GALVANIZATION_LOAD abaixo); a
        # entrada direta so sera desativada apos essa navegacao estar comprovada.
        registry.register("REGISTER_GALVANIZATION_RETURN", LegacyActionHandler(register_galvanization_return_legacy))
        registry.register(
            "OPEN_RELATED_GALVANIZATION_LOAD", OpenRelatedGalvanizationLoadHandler(), area="GALVANIZACAO"
        )
        return registry

    # Pure presentation-mapping helpers kept here as thin delegates so
    # existing call sites/tests that use them as StatusDialog staticmethods
    # keep working - the single source of truth is
    # app/ui/action_center/provider.py.
    @staticmethod
    def _primary_action_index(actions: list[dict[str, str]]) -> int:
        return primary_action_index(actions)

    @staticmethod
    def _action_type(action: dict[str, str], index: int, primary_index: int) -> str:
        return CATEGORY_TO_CARD_TYPE[action_category(action, index, primary_index)]

    @staticmethod
    def _action_icon(action: dict[str, str]):
        return action_icon(action)

    @staticmethod
    def _action_description(action: dict[str, str]) -> str:
        return action_description(action)


class ManualStatusDialog(QDialog):
    """Administrative state repair driven exclusively by API-calculated options."""

    def __init__(self, service, process_id: int, area: str | None, parent=None):
        super().__init__(parent)
        self.service = service
        self.process_id = process_id
        self.idempotency_key = str(uuid4())
        self.options_response = service.administrative_correction_options(process_id)
        self.expected_version = int(self.options_response.get("version") or 0)
        self.current_state = self.options_response.get("current_state") or {}
        self.preview: dict | None = None
        self.setWindowTitle("Correcao administrativa")
        self.setMinimumWidth(720)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(12)
        warning = QLabel(
            "Esta e uma operacao administrativa auditada. Use somente para corrigir "
            "uma projecao incompativel com os fatos reais do processo."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("font-weight: 700;")

        current_frame = QFrame()
        current_frame.setObjectName("Card")
        current_layout = QFormLayout(current_frame)
        current_layout.setContentsMargins(14, 12, 14, 12)
        current_layout.setSpacing(8)
        current_layout.addRow("Area atual", QLabel(self._display(self.current_state.get("current_area"))))
        current_layout.addRow("Status atual", QLabel(self._display(self.current_state.get("current_status"))))
        current_layout.addRow("Producao", QLabel(self._display(self.current_state.get("production_status"))))
        current_layout.addRow("Galvanizacao", QLabel(self._display(self.current_state.get("galvanization_status"))))
        current_layout.addRow("Expedicao", QLabel(self._display(self.current_state.get("shipping_status"))))
        current_layout.addRow("Fiscal", QLabel(self._display(self.current_state.get("fiscal_status"))))

        self.option_combo = QComboBox()
        for option in self.options_response.get("options") or []:
            self.option_combo.addItem(option.get("label") or "Correcao compativel", option)
        if self.option_combo.count() == 0:
            self.option_combo.addItem("Nenhuma correcao de estado compativel", None)
            self.option_combo.setEnabled(False)

        self.impact = QTextEdit()
        self.impact.setReadOnly(True)
        self.impact.setMinimumHeight(210)
        self.reason = QTextEdit()
        self.reason.setPlaceholderText("Motivo obrigatorio da inconsistencia e da correcao")
        self.reason.setMinimumHeight(94)
        self.save_button = ModernButton("Aplicar correcao", "status", accent=True)
        cancel = ModernButton("Cancelar", "clear")
        self.save_button.clicked.connect(self.save)
        cancel.clicked.connect(self.reject)
        self.option_combo.currentIndexChanged.connect(self.load_preview)
        root.addWidget(warning)
        root.addWidget(current_frame)
        root.addWidget(QLabel("Estado desejado (opcoes calculadas pela API)"))
        root.addWidget(self.option_combo)
        root.addWidget(QLabel("Impacto da correcao"))
        root.addWidget(self.impact)
        root.addWidget(QLabel("Motivo"))
        root.addWidget(self.reason)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(cancel)
        footer.addWidget(self.save_button)
        root.addLayout(footer)
        self.load_preview()

    @staticmethod
    def _display(value) -> str:
        return str(value or "-").replace("_", " ").title()

    def load_preview(self):
        option = self.option_combo.currentData()
        self.preview = None
        self.save_button.setEnabled(False)
        if not option:
            warnings = self.options_response.get("warnings") or []
            self.impact.setPlainText("\n".join(warnings) or "Nao existe correcao de estado disponivel.")
            return
        try:
            self.preview = self.service.preview_administrative_correction(
                self.process_id,
                self.expected_version,
                option.get("target_area"),
                option.get("target_status"),
            )
        except Exception as exc:
            self.impact.setPlainText(str(exc))
            return

        lines = ["O que sera alterado:"]
        changes = self.preview.get("changes") or []
        if changes:
            lines.extend(
                f"- {row.get('field')}: {row.get('before') or '-'} -> {row.get('after') or '-'}"
                for row in changes
            )
        else:
            lines.append("- Nenhum campo de projecao.")
        lines.extend(["", "O que NAO sera alterado:"])
        lines.extend(f"- {field}" for field in (self.preview.get("unchanged_fields") or [])[:12])
        blockers = self.preview.get("blockers") or []
        if blockers:
            lines.extend(["", "Bloqueadores:"])
            lines.extend(f"- {row.get('message')}" for row in blockers)
        effects = self.preview.get("effects") or []
        if effects:
            lines.extend(["", "Efeitos:"])
            lines.extend(f"- {effect}" for effect in effects)
        self.impact.setPlainText("\n".join(lines))
        self.save_button.setEnabled(bool(self.preview.get("allowed")))

    def save(self):
        reason = self.reason.toPlainText().strip()
        if not reason:
            QMessageBox.warning(self, "Correcao administrativa", "Informe o motivo da correcao.")
            return
        option = self.option_combo.currentData()
        if not option or not self.preview or not self.preview.get("allowed"):
            QMessageBox.warning(self, "Correcao administrativa", "A correcao selecionada nao esta autorizada pela previa.")
            return
        answer = QMessageBox.question(
            self,
            "Correcao administrativa",
            "A API validara novamente os fatos e a versao antes de aplicar. "
            "A operacao ficara registrada no historico e na auditoria. Deseja continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.service.administrative_correction(
                self.process_id,
                self.expected_version,
                option.get("target_area"),
                option.get("target_status"),
                reason,
                self.idempotency_key,
            )
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, "Correcao administrativa", str(exc))
