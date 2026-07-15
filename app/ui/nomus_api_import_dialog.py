from __future__ import annotations

import re
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal, Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from app.services.nomus_api_client import NomusApiClient, NomusApiClientError
from app.services.nomus_api_config import NomusApiConfigStore, NomusApiSecretError
from app.services.nomus_api_importer import (
    NomusApiAmbiguousOrderError,
    NomusApiImportError,
    NomusApiImporter,
    NomusApiItemsNotFoundError,
    NomusApiOrderNotFoundError,
)
from app.services.proposal_import.compatibility import to_current_payload
from app.services.proposal_import.schemas import StandardProposalImportResult
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import style_dialog_from_parent


ImporterFactory = Callable[[], NomusApiImporter]


class _NomusImportWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, importer: NomusApiImporter, identifier: str):
        super().__init__()
        self.importer = importer
        self.identifier = identifier

    def run(self):
        try:
            self.finished.emit(self.importer.fetch_proposal(self.identifier))
        except Exception as exc:  # pragma: no cover - exercised through dialog tests synchronously
            self.failed.emit(_friendly_nomus_error(exc))


class NomusApiImportDialog(QDialog):
    """Small read-only lookup dialog for Nomus API imports.

    It only fetches operational data and returns an in-memory conference payload.
    No process is saved here.
    """

    def __init__(
        self,
        parent=None,
        *,
        config_store: NomusApiConfigStore | None = None,
        importer_factory: ImporterFactory | None = None,
        synchronous: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle("Buscar proposta no Nomus")
        self.setModal(True)
        self.setMinimumSize(520, 250)
        self.resize(560, 280)
        _center_dialog(self, parent)
        style_dialog_from_parent(self, parent)
        self.config_store = config_store
        self.importer_factory = importer_factory
        self.synchronous = synchronous
        self.standard_result: StandardProposalImportResult | None = None
        self.preview_payload: dict[str, Any] | None = None
        self._thread: QThread | None = None
        self._worker: _NomusImportWorker | None = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        title = QLabel("Importar proposta do Nomus")
        title.setStyleSheet("font-size: 18px; font-weight: 800;")
        subtitle = QLabel("Informe o numero da proposta ou ID do pedido. Nada sera salvo automaticamente.")
        subtitle.setObjectName("Caption")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        panel = QFrame()
        panel.setObjectName("Panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(14, 12, 14, 12)
        panel_layout.setSpacing(8)

        label = QLabel("Proposta ou ID")
        label.setObjectName("FieldLabel")
        self.identifier = QLineEdit()
        self.identifier.setPlaceholderText("Ex.: CP05252 ou ID interno do pedido")
        self.identifier.returnPressed.connect(self.start_lookup)
        self.status = QLabel("A consulta usa apenas dados operacionais e ignora informacoes financeiras.")
        self.status.setObjectName("Caption")
        self.status.setWordWrap(True)
        panel_layout.addWidget(label)
        panel_layout.addWidget(self.identifier)
        panel_layout.addWidget(self.status)
        root.addWidget(panel)

        actions = QHBoxLayout()
        actions.addStretch()
        self.cancel_button = ModernButton("Cancelar", "clear")
        self.search_button = ModernButton("Buscar no Nomus", "search", accent=True)
        self.cancel_button.clicked.connect(self.reject)
        self.search_button.clicked.connect(self.start_lookup)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.search_button)
        root.addLayout(actions)

    def start_lookup(self):
        identifier = self._validated_identifier()
        if not identifier:
            return
        try:
            self._ensure_configuration_ready()
            importer = self._create_importer()
        except Exception as exc:
            self._show_error(_friendly_nomus_error(exc))
            return

        self._set_loading(True)
        if self.synchronous:
            try:
                self._handle_success(importer.fetch_proposal(identifier))
            except Exception as exc:
                self._handle_error(_friendly_nomus_error(exc))
            return

        self._thread = QThread(self)
        self._worker = _NomusImportWorker(importer, identifier)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._handle_success)
        self._worker.failed.connect(self._handle_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._clear_worker)
        self._thread.start()

    def _validated_identifier(self) -> str:
        identifier = self.identifier.text().strip()
        if not identifier:
            self._show_error("Informe o numero da proposta ou ID do pedido Nomus.")
            return ""
        if len(identifier) > 80 or re.search(r"[\r\n\t]", identifier):
            self._show_error("Informe um identificador Nomus valido.")
            return ""
        return identifier

    def _ensure_configuration_ready(self):
        store = self._config_store()
        settings = store.load_settings()
        if not settings.enabled:
            raise NomusApiImportError("A integracao Nomus esta desativada nas Configuracoes.")
        if not settings.base_url:
            raise NomusApiImportError("Configure a URL da API Nomus antes de importar.")
        if not settings.api_key_configured:
            raise NomusApiImportError("Configure a chave da API Nomus antes de importar.")

    def _create_importer(self) -> NomusApiImporter:
        if self.importer_factory:
            return self.importer_factory()
        store = self._config_store()
        client = NomusApiClient(config_store=store)
        return NomusApiImporter(client)

    def _config_store(self) -> NomusApiConfigStore:
        if self.config_store is None:
            self.config_store = NomusApiConfigStore()
        return self.config_store

    def _set_loading(self, loading: bool):
        self.identifier.setEnabled(not loading)
        self.search_button.setEnabled(not loading)
        self.cancel_button.setEnabled(not loading)
        self.status.setText("Consultando o Nomus..." if loading else "")

    def _handle_success(self, result: StandardProposalImportResult):
        self.standard_result = result
        payload = to_current_payload(result)
        payload["source"] = "nomus_api"
        self.preview_payload = payload
        self._set_loading(False)
        self.accept()

    def _handle_error(self, message: str):
        self._set_loading(False)
        self._show_error(message)

    def _show_error(self, message: str):
        self.status.setObjectName("ValidationWarning")
        self.status.setText(message)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        if self.isVisible():
            QMessageBox.warning(self, "Buscar no Nomus", message)

    def _clear_worker(self):
        self._worker = None
        self._thread = None

    def reject(self):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(1500)
        super().reject()


def _friendly_nomus_error(exc: Exception) -> str:
    if isinstance(exc, NomusApiOrderNotFoundError):
        return "Nenhuma proposta foi encontrada no Nomus para o identificador informado."
    if isinstance(exc, NomusApiAmbiguousOrderError):
        return "Mais de uma proposta foi encontrada. Informe o ID interno do pedido Nomus."
    if isinstance(exc, NomusApiItemsNotFoundError):
        return "A proposta foi encontrada, mas nao retornou itens operacionais para conferencia."
    if isinstance(exc, (NomusApiClientError, NomusApiImportError, NomusApiSecretError)):
        return str(exc)
    return "Nao foi possivel consultar o Nomus agora. Verifique a configuracao, internet ou tente novamente."


def _center_dialog(dialog: QDialog, parent=None):
    reference = parent.window() if parent and parent.window() else None
    if reference:
        center = reference.geometry().center()
    else:
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        center = available.center() if available else None
    if center:
        frame = dialog.frameGeometry()
        frame.moveCenter(center)
        dialog.move(frame.topLeft())
