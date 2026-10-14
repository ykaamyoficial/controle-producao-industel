from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.services.remanagement_flow_state import RemanagementFlowState
from app.ui.components.dialog_shell import set_notice_kind


class WizardPage(QWidget):
    """Uma pagina do assistente de remanejamento.

    O dialogo chama `enter()` toda vez que o usuario CHEGA avancando (voltar
    nao recarrega, para nao perder o que ja foi digitado) e `commit()` quando
    ele pede para avancar: a pagina grava no `RemanagementFlowState` e devolve
    False para segurar o usuario nela (depois de avisar o motivo).
    """

    validity_changed = Signal()
    advance_requested = Signal()

    # Titulo curto do passo (trilha) e instrucao do cabecalho.
    step_name = ""
    instruction = ""
    next_label = "Avançar"
    next_icon = "next"

    def __init__(self, service, state: RemanagementFlowState, parent=None):
        super().__init__(parent)
        self.service = service
        self.state = state
        self.load_error: str | None = None
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(12)
        self.notice = QLabel("")
        self.notice.setWordWrap(True)
        set_notice_kind(self.notice, "danger")
        self.notice.setVisible(False)
        self.root.addWidget(self.notice)

    # -- contrato com o dialogo -------------------------------------------

    def enter(self) -> None:
        """Carrega/atualiza os dados da pagina. Falha vira `load_error`."""

    def is_valid(self) -> bool:
        return False

    def commit(self) -> bool:
        return True

    def summary(self) -> str:
        """Texto do rodape (a esquerda dos botoes)."""
        return ""

    # -- aviso em linha -----------------------------------------------------

    def show_error(self, message: str) -> None:
        self.load_error = message
        self.show_notice(message, "danger")

    def show_notice(self, message: str, kind: str = "warning") -> None:
        self.notice.setText(message)
        set_notice_kind(self.notice, kind)
        self.notice.setVisible(bool(message))

    def clear_notice(self) -> None:
        self.load_error = None
        self.notice.setText("")
        self.notice.setVisible(False)
