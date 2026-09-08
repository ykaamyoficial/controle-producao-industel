from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from app.integrations.api.auth_client import AuthApiClient
from app.integrations.api.client import DesktopApiClient
from app.integrations.api.compatibility import compatibility_report
from app.integrations.api.config import DesktopApiConfigError, DesktopApiConfigStore
from app.integrations.api.exceptions import ApiClientError
from app.integrations.api.session import ExperimentalApiSession
from app.integrations.api.system_client import SystemApiClient
from app.integrations.api.token_store import ApiTokenStore
from app.services.app_logging import get_logger
from app.services.diagnostic_service import (
    DiagnosticResult,
    DiagnosticStatus,
    build_report_text,
    run_diagnostics,
)
from app.ui.background_worker import start_worker
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import style_dialog_from_parent

log = get_logger("api_diagnostic_dialog")

_STATUS_MARKERS = {
    DiagnosticStatus.OK: "OK",
    DiagnosticStatus.WARNING: "ATENCAO",
    DiagnosticStatus.ERROR: "ERRO",
    DiagnosticStatus.NOT_TESTED: "NAO TESTADO",
}
_OVERALL_LABELS = {
    DiagnosticStatus.OK: "OK",
    DiagnosticStatus.WARNING: "ATENCAO",
    DiagnosticStatus.ERROR: "ERRO",
    DiagnosticStatus.NOT_TESTED: "NAO EXECUTADO",
}


class ApiDiagnosticDialog(QDialog):
    def __init__(self, parent=None, *, store: DesktopApiConfigStore | None = None, token_store: ApiTokenStore | None = None, diagnostic_client_factory=DesktopApiClient):
        super().__init__(parent)
        self.setWindowTitle("Diagnostico da API")
        self.store = store or DesktopApiConfigStore()
        self.token_store = token_store
        self.diagnostic_client_factory = diagnostic_client_factory
        self._worker_threads = []
        self._session: ExperimentalApiSession | None = None
        self._diagnostic_result: DiagnosticResult | None = None
        self._diagnostic_running = False
        self._diagnostic_thread = None
        self._closing = False
        self._build()
        self._load()
        style_dialog_from_parent(self, parent)
        self.setMinimumSize(760, 620)
        self.resize(860, 700)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)

        title = QLabel("Diagnostico da API")
        title.setStyleSheet("font-size: 20px; font-weight: 800;")
        subtitle = QLabel("Validacao da API oficial usada pelo desktop.")
        subtitle.setObjectName("Caption")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        diag_panel = QFrame()
        diag_panel.setObjectName("Panel")
        diag_layout = QVBoxLayout(diag_panel)
        diag_layout.setContentsMargins(18, 16, 18, 16)
        diag_layout.setSpacing(8)

        diag_title = QLabel("Diagnostico de conexao")
        diag_title.setStyleSheet("font-size: 15px; font-weight: 800;")
        diag_layout.addWidget(diag_title)

        self.diag_status_label = QLabel("Status geral: nao executado")
        diag_layout.addWidget(self.diag_status_label)
        self.diag_server_label = QLabel("Servidor configurado: -")
        self.diag_server_label.setObjectName("Caption")
        diag_layout.addWidget(self.diag_server_label)
        self.diag_meta_label = QLabel("Ultimo teste: nunca")
        self.diag_meta_label.setObjectName("Caption")
        diag_layout.addWidget(self.diag_meta_label)

        diag_actions = QHBoxLayout()
        diag_actions.setSpacing(10)
        self.diag_run_button = ModernButton("Executar diagnostico", "refresh", accent=True)
        self.diag_run_button.clicked.connect(self.run_diagnostic)
        self.diag_copy_button = ModernButton("Copiar relatorio", "save")
        self.diag_copy_button.clicked.connect(self.copy_diagnostic_report)
        self.diag_copy_button.setEnabled(False)
        diag_actions.addWidget(self.diag_run_button)
        diag_actions.addWidget(self.diag_copy_button)
        diag_actions.addStretch()
        diag_layout.addLayout(diag_actions)

        self.diag_checks_list = QListWidget()
        self.diag_checks_list.setMinimumHeight(150)
        self.diag_checks_list.setMaximumHeight(210)
        diag_layout.addWidget(self.diag_checks_list)

        root.addWidget(diag_panel)

        form = QFrame()
        form.setObjectName("Panel")
        grid = QGridLayout(form)
        grid.setContentsMargins(18, 16, 18, 16)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        self.enabled_check = QCheckBox("Ativar integracao oficial com a API")
        grid.addWidget(self.enabled_check, 0, 0, 1, 2)
        grid.addWidget(QLabel("URL da API"), 1, 0)
        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText("http://127.0.0.1:8000")
        grid.addWidget(self.base_url, 1, 1)
        grid.addWidget(QLabel("Timeout conexao"), 2, 0)
        self.connect_timeout = QLineEdit()
        grid.addWidget(self.connect_timeout, 2, 1)
        grid.addWidget(QLabel("Timeout leitura"), 3, 0)
        self.read_timeout = QLineEdit()
        grid.addWidget(self.read_timeout, 3, 1)

        self.status_label = QLabel("Nenhum teste executado.")
        self.status_label.setObjectName("Caption")
        self.status_label.setWordWrap(True)
        grid.addWidget(QLabel("Status"), 4, 0)
        grid.addWidget(self.status_label, 4, 1)
        root.addWidget(form)

        auth = QFrame()
        auth.setObjectName("Panel")
        auth_grid = QGridLayout(auth)
        auth_grid.setContentsMargins(18, 16, 18, 16)
        auth_grid.setHorizontalSpacing(12)
        auth_grid.setVerticalSpacing(10)
        auth_grid.setColumnStretch(1, 1)
        auth_grid.addWidget(QLabel("Usuario API"), 0, 0)
        self.username = QLineEdit()
        auth_grid.addWidget(self.username, 0, 1)
        auth_grid.addWidget(QLabel("Senha API"), 1, 0)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        auth_grid.addWidget(self.password, 1, 1)
        root.addWidget(auth)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMinimumHeight(150)
        root.addWidget(self.output, 1)

        actions = QHBoxLayout()
        self.save_btn = ModernButton("Salvar", "save", accent=True)
        self.health_btn = ModernButton("Testar conexao", "refresh")
        self.compat_btn = ModernButton("Testar compatibilidade", "settings")
        self.login_btn = ModernButton("Testar autenticacao", "users", accent=True)
        self.refresh_btn = ModernButton("Renovar sessao", "refresh")
        self.logout_btn = ModernButton("Encerrar sessao", "close")
        self.logout_all_btn = ModernButton("Encerrar todas", "delete")
        self.clear_btn = ModernButton("Limpar local", "delete")
        for button in (self.save_btn, self.health_btn, self.compat_btn, self.login_btn, self.refresh_btn, self.logout_btn, self.logout_all_btn, self.clear_btn):
            actions.addWidget(button)
        actions.addStretch()
        close = ModernButton("Fechar", "close")
        actions.addWidget(close)
        root.addLayout(actions)

        self.save_btn.clicked.connect(self.save)
        self.health_btn.clicked.connect(self.test_connection)
        self.compat_btn.clicked.connect(self.test_compatibility)
        self.login_btn.clicked.connect(self.test_login)
        self.refresh_btn.clicked.connect(self.refresh_session)
        self.logout_btn.clicked.connect(self.logout)
        self.logout_all_btn.clicked.connect(self.logout_all)
        self.clear_btn.clicked.connect(self.clear_local_session)
        close.clicked.connect(self.accept)

    def _load(self):
        self.settings = self.store.load_settings()
        self.enabled_check.setChecked(self.settings.enabled)
        self.base_url.setText(self.settings.base_url)
        self.connect_timeout.setText(str(self.settings.connect_timeout))
        self.read_timeout.setText(str(self.settings.read_timeout))
        self._refresh_status()
        server_label = self.settings.base_url if self.store.is_configured() else "nao configurado"
        self.diag_server_label.setText(f"Servidor configurado: {server_label}")

    def run_diagnostic(self):
        if self._closing or self._diagnostic_running:
            return
        self._diagnostic_running = True
        self.diag_run_button.setEnabled(False)
        self.diag_copy_button.setEnabled(False)
        self.diag_status_label.setText("Status geral: verificando...")
        self.diag_checks_list.clear()
        self._diagnostic_thread = start_worker(
            self,
            lambda: run_diagnostics(config_store=self.store, client_factory=self.diagnostic_client_factory),
            self._on_diagnostic_result,
            self._on_diagnostic_error,
        )

    def _on_diagnostic_result(self, result: DiagnosticResult) -> None:
        if self._closing:
            return
        self._diagnostic_running = False
        self.diag_run_button.setEnabled(True)
        self.diag_copy_button.setEnabled(True)
        self._diagnostic_result = result
        self._load()  # atualiza "Servidor configurado" caso o bootstrap/outra tela tenha alterado a config.

        self.diag_status_label.setText(f"Status geral: {_OVERALL_LABELS[result.overall_status]}")
        when = result.started_at.astimezone().strftime("%d/%m/%Y %H:%M:%S")
        self.diag_meta_label.setText(f"Ultimo teste: {when} | Tempo total: {result.duration_ms} ms")

        self.diag_checks_list.clear()
        for check in result.checks:
            marker = _STATUS_MARKERS[check.status]
            text = f"[{marker}] {check.label} - {check.detail}"
            if check.status == DiagnosticStatus.ERROR and check.recommendation:
                text += f" | Sugestao: {check.recommendation}"
            item = QListWidgetItem(text)
            self.diag_checks_list.addItem(item)

        self._append(f"Diagnostico executado: {result.overall_status.value} | {result.user_message}")

    def _on_diagnostic_error(self, exc: Exception) -> None:
        if self._closing:
            return
        self._diagnostic_running = False
        self.diag_run_button.setEnabled(True)
        self.diag_status_label.setText("Status geral: falha ao executar diagnostico")
        log.exception("Falha inesperada ao executar o diagnostico completo")

    def copy_diagnostic_report(self):
        if self._diagnostic_result is None:
            return
        report = build_report_text(self._diagnostic_result)
        QApplication.clipboard().setText(report)
        self._append("Relatorio de diagnostico copiado para a area de transferencia.")

    def _refresh_status(self):
        if not self.settings.last_tested_at:
            self.status_label.setText("Integracao desabilitada por padrao. Nenhum teste executado.")
            return
        when = self.settings.last_tested_at.strftime("%d/%m/%Y %H:%M:%S")
        self.status_label.setText(f"{when} | {self.settings.last_test_status or '-'} | {self.settings.last_test_message or '-'}")

    def save(self):
        try:
            self.settings = self.store.save_settings(
                enabled=self.enabled_check.isChecked(),
                base_url=self.base_url.text(),
                connect_timeout=float(self.connect_timeout.text().replace(",", ".")),
                read_timeout=float(self.read_timeout.text().replace(",", ".")),
            )
        except (ValueError, DesktopApiConfigError) as exc:
            QMessageBox.warning(self, "Diagnostico da API", str(exc))
            return
        self._append("Configuracao salva. Integracao habilitada: %s" % ("sim" if self.settings.enabled else "nao"))
        self._refresh_status()

    def test_connection(self):
        self._run_api_task("Testar conexao", self._test_connection)

    def test_compatibility(self):
        self._run_api_task("Testar compatibilidade", self._test_compatibility)

    def test_login(self):
        if not self.username.text().strip() or not self.password.text():
            QMessageBox.warning(self, "Diagnostico da API", "Informe usuario e senha da API para o teste experimental.")
            return
        self._run_api_task("Testar autenticacao", lambda: self._test_login(self.username.text(), self.password.text()))

    def refresh_session(self):
        self._run_api_task("Renovar sessao", self._refresh_session)

    def logout(self):
        self._run_api_task("Encerrar sessao", self._logout)

    def logout_all(self):
        self._run_api_task("Encerrar todas", self._logout_all)

    def clear_local_session(self):
        store = self.token_store or ApiTokenStore()
        store.clear()
        self._session = None
        self._append("Sessao experimental local limpa.")

    def _test_connection(self) -> str:
        settings = self._settings_from_fields()
        with _api_client(settings) as client:
            system = SystemApiClient(client)
            health = system.health()
            ready = system.readiness()
            message = f"Health: {health.get('status')} | Ready: {ready.get('status')} | Banco: {ready.get('database')}"
            self.store.record_test_result(status="success", message=message)
            return message

    def _test_compatibility(self) -> str:
        settings = self._settings_from_fields()
        with _api_client(settings) as client:
            version = SystemApiClient(client).version()
            result = compatibility_report(version)
            status = "compativel" if result.compatible else "incompativel"
            message = f"{status}: API {version.api_version} | etapa {version.api_stage} | banco {version.database_status}"
            self.store.record_test_result(status=result.status, message=message)
            return message

    def _test_login(self, username: str, password: str) -> str:
        settings = self._settings_from_fields()
        if not settings.enabled:
            raise ApiClientError("disabled", "Ative a integracao antes de testar autenticacao.")
        client = DesktopApiClient(settings)
        auth = AuthApiClient(client)
        self._session = ExperimentalApiSession(settings=settings, auth_client=auth, token_store=self.token_store or ApiTokenStore())
        state = self._session.start(username, password)
        user = state.authenticated_user
        permissions = ", ".join(user.permissions[:12]) if user else "-"
        return f"Autenticado: {user.display_name if user else '-'} ({user.username if user else '-'}) | permissoes: {permissions}"

    def _refresh_session(self) -> str:
        if not self._session:
            raise ApiClientError("session_missing", "Nenhuma sessao experimental ativa para renovar.")
        state = self._session.refresh_if_needed(force=True)
        user = state.authenticated_user
        return f"Sessao renovada para {user.username if user else '-'}."

    def _logout(self) -> str:
        if not self._session:
            self.clear_local_session()
            return "Sessao local limpa. Nao havia sessao remota ativa."
        self._session.logout()
        self._session = None
        return "Sessao experimental encerrada."

    def _logout_all(self) -> str:
        if not self._session:
            self.clear_local_session()
            return "Sessao local limpa. Nao havia sessao remota ativa."
        self._session.logout_all()
        self._session = None
        return "Todas as sessoes da API foram encerradas para o usuario experimental."

    def _settings_from_fields(self):
        return self.store.save_settings(
            enabled=self.enabled_check.isChecked(),
            base_url=self.base_url.text(),
            connect_timeout=float(self.connect_timeout.text().replace(",", ".")),
            read_timeout=float(self.read_timeout.text().replace(",", ".")),
        )

    def _run_api_task(self, label: str, operation):
        if self._closing:
            return
        for button in (self.health_btn, self.compat_btn, self.login_btn, self.refresh_btn, self.logout_btn, self.logout_all_btn):
            button.setEnabled(False)
        self._append(f"{label} iniciado...")
        self._run_background(operation, self._show_result, self._show_error)

    def _show_result(self, result):
        if self._closing:
            return
        self._set_buttons_enabled(True)
        self.password.clear()
        self.settings = self.store.load_settings()
        self._refresh_status()
        self._append(str(result))

    def _show_error(self, exc):
        if self._closing:
            return
        self._set_buttons_enabled(True)
        self.password.clear()
        if isinstance(exc, ApiClientError):
            suffix = f" | Codigo de diagnostico: {exc.request_id}" if exc.request_id else ""
            self._append(f"Falha: {exc.user_message}{suffix}")
            QMessageBox.warning(self, "Diagnostico da API", f"{exc.user_message}{suffix}")
            return
        self._append("Falha: resposta nao pode ser validada.")
        QMessageBox.warning(self, "Diagnostico da API", "Nao foi possivel concluir o teste agora.")

    def _set_buttons_enabled(self, enabled: bool):
        for button in (self.health_btn, self.compat_btn, self.login_btn, self.refresh_btn, self.logout_btn, self.logout_all_btn):
            button.setEnabled(enabled)

    def _append(self, message: str):
        when = datetime.now().strftime("%H:%M:%S")
        self.output.appendPlainText(f"{when} | {message}")

    def _run_background(self, operation, on_success, on_error):
        if self._closing:
            return
        thread = start_worker(self, operation, on_success, on_error)
        self._worker_threads.append(thread)
        thread.finished.connect(lambda target=thread: self._worker_threads.remove(target) if target in self._worker_threads else None)

    def cleanup(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._diagnostic_running = False
        threads = list(self._worker_threads)
        if self._diagnostic_thread is not None:
            threads.append(self._diagnostic_thread)
        self._worker_threads.clear()
        self._diagnostic_thread = None
        for thread in threads:
            try:
                if thread.isRunning():
                    thread.quit()
                    thread.wait(3000)
            except RuntimeError:
                pass

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)

    def event(self, event):
        if event.type() == QEvent.Type.DeferredDelete:
            self.cleanup()
        return super().event(event)


class _api_client:
    def __init__(self, settings):
        self.client = DesktopApiClient(settings)

    def __enter__(self):
        return self.client

    def __exit__(self, _exc_type, _exc, _tb):
        self.client.close()
