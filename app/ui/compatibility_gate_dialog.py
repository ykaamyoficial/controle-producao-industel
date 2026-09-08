from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout

from app.services.app_logging import get_logger
from app.services.compatibility_check import CompatibilityCheckResult
from app.ui.background_worker import start_worker
from app.ui.components.modern_button import ModernButton
from app.versioning.models import CompatibilityStatus

log = get_logger("compatibility_gate_dialog")

_CHECKING_MESSAGE = "Verificando compatibilidade com o servidor..."
_UPDATING_MESSAGE = "Preparando a atualizacao (baixando e validando)..."

# (mensagem ao usuario, bloqueia a operacao?) por estado. COMPATIBLE/UPDATE_AVAILABLE/
# UPDATE_RECOMMENDED nunca aparecem aqui como bloqueantes: o dialogo se fecha sozinho
# para esses tres estados (Fase 13, Secao 2: "Pode operar? SIM").
_STATE_MESSAGES: dict[CompatibilityStatus, str] = {
    CompatibilityStatus.UPDATE_AVAILABLE: "Ha uma nova versao disponivel. Voce pode continuar usando esta versao.",
    CompatibilityStatus.UPDATE_RECOMMENDED: "Atualizacao recomendada. Voce pode continuar usando esta versao, mas atualizar em breve e importante.",
    CompatibilityStatus.UPDATE_REQUIRED: "Atualizacao necessaria. E preciso atualizar para continuar.",
    CompatibilityStatus.INCOMPATIBLE: "Versao nao suportada. Esta versao do aplicativo nao e compativel com o servidor atual.",
    CompatibilityStatus.MAINTENANCE: "O sistema esta em manutencao no servidor. Tente novamente em instantes.",
    CompatibilityStatus.CHECK_FAILED: "Nao foi possivel verificar a compatibilidade com o servidor.",
    # Fase 6 - Compatibilidade de Versoes: o problema e do lado do servidor, nao
    # do Desktop -- a mensagem orienta o administrador, nao pede para o usuario
    # comum "atualizar" (nao ha nada que ele possa baixar aqui).
    CompatibilityStatus.SERVER_UPDATE_REQUIRED: "O servidor esta com uma versao desatualizada da API para este Desktop. Contate o administrador do sistema.",
}
_BLOCKING_STATES = {
    CompatibilityStatus.UPDATE_REQUIRED,
    CompatibilityStatus.INCOMPATIBLE,
    CompatibilityStatus.MAINTENANCE,
    CompatibilityStatus.CHECK_FAILED,
    CompatibilityStatus.SERVER_UPDATE_REQUIRED,
}
# Fase 13, Secao 17/18: REQUIRED nunca tem botao "Ignorar"; REQUIRED/INCOMPATIBLE
# oferecem "Atualizar agora" quando o servidor indicou uma versao autorizada.
_UPDATE_OFFER_STATES = {CompatibilityStatus.UPDATE_REQUIRED, CompatibilityStatus.INCOMPATIBLE}


class CompatibilityGateDialog(QDialog):
    """Verifica compatibilidade Desktop<->API antes de liberar a interface operacional.

    Roda a checagem (rede + decisao) em uma QThread via start_worker para nao travar a UI.
    COMPATIBLE/UPDATE_AVAILABLE/UPDATE_RECOMMENDED fecham o dialogo automaticamente (proceed=True).
    UPDATE_REQUIRED/INCOMPATIBLE/MAINTENANCE/CHECK_FAILED bloqueiam com Tentar novamente/Sair,
    mais "Atualizar agora" quando ha uma versao autorizada (Fase 13, Secao 21: delega
    integralmente ao UpdateCoordinator -- nunca constroi o fluxo de update aqui).
    """

    def __init__(
        self,
        perform_check: Callable[[], CompatibilityCheckResult],
        parent=None,
        *,
        update_launcher: Callable[[str | None], object] | None = None,
    ):
        super().__init__(parent)
        self._perform_check = perform_check
        self._update_launcher = update_launcher or self._default_update_launcher
        self.proceed = False
        self.update_launched = False
        self.check_result: CompatibilityCheckResult | None = None
        self._checking = False
        self._updating = False
        self._thread = None
        self._update_thread = None
        self.setWindowTitle("Verificando compatibilidade")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self._build()
        self._start_check()

    @staticmethod
    def _default_update_launcher(expected_version: str | None):
        from app.services.update_coordinator import UpdateCoordinator

        return UpdateCoordinator().start_required_update(expected_version=expected_version)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(14)

        self.message_label = QLabel(_CHECKING_MESSAGE)
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)

        footer = QHBoxLayout()
        footer.addStretch()
        self.update_now_button = ModernButton("Atualizar agora", "download", accent=True)
        self.update_now_button.clicked.connect(self._on_update_now)
        self.update_now_button.hide()
        footer.addWidget(self.update_now_button)
        self.retry_button = ModernButton("Tentar novamente", "refresh")
        self.retry_button.clicked.connect(self._start_check)
        self.retry_button.hide()
        footer.addWidget(self.retry_button)
        self.exit_button = ModernButton("Sair", "clear")
        self.exit_button.clicked.connect(self._on_exit)
        self.exit_button.hide()
        footer.addWidget(self.exit_button)
        layout.addLayout(footer)

    def _start_check(self) -> None:
        if self._checking:
            return
        self._checking = True
        self.update_now_button.hide()
        self.retry_button.hide()
        self.exit_button.hide()
        self.message_label.setText(_CHECKING_MESSAGE)
        self._thread = start_worker(self, self._perform_check, self._on_result, self._on_error)

    def _on_result(self, result: CompatibilityCheckResult) -> None:
        self._checking = False
        self.check_result = result
        if result.state not in _BLOCKING_STATES:
            self.proceed = True
            self.accept()
            return
        if result.state == CompatibilityStatus.MAINTENANCE:
            # Fase 14: a tela de manutencao dedicada (MaintenanceModeDialog)
            # assume daqui em diante -- fecha sem exigir interacao do
            # usuario, sem mostrar a mensagem estatica generica.
            self.proceed = False
            self.accept()
            return
        message = _STATE_MESSAGES.get(result.state, "Nao foi possivel verificar a compatibilidade com o servidor.")
        if result.state == CompatibilityStatus.UPDATE_REQUIRED and result.dto is not None:
            message += f"\n\nVersao minima exigida: {result.dto.minimum_desktop_version}"
        if result.dto is not None and result.dto.message:
            message += f"\n\n{result.dto.message}"
        self.message_label.setText(message)
        can_offer_update = (
            result.state in _UPDATE_OFFER_STATES
            and result.dto is not None
            and bool(result.dto.authorized_update_version)
        )
        self.update_now_button.setVisible(can_offer_update)
        self.retry_button.show()
        self.exit_button.show()

    def _on_error(self, exc: Exception) -> None:
        self._checking = False
        log.exception("Falha inesperada ao verificar compatibilidade")
        self.check_result = CompatibilityCheckResult(CompatibilityStatus.CHECK_FAILED, "-")
        self.message_label.setText(_STATE_MESSAGES[CompatibilityStatus.CHECK_FAILED])
        self.update_now_button.hide()
        self.retry_button.show()
        self.exit_button.show()

    def _on_update_now(self) -> None:
        if self._updating or self.check_result is None or self.check_result.dto is None:
            return
        self._updating = True
        self.update_now_button.setEnabled(False)
        self.retry_button.setEnabled(False)
        self.exit_button.setEnabled(False)
        self.message_label.setText(_UPDATING_MESSAGE)

        expected_version = self.check_result.dto.authorized_update_version
        self._update_thread = start_worker(
            self, lambda: self._update_launcher(expected_version), self._on_update_result, self._on_update_error,
        )

    def _on_update_result(self, result) -> None:
        self._updating = False
        self.update_now_button.setEnabled(True)
        self.retry_button.setEnabled(True)
        self.exit_button.setEnabled(True)
        if getattr(result, "launched", False):
            # Nunca um QMessageBox modal aqui: o app esta prestes a fechar
            # sozinho (Secao 13, "nao matar o processo enquanto o usuario
            # trabalha" tambem implica nunca travar o fechamento esperando
            # um clique). O feedback fica no message_label, visivel por um
            # instante antes do dialogo fechar.
            self.update_launched = True
            self.proceed = False
            self.message_label.setText("Atualizacao iniciada. O sistema sera fechado automaticamente para concluir a instalacao.")
            self.reject()
            return
        error_message = getattr(result, "error_message", None) or "Nao foi possivel iniciar a atualizacao."
        self.message_label.setText(f"{_STATE_MESSAGES.get(self.check_result.state, '')}\n\nFalha ao atualizar: {error_message}")

    def _on_update_error(self, exc: Exception) -> None:
        self._updating = False
        self.update_now_button.setEnabled(True)
        self.retry_button.setEnabled(True)
        self.exit_button.setEnabled(True)
        log.exception("Falha inesperada ao iniciar a atualizacao")
        self.message_label.setText(f"{_STATE_MESSAGES.get(self.check_result.state, '')}\n\nFalha ao atualizar. Consulte os logs tecnicos.")

    def _on_exit(self) -> None:
        self.proceed = False
        self.reject()
