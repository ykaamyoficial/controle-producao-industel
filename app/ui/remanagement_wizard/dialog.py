from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QStackedWidget, QVBoxLayout

from app.services.remanagement_flow_state import RemanagementFlowState
from app.ui.animations import fade_in
from app.ui.components.app_icon_button import AppIconButton
from app.ui.components.dialog_shell import dialog_footer, dialog_header
from app.ui.components.modern_button import ModernButton
from app.ui.components.wizard_stepper import WizardStepper
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.icons import AppIcons, IconSize
from app.ui.remanagement_wizard.destination_page import DestinationPage
from app.ui.remanagement_wizard.items_page import ItemsPage
from app.ui.remanagement_wizard.review_page import ReviewPage
from app.ui.remanagement_wizard.sources_page import SourcesPage

TITLE = "Remanejamento de materiais"
CONFIRM_LABEL = "Confirmar remanejamento"


class RemanagementWizardDialog(QDialog):
    """Remanejamento de materiais em UMA janela grande (mesmo tamanho da
    central de chats) que troca de pagina conforme o usuario avanca:

    1. Proposta destino  - quem vai receber (so Producao/Galvanizacao)
    2. Itens             - o que adiantar e quanto
    3. Origem do material - de qual proposta da Expedicao cada item sai
    4. Revisao           - simulacao, motivo e confirmacao

    Todas as paginas compartilham um unico `RemanagementFlowState`, entao
    "Voltar" preserva o que ja foi escolhido. Nada e gravado antes da
    confirmacao do ultimo passo (`ReviewPage.commit`)."""

    def __init__(self, service, parent=None, state: RemanagementFlowState | None = None, initial_destination_id: int | None = None):
        super().__init__(parent)
        self.service = service
        self.state = state if state is not None else RemanagementFlowState()
        if initial_destination_id is not None:
            self.state.destination_proposal_id = initial_destination_id
        self.confirm_result: dict | None = None
        self._index = 0

        self.destination_page = DestinationPage(service, self.state)
        self.items_page = ItemsPage(service, self.state)
        self.sources_page = SourcesPage(service, self.state)
        self.review_page = ReviewPage(service, self.state)
        self.pages = [self.destination_page, self.items_page, self.sources_page, self.review_page]

        self.setWindowTitle(TITLE)
        apply_large_dialog_geometry(self, parent, width_ratio=0.94, height_ratio=0.94, minimum_width=1180, minimum_height=690)
        style_dialog_from_parent(self, parent)
        self._build()
        for page in self.pages:
            page.validity_changed.connect(self._sync_buttons)
            page.advance_requested.connect(self._next)
        self.destination_page.enter()
        self._show_page(0)

    # -- construcao -----------------------------------------------------------

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        self.close_button = AppIconButton(
            AppIcons.CLOSE, palette=getattr(self.service, "palette", None), size=IconSize.LG, tooltip="Fechar",
        )
        self.close_button.setFixedSize(36, 36)
        self.close_button.clicked.connect(self.reject)
        self.header = dialog_header(TITLE, "", actions=[self.close_button])
        root.addWidget(self.header)

        stepper_frame = QFrame()
        stepper_frame.setObjectName("DetailPanel")
        stepper_row = QHBoxLayout(stepper_frame)
        stepper_row.setContentsMargins(18, 8, 18, 8)
        self.stepper = WizardStepper([page.step_name for page in self.pages])
        self.stepper.step_clicked.connect(self._go_back_to)
        stepper_row.addWidget(self.stepper)
        root.addWidget(stepper_frame)

        self.stack = QStackedWidget()
        for page in self.pages:
            self.stack.addWidget(page)
        root.addWidget(self.stack, 1)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("ValueLabel")
        self.cancel_button = ModernButton("Cancelar", "clear", variant="ghost")
        self.back_button = ModernButton("Voltar", "previous")
        # Nasce com o rotulo mais longo: a largura do botao nao muda de passo a passo.
        self.next_button = ModernButton(CONFIRM_LABEL, "next", accent=True)
        self.cancel_button.clicked.connect(self.reject)
        self.back_button.clicked.connect(self._back)
        self.next_button.clicked.connect(self._next)
        root.addWidget(dialog_footer(left=[self.summary_label], right=[self.cancel_button, self.back_button, self.next_button]))

    # -- navegacao ------------------------------------------------------------

    def current_page(self):
        return self.pages[self._index]

    def _show_page(self, index: int) -> None:
        self._index = index
        page = self.pages[index]
        changed = self.stack.currentIndex() != index
        self.stack.setCurrentIndex(index)
        if changed and self.isVisible():
            self._page_fade = fade_in(page, duration=160)
        self.stepper.set_current(index)
        self.header.title_label.setText(TITLE)
        if self.header.subtitle_label is not None:
            self.header.subtitle_label.setText(f"Passo {index + 1} de {len(self.pages)} — {page.instruction}")
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        page = self.current_page()
        last = self._index == len(self.pages) - 1
        self.back_button.setVisible(self._index > 0)
        self.next_button.setText(page.next_label)
        self.next_button.set_icon_semantic(page.next_icon)
        self.next_button.setEnabled(page.is_valid())
        self.summary_label.setText(page.summary())
        self.next_button.setToolTip(CONFIRM_LABEL if last else "")

    def _enter(self, index: int) -> None:
        """Chega a pagina `index` avancando: passa o destino adiante e carrega."""
        destination = self.destination_page.selected_row()
        self.items_page.set_destination(destination)
        self.review_page.set_destination(destination)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.pages[index].enter()
        finally:
            QApplication.restoreOverrideCursor()
        self._show_page(index)

    def _next(self) -> None:
        page = self.current_page()
        if not self.next_button.isEnabled() or not page.is_valid():
            return
        # Impede duplo clique durante a gravacao/validacao.
        self.next_button.setEnabled(False)
        try:
            committed = page.commit()
        finally:
            self._sync_buttons()
        if not committed:
            return
        if self._index == len(self.pages) - 1:
            self.confirm_result = self.review_page.confirm_result
            self.accept()
            return
        self._enter(self._index + 1)

    def _back(self) -> None:
        if self._index > 0:
            self._show_page(self._index - 1)

    def _go_back_to(self, index: int) -> None:
        if 0 <= index < self._index:
            self._show_page(index)

    # -- fechar ---------------------------------------------------------------

    def has_progress(self) -> bool:
        return bool(self.state.item_selections or self.state.allocations)

    def reject(self) -> None:  # noqa: N802 (Qt override)
        # Fechar com escolhas feitas pede confirmacao; nada foi gravado ainda.
        if self.result() != QDialog.Accepted and self.has_progress():
            answer = QMessageBox.question(
                self, "Cancelar remanejamento?",
                "As escolhas feitas até aqui serão descartadas. Nada foi gravado.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        super().reject()
