from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from app.integrations.api.client import DesktopApiClient
from app.integrations.api.config import DesktopApiConfigError, DesktopApiConfigStore, normalize_api_base_url
from app.services.app_logging import get_logger
from app.services.bootstrap_service import (
    BootstrapErrorCode,
    BootstrapResult,
    BootstrapState,
    get_bootstrap_default_url,
    probe_health,
    run_bootstrap,
)
from app.ui.background_worker import start_worker
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import style_dialog_from_parent

log = get_logger("first_access_dialog")

_CHECKING_MESSAGE = "Conectando ao servidor..."
_MISSING_MESSAGE = "Nao foi possivel conectar automaticamente ao servidor."
_UNREACHABLE_MESSAGE = "Nao foi possivel conectar ao servidor configurado."
_EXPLANATION = "Informe o endereco da API do Controle de Producao na rede da empresa (fornecido pelo suporte tecnico)."

_ERROR_DETAILS = {
    BootstrapErrorCode.CONFIG_INVALID: "O endereco salvo nao e valido.",
    BootstrapErrorCode.DNS_OR_CONNECT_ERROR: "O servidor nao foi encontrado ou recusou a conexao.",
    BootstrapErrorCode.TIMEOUT: "O servidor nao respondeu no tempo esperado.",
    BootstrapErrorCode.HEALTH_HTTP_ERROR: "O servidor respondeu com um erro inesperado.",
    BootstrapErrorCode.API_UNHEALTHY: "O servidor esta acessivel, mas informou que ainda nao esta pronto.",
}


class FirstAccessDialog(QDialog):
    """Fase 3 - Primeiro Acesso Automatico.

    Ao abrir, tenta localizar a API oficial automaticamente (configuracao
    persistente da Fase 2 ou, na ausencia dela, um endereco de bootstrap),
    sem travar a interface -- a checagem roda em QThread via start_worker,
    igual ao padrao ja usado por CompatibilityGateDialog. So vira um
    formulario visivel/interativo quando essa tentativa automatica falha.
    """

    def __init__(
        self,
        parent=None,
        *,
        config_store: DesktopApiConfigStore | None = None,
        client_factory=DesktopApiClient,
        bootstrap_url_provider=get_bootstrap_default_url,
    ):
        super().__init__(parent)
        self.store = config_store or DesktopApiConfigStore()
        self.client_factory = client_factory
        self.bootstrap_url_provider = bootstrap_url_provider
        self.proceed = False
        self.result_base_url: str | None = None
        self._checking = False
        self._testing = False
        self._known_url = ""
        self._last_tested_url: str | None = None
        self._last_test_ok = False
        self._bootstrap_thread = None
        self._test_thread = None

        self.setWindowTitle("Conexao com o servidor")
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self._build()
        style_dialog_from_parent(self, parent)
        self._start_bootstrap()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(14)

        self.message_label = QLabel(_CHECKING_MESSAGE)
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)

        self.explanation_label = QLabel(_EXPLANATION)
        self.explanation_label.setObjectName("Caption")
        self.explanation_label.setWordWrap(True)
        self.explanation_label.hide()
        layout.addWidget(self.explanation_label)

        self.field_container = QWidget()
        field_row = QHBoxLayout(self.field_container)
        field_row.setContentsMargins(0, 0, 0, 0)
        field_row.addWidget(QLabel("Endereco da API"))
        self.url_field = QLineEdit()
        self.url_field.setPlaceholderText("http://192.168.1.50:8000")
        self.url_field.textChanged.connect(self._on_field_changed)
        field_row.addWidget(self.url_field, 1)
        self.field_container.hide()
        layout.addWidget(self.field_container)

        self.status_label = QLabel("Status: ainda nao testado")
        self.status_label.setObjectName("Caption")
        self.status_label.setWordWrap(True)
        self.status_label.hide()
        layout.addWidget(self.status_label)

        footer = QHBoxLayout()
        self.retry_known_button = ModernButton("Tentar novamente", "refresh")
        self.retry_known_button.clicked.connect(self._retry_known)
        self.retry_known_button.hide()
        footer.addWidget(self.retry_known_button)
        footer.addStretch()
        self.test_button = ModernButton("Testar conexao", "refresh")
        self.test_button.clicked.connect(self._test_connection)
        self.test_button.hide()
        footer.addWidget(self.test_button)
        self.save_button = ModernButton("Salvar e continuar", "save", accent=True)
        self.save_button.clicked.connect(self._save_and_continue)
        self.save_button.setEnabled(False)
        self.save_button.hide()
        footer.addWidget(self.save_button)
        self.exit_button = ModernButton("Sair", "clear")
        self.exit_button.clicked.connect(self._on_exit)
        self.exit_button.hide()
        footer.addWidget(self.exit_button)
        layout.addLayout(footer)

    # -- checagem automatica inicial -------------------------------------------------

    def _start_bootstrap(self) -> None:
        if self._checking:
            return
        self._checking = True
        self.message_label.setText(_CHECKING_MESSAGE)
        self._bootstrap_thread = start_worker(self, self._perform_bootstrap, self._on_bootstrap_result, self._on_bootstrap_error)

    def _perform_bootstrap(self) -> BootstrapResult:
        return run_bootstrap(config_store=self.store, client_factory=self.client_factory, bootstrap_url_provider=self.bootstrap_url_provider)

    def _on_bootstrap_result(self, result: BootstrapResult) -> None:
        self._checking = False
        if result.state == BootstrapState.READY_FOR_LOGIN:
            self.proceed = True
            self.result_base_url = result.base_url
            self.accept()
            return
        self._known_url = result.base_url or ""
        self._show_form(result)

    def _on_bootstrap_error(self, exc: Exception) -> None:
        self._checking = False
        log.exception("Falha inesperada no bootstrap de primeiro acesso")
        self._show_form(None)

    def _show_form(self, result: BootstrapResult | None) -> None:
        if result is not None and result.state == BootstrapState.API_UNREACHABLE:
            detail = _ERROR_DETAILS.get(result.error_code, "")
            self.message_label.setText(f"{_UNREACHABLE_MESSAGE}\n{detail}".strip())
            self.retry_known_button.show()
        else:
            self.message_label.setText(_MISSING_MESSAGE)
        self.explanation_label.show()
        self.field_container.show()
        self.status_label.show()
        self.test_button.show()
        self.save_button.show()
        self.exit_button.show()
        self.url_field.setText(self._known_url)

    # -- interacao do usuario ---------------------------------------------------------

    def _on_field_changed(self, _text: str) -> None:
        self.save_button.setEnabled(False)
        self._last_test_ok = False

    def _retry_known(self) -> None:
        self.url_field.setText(self._known_url)
        self._test_connection()

    def _test_connection(self) -> None:
        if self._testing:
            return
        raw_value = self.url_field.text()
        try:
            normalized = normalize_api_base_url(raw_value)
        except DesktopApiConfigError as exc:
            self.status_label.setText(f"Status: {exc}")
            self.save_button.setEnabled(False)
            self._last_test_ok = False
            return

        self._testing = True
        self.test_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.status_label.setText("Status: testando...")
        self._last_tested_url = normalized
        self._test_thread = start_worker(self, lambda: probe_health(normalized, client_factory=self.client_factory), self._on_test_result, self._on_test_error)

    def _on_test_result(self, outcome: tuple[bool, BootstrapErrorCode]) -> None:
        self._testing = False
        self.test_button.setEnabled(True)
        ok, code = outcome
        self._last_test_ok = ok
        if ok:
            self.status_label.setText("Status: conexao confirmada.")
            self.save_button.setEnabled(True)
        else:
            self.status_label.setText(f"Status: falha ({_ERROR_DETAILS.get(code, 'nao foi possivel conectar')}).")
            self.save_button.setEnabled(False)

    def _on_test_error(self, exc: Exception) -> None:
        self._testing = False
        self.test_button.setEnabled(True)
        self._last_test_ok = False
        log.exception("Falha inesperada ao testar conexao no primeiro acesso")
        self.status_label.setText("Status: nao foi possivel concluir o teste agora.")
        self.save_button.setEnabled(False)

    def _save_and_continue(self) -> None:
        current = self.url_field.text().strip()
        if not self._last_test_ok or current != self._last_tested_url:
            # Falha/edicao apos o teste nao pode destruir a configuracao
            # funcional existente -- exige um novo teste bem-sucedido do
            # valor atual antes de permitir salvar (Fase 3, Secao 15).
            self.status_label.setText("Status: teste a conexao com este endereco antes de salvar.")
            return
        try:
            settings = self.store.save_settings(enabled=True, base_url=current)
        except DesktopApiConfigError as exc:
            self.status_label.setText(f"Status: {exc}")
            return
        self.proceed = True
        self.result_base_url = settings.base_url
        self.accept()

    def _on_exit(self) -> None:
        self.proceed = False
        self.reject()
