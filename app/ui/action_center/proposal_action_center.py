from __future__ import annotations

from dataclasses import replace
from typing import Any

from PySide6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)

from app.services.app_logging import get_logger
from app.ui.action_center.context import ProposalActionContext
from app.ui.action_center.descriptor import ActionCategory, ActionDescriptor
from app.ui.action_center.provider import AREA_COLOR_KEYS, CATEGORY_TO_CARD_TYPE
from app.ui.action_center.registry import ActionRegistry
from app.ui.background_worker import start_worker
from app.ui.components.action_card_button import ActionCardButton
from app.ui.components.modern_button import ModernButton
from app.ui.components.status_badge import StatusBadge
from app.ui.dialog_utils import style_dialog_from_parent
from app.ui.icons import AppIcons
from app.ui.theme_tokens import with_alpha

log = get_logger("action_center")

_ACTIONS_SCROLL_MAX_HEIGHT = 420


class ProposalActionCenter(QDialog):
    """Central de Ações da proposta: apresentação + descoberta + roteamento.
    Não calcula status, não decide transições, não substitui services/API -
    apenas monta o contexto, pede os descriptors ao provider, e roteia a
    ação escolhida ao handler registrado. Ver StatusDialog para a instancia
    de Producao (provider + registry pre-configurados)."""

    def __init__(
        self,
        service,
        process_id: int,
        area: str | None,
        provider,
        registry: ActionRegistry,
        parent=None,
        row_context: dict[str, Any] | None = None,
    ):
        super().__init__(parent)
        self.service = service
        self.process_id = process_id
        self.provider = provider
        self.registry = registry
        self.row_context = dict(row_context or {})
        self._action_thread = None
        self._running_action = False
        self._action_buttons: list[ActionCardButton] = []
        self.success_message = ""
        self._reload_on_success = False
        self._changed_since_open = False
        base_process = service.get_process_dict(process_id)
        self.area = area or service.current_location(base_process)[0] or "CONTROLE GERAL"
        self.context = self._load_context()
        self.setWindowTitle("Acoes da proposta")
        style_dialog_from_parent(self, parent)
        self._build()
        self.setMinimumWidth(720)
        self.resize(760, self.sizeHint().height())
        self._center_on_parent(parent)
        log.info("Action Center aberto: proposal_id=%s area=%s", process_id, self.area)

    def _center_on_parent(self, parent):
        owner = parent.window() if parent and parent.window() else None
        if not owner:
            return
        frame = self.frameGeometry()
        frame.moveCenter(owner.geometry().center())
        self.move(frame.topLeft())

    # -- context -----------------------------------------------------------

    def _load_context(self) -> ProposalActionContext:
        self.process = self.service.get_process_area_dict(self.process_id, self.area)
        if self.row_context:
            self.process.update(self.row_context)
        current_status = self.service.status_for_area(self.process, self.area)
        self.current_status = current_status
        base_context = ProposalActionContext(
            proposal_id=self.process_id,
            area=self.area,
            current_status=current_status,
            proposal_number=str(self.process.get("proposta", "") or ""),
            client_name=self.process.get("cliente"),
            proposal_data=self.process,
            can_admin=self.service.can_admin(),
        )
        actions = self.provider.get_actions(base_context)
        return replace(base_context, available_actions=tuple(actions))

    def reload_context(self):
        """Reconsulta proposta/area/status/acoes/permissoes e re-renderiza o
        cabecalho e a grade de acoes sem fechar a Central."""
        self.context = self._load_context()
        palette = self.service.palette
        self._update_header(palette)
        self._populate_actions(self._actions_layout, palette)

    # -- layout --------------------------------------------------------

    def _build(self):
        palette = self.service.palette
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 14)
        root.setSpacing(12)

        root.addLayout(self._build_header(palette))

        instruction = QLabel("Acoes disponiveis")
        instruction.setStyleSheet("font-weight: 700; font-size: 13px;")
        root.addWidget(instruction)

        self._actions_container = QWidget()
        self._actions_layout = QVBoxLayout(self._actions_container)
        self._actions_layout.setContentsMargins(0, 0, 0, 0)
        self._actions_layout.setSpacing(0)
        root.addWidget(self._actions_container, 1)
        self._populate_actions(self._actions_layout, palette)

        root.addWidget(QLabel("Observacao (opcional)"))
        self.observation = QTextEdit()
        self.observation.setPlaceholderText("Acrescente uma informacao importante sobre esta operacao")
        self.observation.setFixedHeight(68)
        root.addWidget(self.observation)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background: {palette['border']}; border: 0;")
        root.addWidget(divider)

        root.addLayout(self._build_footer())

    def _build_header(self, palette) -> QVBoxLayout:
        header = QVBoxLayout()
        header.setSpacing(4)
        self._title_label = QLabel()
        self._title_label.setStyleSheet("font-size: 16px; font-weight: 800;")
        self._title_label.setWordWrap(True)
        header.addWidget(self._title_label)

        self._badges_widget = QWidget()
        self._badges_layout = QHBoxLayout(self._badges_widget)
        self._badges_layout.setContentsMargins(0, 0, 0, 0)
        self._badges_layout.setSpacing(6)
        header.addWidget(self._badges_widget)

        self._update_header(palette)
        return header

    def _update_header(self, palette):
        self._title_label.setText(f"{self.process.get('proposta', '')} — {self.process.get('cliente', '')}")
        self._clear_layout(self._badges_layout)
        area_label = self.area.title()
        stage_color = palette.get(AREA_COLOR_KEYS.get(self.area, ""), palette["accent"])
        self._badges_layout.addWidget(StatusBadge(area_label or "-", with_alpha(stage_color, 34), stage_color))
        if self.context.current_status:
            status_text = self.service.area_status_label(self.area, self.context.current_status)
            self._badges_layout.addWidget(StatusBadge(status_text, with_alpha(palette["muted"], 30), palette["text"]))
        self._badges_layout.addStretch()

    def _populate_actions(self, layout: QVBoxLayout, palette):
        self._clear_layout(layout)
        self._action_buttons = []
        actions = self.context.available_actions
        if not actions:
            message = "Nao ha nenhuma acao disponivel nesta etapa."
            if self.area == "GALVANIZACAO":
                message = "Esta movimentacao e controlada pela tela Cargas."
            empty = QLabel(message)
            empty.setObjectName("Caption")
            layout.addWidget(empty)
            return

        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        secondary_actions = [action for action in actions if action.category != ActionCategory.PRIMARY]
        primary_action = next((action for action in actions if action.category == ActionCategory.PRIMARY), None)

        focus_card = None
        row = col = 0
        for descriptor in secondary_actions:
            grid.addWidget(self._build_card(descriptor, palette), row, col)
            col += 1
            if col == 2:
                col = 0
                row += 1
        if primary_action is not None:
            card = self._build_card(primary_action, palette)
            grid.addWidget(card, row + 1 if col else row, 0, 1, 2)
            focus_card = card

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(grid_widget)
        scroll.setMinimumHeight(min(grid_widget.sizeHint().height(), _ACTIONS_SCROLL_MAX_HEIGHT))
        layout.addWidget(scroll)
        if focus_card is not None:
            focus_card.setFocus()

    def _build_card(self, descriptor: ActionDescriptor, palette) -> ActionCardButton:
        card = ActionCardButton(
            title=descriptor.label,
            description=descriptor.description,
            icon=descriptor.icon,
            action_type=CATEGORY_TO_CARD_TYPE.get(descriptor.category, "secondary"),
            palette=palette,
        )
        card.clicked.connect(lambda _checked=False, data=descriptor: self.run_action(data))
        self._action_buttons.append(card)
        return card

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        if self.service.can_admin():
            manual = ModernButton("Correcao administrativa", AppIcons.ADMIN_CORRECTION)
            manual.clicked.connect(self.open_manual_correction)
            footer.addWidget(manual)
        footer.addStretch()
        close = ModernButton("Fechar", AppIcons.CLOSE)
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        return footer

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
                continue
            child_layout = item.layout()
            if child_layout is not None:
                ProposalActionCenter._clear_layout(child_layout)

    # -- routing -------------------------------------------------------

    def run_action(self, action: ActionDescriptor):
        if self._running_action:
            return
        self.success_message = ""
        handler = self.registry.resolve(action.id, action.area)
        if handler is None:
            log.error("Acao sem handler registrado: id=%s area=%s", action.id, action.area)
            QMessageBox.warning(self, "Acao da proposta", "Esta acao nao esta disponivel nesta versao.")
            return
        try:
            handler.execute(self.context, action, self)
        except Exception as exc:
            log.exception("Falha ao executar acao da proposta: id=%s", action.id)
            QMessageBox.warning(self, "Acao da proposta", str(exc))

    def _run_background_action(self, operation, reload_on_success: bool = False):
        self._reload_on_success = reload_on_success
        self._set_action_running(True)
        self._action_thread = start_worker(self, operation, self._action_success, self._action_error)

    def _action_success(self, _result):
        self._set_action_running(False)
        if self.success_message:
            QMessageBox.information(self, "Produção", self.success_message)
        if self._reload_on_success:
            self._reload_on_success = False
            self._changed_since_open = True
            self.reload_context()
            return
        self.accept()

    def _action_error(self, exc):
        self._reload_on_success = False
        self._set_action_running(False)
        self.success_message = ""
        QMessageBox.warning(self, "Acao da proposta", str(exc))
        try:
            self.reload_context()
        except Exception:
            log.exception("Falha ao recarregar contexto apos erro de acao: process_id=%s", self.process_id)

    def _set_action_running(self, running: bool):
        self._running_action = running
        self.observation.setEnabled(not running)
        for button in self._action_buttons:
            button.setEnabled(not running)

    def reject(self):
        # Fechar/Escape/X apos uma acao que ficou aberta (reload_context em vez de
        # accept()) ainda deve contar como "houve mudanca" para quem chamou exec() -
        # ex.: ProcessPage recarrega a tabela quando o dialog e aceito.
        if self._changed_since_open:
            self.accept()
            return
        super().reject()

    def open_manual_correction(self):
        from app.ui.status_dialog import ManualStatusDialog

        try:
            dialog = ManualStatusDialog(self.service, self.process_id, self.area, self)
            if dialog.exec():
                self.accept()
        except Exception as exc:
            QMessageBox.warning(self, "Correcao administrativa", str(exc))
