from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout

from app.services.app_logging import get_logger
from app.services.compatibility_check import CompatibilityCheckResult
from app.ui.background_worker import start_worker
from app.ui.components.modern_button import ModernButton
from app.version import APP_VERSION
from app.versioning.models import CompatibilityStatus

log = get_logger("maintenance_mode_dialog")

_BASE_POLL_INTERVAL_MS = 20_000
_MIN_POLL_INTERVAL_MS = 5_000
_MAX_POLL_INTERVAL_MS = 120_000

_REASON_LABELS = {
    "DEPLOYMENT": "Atualizacao de versao",
    "DATABASE_MIGRATION": "Migracao de banco de dados",
    "EMERGENCY_MAINTENANCE": "Manutencao emergencial",
    "INFRASTRUCTURE": "Manutencao de infraestrutura",
    "SECURITY": "Correcao de seguranca",
    "DATA_RECOVERY": "Recuperacao de dados",
    "MANUAL_ADMIN": "Manutencao administrativa",
}


class MaintenanceModeDialog(QDialog):
    """Tela dedicada de manutencao (Fase 14, Secao 23) -- mostrada em vez do
    erro HTTP 503 bruto ou da mensagem generica do CompatibilityGateDialog
    quando o servidor esta em ACTIVE/RECOVERY.

    Re-executa a mesma verificacao de compatibilidade (perform_check) em
    intervalo periodico (Secao 25: nunca a cada segundo, respeita
    retry_after_seconds quando informado, com backoff simples em falha de
    rede) ate o estado deixar de bloquear -- nesse momento fecha sozinha
    (proceed=True), igual ao CompatibilityGateDialog para os demais estados.
    """

    def __init__(
        self,
        perform_check: Callable[[], CompatibilityCheckResult],
        initial_result: CompatibilityCheckResult,
        parent=None,
        *,
        auto_start_timer: bool = True,
    ):
        super().__init__(parent)
        self._perform_check = perform_check
        self.proceed = False
        self.check_result = initial_result
        self._checking = False
        self._thread = None
        self._poll_interval_ms = _BASE_POLL_INTERVAL_MS

        self.setWindowTitle("Sistema em manutencao")
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._poll)

        self._build()
        self._apply_result(initial_result)
        if auto_start_timer:
            self._schedule_next_poll()

    # -- UI ---------------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 20)
        layout.setSpacing(10)

        self.title_label = QLabel("Sistema em manutencao")
        title_font = self.title_label.font()
        title_font.setPointSize(title_font.pointSize() + 3)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        layout.addWidget(self.title_label)

        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)

        self.details_label = QLabel()
        self.details_label.setWordWrap(True)
        self.details_label.setStyleSheet("color: #64748b;")
        layout.addWidget(self.details_label)

        self.status_label = QLabel()
        self.status_label.setStyleSheet("color: #94a3b8; font-size: 11px;")
        layout.addWidget(self.status_label)

        version_label = QLabel(f"Versao do Desktop: {APP_VERSION}")
        version_label.setStyleSheet("color: #94a3b8; font-size: 11px;")
        layout.addWidget(version_label)

        footer = QHBoxLayout()
        footer.addStretch()
        self.retry_button = ModernButton("Tentar novamente", "refresh")
        self.retry_button.clicked.connect(self._poll)
        footer.addWidget(self.retry_button)
        self.exit_button = ModernButton("Fechar", "clear")
        self.exit_button.clicked.connect(self._on_exit)
        footer.addWidget(self.exit_button)
        layout.addLayout(footer)

    # -- ciclo de verificacao ----------------------------------------------

    def _schedule_next_poll(self) -> None:
        self._timer.start(self._poll_interval_ms)

    def _poll(self) -> None:
        if self._checking:
            return
        self._checking = True
        self._timer.stop()
        self.retry_button.setEnabled(False)
        self._thread = start_worker(self, self._perform_check, self._on_result, self._on_error)

    def _on_result(self, result: CompatibilityCheckResult) -> None:
        self._checking = False
        self.retry_button.setEnabled(True)
        self.check_result = result

        if result.state != CompatibilityStatus.MAINTENANCE and result.state != CompatibilityStatus.CHECK_FAILED:
            log.info("Manutencao encerrada no servidor -- liberando a area operacional | novo_estado=%s", result.state.value)
            self.proceed = True
            self.accept()
            return

        self._poll_interval_ms = _BASE_POLL_INTERVAL_MS
        self._apply_result(result)
        self._schedule_next_poll()

    def _on_error(self, exc: Exception) -> None:
        self._checking = False
        self.retry_button.setEnabled(True)
        log.warning("Falha ao consultar manutencao -- aplicando backoff", exc_info=True)
        self._poll_interval_ms = min(self._poll_interval_ms * 2, _MAX_POLL_INTERVAL_MS)
        self.status_label.setText("Nao foi possivel confirmar o status agora. Nova tentativa em instantes.")
        self._schedule_next_poll()

    # -- apresentacao -------------------------------------------------------

    def _apply_result(self, result: CompatibilityCheckResult) -> None:
        dto = result.dto
        maintenance = dto.maintenance if dto is not None else None

        if maintenance is None:
            self.message_label.setText("O sistema esta em manutencao no servidor. Tente novamente em instantes.")
            self.details_label.setText("")
            self.status_label.setText("")
            return

        self.message_label.setText(maintenance.message or "O sistema esta em manutencao no servidor.")

        details: list[str] = []
        reason_label = _REASON_LABELS.get(getattr(maintenance, "reason_code", ""), None)
        if reason_label:
            details.append(f"Motivo: {reason_label}")
        if maintenance.expected_end_at:
            details.append(f"Previsao de retorno: {maintenance.expected_end_at}")
        self.details_label.setText("  |  ".join(details))

        retry_seconds = maintenance.retry_after_seconds
        if retry_seconds:
            self._poll_interval_ms = max(retry_seconds * 1000, _MIN_POLL_INTERVAL_MS)
        self.status_label.setText(f"Status: {maintenance.state}  |  Verificando automaticamente...")

    # -- acoes do usuario -----------------------------------------------

    def _on_exit(self) -> None:
        self.proceed = False
        self._timer.stop()
        self.reject()

    def closeEvent(self, event) -> None:
        self._timer.stop()
        super().closeEvent(event)
