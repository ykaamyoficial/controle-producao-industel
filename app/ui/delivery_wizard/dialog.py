from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QStackedWidget, QVBoxLayout

from app.ui.animations import fade_in
from app.ui.components.app_icon_button import AppIconButton
from app.ui.components.dialog_shell import dialog_footer, dialog_header
from app.ui.components.modern_button import ModernButton
from app.ui.components.wizard_stepper import WizardStepper
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.icons import AppIcons, IconSize
from app.ui.delivery_wizard.done_page import DonePage
from app.ui.delivery_wizard.items_page import ItemsPage
from app.ui.delivery_wizard.review_page import ReviewPage
from app.ui.delivery_wizard.state import DeliveryWizardState

TITLE = "Registrar retirada do cliente"
CONFIRM_LABEL = "Confirmar retirada"


class DeliveryWizardDialog(QDialog):
    """Registro de retirada pelo cliente em UMA janela grande (mesmo tamanho do
    remanejamento e do registro de producao) que troca de pagina:

    1. Itens      - marca o que o cliente retirou
    2. Revisao    - confere e grava (ENTREGUE ou ENTREGUE_PARCIAL por proposta)
    3. Concluido  - resultado, na propria janela

    Propostas sem item pendente entram como entrega direta. Nada e gravado
    antes da confirmacao da revisao."""

    def __init__(
        self,
        service,
        process_ids: list[int],
        parent=None,
        observation: str = "",
        preselected_item_ids: set[int] | list[int] | None = None,
    ):
        super().__init__(parent)
        self.service = service
        self.state = DeliveryWizardState(
            process_ids=list(dict.fromkeys(int(value) for value in process_ids)),
            observation=observation,
            selected_item_ids={int(value) for value in (preselected_item_ids or [])},
        )
        self.items_page = ItemsPage(service, self.state)
        self.review_page = ReviewPage(service, self.state)
        self.done_page = DonePage(service, self.state)
        self._all_pages = [self.items_page, self.review_page, self.done_page]
        self._current = self.items_page

        self.setWindowTitle(TITLE)
        apply_large_dialog_geometry(self, parent, width_ratio=0.94, height_ratio=0.94, minimum_width=1180, minimum_height=690)
        style_dialog_from_parent(self, parent)
        self._build()
        for page in self._all_pages:
            page.validity_changed.connect(self._sync_buttons)
            page.advance_requested.connect(self._next)
        self.items_page.enter()
        self._show_page(self.items_page)

    @property
    def registered(self) -> bool:
        """Algo foi gravado (fluxo ou producao): quem abriu deve recarregar a tela."""
        return bool(self.state.changed)

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
        self.stepper = WizardStepper([page.step_name for page in self._sequence()])
        self.stepper.step_clicked.connect(self._go_back_to)
        stepper_row.addWidget(self.stepper)
        root.addWidget(stepper_frame)

        self.stack = QStackedWidget()
        for page in self._all_pages:
            self.stack.addWidget(page)
        root.addWidget(self.stack, 1)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("ValueLabel")
        self.cancel_button = ModernButton("Cancelar", "clear", variant="ghost")
        self.back_button = ModernButton("Voltar", "previous")
        # Nasce com o rotulo mais longo: a largura do botao nao muda de passo a passo.
        self.next_button = ModernButton("Confirmar retirada", "next", accent=True)
        self.cancel_button.clicked.connect(self.reject)
        self.back_button.clicked.connect(self._back)
        self.next_button.clicked.connect(self._next)
        root.addWidget(dialog_footer(left=[self.summary_label], right=[self.cancel_button, self.back_button, self.next_button]))

    # -- navegacao ------------------------------------------------------------

    def _sequence(self) -> list:
        return [self.items_page, self.review_page, self.done_page]

    def current_page(self):
        return self._current

    def _show_page(self, page) -> None:
        self._current = page
        sequence = self._sequence()
        index = sequence.index(page)
        self.stepper.set_steps([p.step_name for p in sequence])
        self.stepper.set_current(index)
        changed = self.stack.currentWidget() is not page
        self.stack.setCurrentWidget(page)
        if changed and self.isVisible():
            self._page_fade = fade_in(page, duration=160)
        self.header.title_label.setText(TITLE)
        if self.header.subtitle_label is not None:
            self.header.subtitle_label.setText(f"Passo {index + 1} de {len(sequence)} — {page.instruction}")
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        page = self._current
        sequence = self._sequence()
        done = page is self.done_page
        self.back_button.setVisible(page is not self.items_page and not done)
        self.cancel_button.setVisible(not done)
        self.close_button.setVisible(True)
        self.next_button.setText(page.next_label)
        self.next_button.set_icon_semantic(page.next_icon)
        self.next_button.setEnabled(page.is_valid())
        self.summary_label.setText(page.summary())
        self.next_button.setToolTip(CONFIRM_LABEL if page is self.review_page else "")
        self.stepper.set_current(sequence.index(page))

    def _enter(self, page) -> None:
        """Chega a pagina avancando: carrega os dados dela."""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            page.enter()
        finally:
            QApplication.restoreOverrideCursor()
        self._show_page(page)

    def _next(self) -> None:
        page = self._current
        if page is self.done_page:
            self.accept()
            return
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
        sequence = self._sequence()
        index = sequence.index(page)
        if index + 1 < len(sequence):
            self._enter(sequence[index + 1])

    def _back(self) -> None:
        sequence = self._sequence()
        index = sequence.index(self._current)
        if index > 0:
            self._show_page(sequence[index - 1])

    def _go_back_to(self, index: int) -> None:
        sequence = self._sequence()
        current_index = sequence.index(self._current)
        if self._current is self.done_page:
            return  # registrado: nao ha para onde voltar
        if 0 <= index < current_index:
            self._show_page(sequence[index])

    # -- fechar ---------------------------------------------------------------

    def has_progress(self) -> bool:
        return bool(self.state.selected_item_ids) and self._current is not self.done_page

    def reject(self) -> None:  # noqa: N802 (Qt override)
        if self._current is self.done_page:
            super().accept()
            return
        if self.result() != QDialog.Accepted and self.has_progress() and self._current is not self.items_page:
            answer = QMessageBox.question(
                self, "Cancelar registro de retirada?",
                "As escolhas feitas até aqui serão descartadas. Nada foi gravado.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        super().reject()
