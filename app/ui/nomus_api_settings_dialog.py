from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from app.services.nomus_api_config import NomusApiConfigError, NomusApiConfigStore
from app.ui.background_worker import start_worker
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import style_dialog_from_parent


class NomusIntegrationSettingsWidget(QWidget):
    """Conteudo reutilizavel da configuracao Nomus, sem janela intermediaria."""

    saved = Signal()
    cancel_requested = Signal()

    def __init__(
        self,
        parent=None,
        *,
        store: NomusApiConfigStore | None = None,
        auto_load: bool = True,
        show_header: bool = True,
        show_cancel: bool = False,
    ):
        super().__init__(parent)
        self.store = store
        self._worker_threads = []
        self._key_changed = False
        self._key_removed = False
        self._loaded = False
        self._build(show_header=show_header, show_cancel=show_cancel)
        if auto_load:
            self.ensure_loaded()

    def _build(self, *, show_header: bool, show_cancel: bool):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        if show_header:
            title = QLabel("Integracao Nomus")
            title.setStyleSheet("font-size: 20px; font-weight: 800;")
            subtitle = QLabel(
                "Configure a chave REST e valide tecnicamente o acesso. "
                "Nenhuma proposta sera importada nesta etapa."
            )
            subtitle.setObjectName("Caption")
            subtitle.setWordWrap(True)
            root.addWidget(title)
            root.addWidget(subtitle)

        form = QFrame()
        form.setObjectName("Panel")
        grid = QGridLayout(form)
        grid.setContentsMargins(18, 16, 18, 16)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(1, 1)

        self.enabled_check = QCheckBox("Ativar integracao com o Nomus")
        grid.addWidget(self.enabled_check, 0, 0, 1, 2)

        grid.addWidget(QLabel("URL base da API"), 1, 0)
        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText("https://suaempresa.nomus.com.br/suaempresa/rest")
        grid.addWidget(self.base_url, 1, 1)

        grid.addWidget(QLabel("Chave configurada"), 2, 0)
        self.key_status = QLabel("Nenhuma chave configurada")
        self.key_status.setObjectName("Caption")
        self.key_status.setWordWrap(True)
        grid.addWidget(self.key_status, 2, 1)

        grid.addWidget(QLabel("Nova chave"), 3, 0)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("Digite uma nova chave somente se desejar trocar")
        self.api_key.textEdited.connect(self._mark_key_changed)
        grid.addWidget(self.api_key, 3, 1)

        remove_row = QHBoxLayout()
        self.remove_key_btn = ModernButton("Remover chave", "delete")
        self.remove_key_btn.clicked.connect(self.remove_key)
        remove_row.addWidget(self.remove_key_btn)
        remove_row.addStretch()
        grid.addLayout(remove_row, 4, 1)
        root.addWidget(form)

        status = QFrame()
        status.setObjectName("Panel")
        status_layout = QVBoxLayout(status)
        status_layout.setContentsMargins(18, 14, 18, 14)
        status_layout.setSpacing(8)
        status_title = QLabel("Ultimo teste")
        status_title.setStyleSheet("font-weight: 800;")
        self.last_test = QLabel("Nenhum teste executado.")
        self.last_test.setWordWrap(True)
        status_layout.addWidget(status_title)
        status_layout.addWidget(self.last_test)
        root.addWidget(status)
        root.addStretch()

        footer = QHBoxLayout()
        self.test_btn = ModernButton("Testar conexao", "refresh")
        self.test_btn.clicked.connect(self.test_connection)
        footer.addWidget(self.test_btn)
        footer.addStretch()
        if show_cancel:
            cancel = ModernButton("Cancelar", "close")
            cancel.clicked.connect(self.cancel_requested)
            footer.addWidget(cancel)
        self.save_btn = ModernButton("Salvar", "save", accent=True)
        self.save_btn.clicked.connect(self.save)
        footer.addWidget(self.save_btn)
        root.addLayout(footer)

    def _get_store(self) -> NomusApiConfigStore:
        if self.store is None:
            self.store = NomusApiConfigStore()
        return self.store

    def ensure_loaded(self):
        if not self._loaded:
            self._load()

    def _load(self):
        self.settings = self._get_store().load_settings()
        self.enabled_check.setChecked(self.settings.enabled)
        self.base_url.setText(self.settings.base_url)
        self.api_key.clear()
        self._key_changed = False
        self._key_removed = False
        self._refresh_key_status()
        self._refresh_last_test()
        self._loaded = True

    def _refresh_key_status(self):
        if self._key_removed:
            self.key_status.setText("Chave marcada para remocao ao salvar.")
            self.remove_key_btn.setEnabled(False)
            return
        if self.settings.api_key_configured:
            self.key_status.setText(f"Chave configurada: {self.settings.masked_api_key}")
            self.remove_key_btn.setEnabled(True)
        else:
            self.key_status.setText("Nenhuma chave configurada")
            self.remove_key_btn.setEnabled(False)

    def _refresh_last_test(self):
        if not self.settings.last_tested_at:
            self.last_test.setText("Nenhum teste executado.")
            return
        when = self.settings.last_tested_at.strftime("%d/%m/%Y %H:%M:%S")
        status = self.settings.last_test_status or "-"
        message = self.settings.last_test_message or "-"
        self.last_test.setText(f"{when} | {status} | {message}")

    def _mark_key_changed(self):
        self._key_changed = bool(self.api_key.text().strip())
        if self._key_changed:
            self._key_removed = False
            self._refresh_key_status()

    def remove_key(self):
        self.ensure_loaded()
        if not self.settings.api_key_configured:
            return
        if QMessageBox.question(self, "Remover chave", "Deseja remover a chave da API Nomus deste computador?") != QMessageBox.Yes:
            return
        self._key_removed = True
        self._key_changed = False
        self.api_key.clear()
        self._refresh_key_status()

    def save(self):
        self.ensure_loaded()
        try:
            if self._key_removed:
                if self.enabled_check.isChecked():
                    raise NomusApiConfigError("Desative a integracao antes de remover a chave.")
                self._get_store().delete_api_key()
            elif self._key_changed:
                self._get_store().save_api_key(self.api_key.text())
            self.settings = self._get_store().save_settings(
                enabled=self.enabled_check.isChecked(),
                base_url=self.base_url.text(),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Integracao Nomus", str(exc))
            return
        QMessageBox.information(self, "Integracao Nomus", "Configuracao salva com seguranca.")
        self.api_key.clear()
        self._key_changed = False
        self._key_removed = False
        self._refresh_key_status()
        self._refresh_last_test()
        self.saved.emit()

    def test_connection(self):
        self.ensure_loaded()
        try:
            base_url = self.base_url.text()
            if self._key_changed:
                if not self.api_key.text().strip():
                    raise NomusApiConfigError("Informe uma chave da API para testar.")
            elif not self.settings.api_key_configured and not self._key_removed:
                raise NomusApiConfigError("Informe e salve uma chave da API antes de testar a integracao.")
        except NomusApiConfigError as exc:
            QMessageBox.warning(self, "Integracao Nomus", str(exc))
            return
        self.test_btn.setEnabled(False)
        self.test_btn.setText("Testando...")
        self._run_background(
            lambda: self._get_store().test_authenticated_connection(
                base_url=base_url,
                api_key_override=self.api_key.text().strip() if self._key_changed else None,
            ),
            self._show_test_result,
            self._show_test_error,
        )

    def _show_test_result(self, result):
        self.test_btn.setEnabled(True)
        self.test_btn.setText("Testar conexao")
        self.settings = self._get_store().load_settings()
        self._refresh_last_test()
        if result.success:
            QMessageBox.information(self, "Integracao Nomus", result.user_message)
        else:
            QMessageBox.warning(self, "Integracao Nomus", result.user_message)

    def _show_test_error(self, exc):
        self.test_btn.setEnabled(True)
        self.test_btn.setText("Testar conexao")
        QMessageBox.warning(self, "Integracao Nomus", f"Nao foi possivel testar a conexao agora.\n{exc}")

    def _run_background(self, operation, on_success, on_error):
        thread = start_worker(self, operation, on_success, on_error)
        self._worker_threads.append(thread)
        thread.finished.connect(
            lambda target=thread: self._worker_threads.remove(target)
            if target in self._worker_threads
            else None
        )


class NomusApiSettingsDialog(QDialog):
    """Invólucro de compatibilidade para usos legítimos fora das Configurações."""

    def __init__(self, parent=None, *, store: NomusApiConfigStore | None = None):
        super().__init__(parent)
        self.setWindowTitle("Integracao Nomus")
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        self.content = NomusIntegrationSettingsWidget(
            self,
            store=store,
            show_header=True,
            show_cancel=True,
        )
        self.content.saved.connect(self.accept)
        self.content.cancel_requested.connect(self.reject)
        root.addWidget(self.content)
        style_dialog_from_parent(self, parent)
        self.setMinimumSize(720, 460)
        self.resize(820, 520)
