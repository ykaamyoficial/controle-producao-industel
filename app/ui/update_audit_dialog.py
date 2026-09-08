"""Tela administrativa somente leitura de auditoria de atualizacoes (Fase 16,
Secao 27). Sem nenhum botao operacional -- so consulta o historico ja
persistido pelo servidor (api.app.modules.update_audit.router)."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from app.integrations.api.auth_client import AuthApiClient
from app.integrations.api.client import DesktopApiClient
from app.integrations.api.config import DesktopApiConfigStore
from app.integrations.api.exceptions import ApiClientError
from app.integrations.api.session import ExperimentalApiSession
from app.integrations.api.token_store import ApiTokenStore
from app.integrations.api.update_audit_client import UpdateAuditApiClient
from app.ui.background_worker import start_worker
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import style_dialog_from_parent

_RESULT_BADGE = {
    "SUCCEEDED": "#16a34a",
    "FAILED": "#dc2626",
    "ROLLED_BACK": "#d97706",
    "BLOCKED": "#dc2626",
    "REVOKED": "#dc2626",
    "REQUIRES_MANUAL_INTERVENTION": "#dc2626",
    "STARTED": "#64748b",
    "CANCELLED": "#64748b",
    "SKIPPED": "#64748b",
    "PARTIAL": "#d97706",
}


class EventDetailDialog(QDialog):
    def __init__(self, event: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Evento {event.get('event_type', '')}")
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText(json.dumps(event, indent=2, ensure_ascii=False, sort_keys=True))
        layout.addWidget(text)
        close = ModernButton("Fechar", "close")
        close.clicked.connect(self.accept)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(close)
        layout.addLayout(footer)
        self.resize(560, 480)
        style_dialog_from_parent(self, parent)


class UpdateAuditDialog(QDialog):
    """Fase 16, Secao 27: cards pequenos + tabela de eventos com filtros +
    detalhe ao duplo clique + timeline por correlation_id. Nenhum botao
    operacional -- estritamente somente leitura."""

    def __init__(self, parent=None, *, store: DesktopApiConfigStore | None = None, token_store: ApiTokenStore | None = None):
        super().__init__(parent)
        self.setWindowTitle("Auditoria de atualizacoes")
        self.store = store or DesktopApiConfigStore()
        self.token_store = token_store or ApiTokenStore()
        self._worker_threads: list = []
        self._access_token: str | None = None
        self._rows: list[dict] = []
        self._timeline_mode = False
        self._build()
        style_dialog_from_parent(self, parent)
        self.setMinimumSize(980, 640)
        self.resize(1080, 700)
        self.search()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel("Auditoria de atualizacoes")
        title.setStyleSheet("font-size: 20px; font-weight: 800;")
        subtitle = QLabel("Historico oficial de releases, deploys, manutencao e canais -- somente leitura.")
        subtitle.setObjectName("Caption")
        subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(subtitle)

        self.summary_label = QLabel("")
        self.summary_label.setObjectName("Caption")
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)

        filters = QFrame()
        filters.setObjectName("Panel")
        grid = QGridLayout(filters)
        grid.setContentsMargins(14, 12, 14, 12)
        self.event_type = QLineEdit()
        self.event_type.setPlaceholderText("ex.: DEPLOYMENT_FAILED")
        self.result = QLineEdit()
        self.result.setPlaceholderText("ex.: FAILED")
        self.channel = QLineEdit()
        self.version = QLineEdit()
        self.installation_id = QLineEdit()
        fields = (
            ("Tipo de evento", self.event_type), ("Resultado", self.result), ("Canal", self.channel),
            ("Versao", self.version), ("Installation ID", self.installation_id),
        )
        for column, (label, widget) in enumerate(fields):
            grid.addWidget(QLabel(label), 0, column)
            grid.addWidget(widget, 1, column)
        root.addWidget(filters)

        buttons = QHBoxLayout()
        self.search_btn = ModernButton("Pesquisar", "search", accent=True)
        self.prev_btn = ModernButton("Anterior", "previous")
        self.next_btn = ModernButton("Proximo", "next")
        self.timeline_btn = ModernButton("Ver linha do tempo", "search")
        self.clear_timeline_btn = ModernButton("Limpar filtro de linha do tempo", "refresh")
        self.clear_timeline_btn.hide()
        self.page_label = QLabel("Pagina 1")
        buttons.addWidget(self.search_btn)
        buttons.addWidget(self.prev_btn)
        buttons.addWidget(self.next_btn)
        buttons.addWidget(self.timeline_btn)
        buttons.addWidget(self.clear_timeline_btn)
        buttons.addWidget(self.page_label)
        buttons.addStretch()
        close = ModernButton("Fechar", "close")
        buttons.addWidget(close)
        root.addLayout(buttons)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["Quando (UTC)", "Tipo", "Componente", "Resultado", "Versao", "Canal", "Instalacao", "Mensagem"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.doubleClicked.connect(self.show_selected_detail)
        root.addWidget(self.table, 1)

        self.search_btn.clicked.connect(self.search)
        self.prev_btn.clicked.connect(self.previous_page)
        self.next_btn.clicked.connect(self.next_page)
        self.timeline_btn.clicked.connect(self.show_timeline)
        self.clear_timeline_btn.clicked.connect(self.clear_timeline_filter)
        close.clicked.connect(self.accept)
        self.offset = 0
        self.limit = 50
        self.total = 0
        self._active_correlation_id: str | None = None

    # -- carregamento -----------------------------------------------------

    def search(self) -> None:
        self.offset = 0
        self._active_correlation_id = None
        self._timeline_mode = False
        self.clear_timeline_btn.hide()
        self._run_background(self._load_page, self._show_page, self._show_error)

    def previous_page(self) -> None:
        self.offset = max(0, self.offset - self.limit)
        self._run_background(self._load_page, self._show_page, self._show_error)

    def next_page(self) -> None:
        if self.offset + self.limit < self.total:
            self.offset += self.limit
        self._run_background(self._load_page, self._show_page, self._show_error)

    def show_timeline(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows):
            QMessageBox.warning(self, "Auditoria", "Selecione um evento para ver a linha do tempo.")
            return
        correlation_id = self._rows[row].get("correlation_id")
        if not correlation_id:
            QMessageBox.information(self, "Auditoria", "Este evento nao possui correlation_id.")
            return
        self._active_correlation_id = correlation_id
        self._timeline_mode = True
        self.clear_timeline_btn.show()
        self._run_background(lambda: self._load_timeline(correlation_id), self._show_page, self._show_error)

    def clear_timeline_filter(self) -> None:
        self.search()

    def show_selected_detail(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._rows):
            return
        EventDetailDialog(self._rows[row], self).exec()

    def _client_and_token(self):
        settings = self.store.load_settings()
        if not settings.enabled:
            raise ApiClientError("disabled", "A integracao com a API esta desabilitada.")
        client = DesktopApiClient(settings)
        if not self._access_token:
            session = ExperimentalApiSession(settings=settings, auth_client=AuthApiClient(client), token_store=self.token_store)
            self._access_token = session.refresh_if_needed(force=True).access_token
        if not self._access_token:
            client.close()
            raise ApiClientError("session_missing", "Faca login antes de consultar a auditoria de atualizacoes.")
        return client, self._access_token

    def _load_page(self) -> dict:
        client, token = self._client_and_token()
        try:
            return UpdateAuditApiClient(client).list_events(
                token,
                event_type=self.event_type.text().strip() or None,
                result=self.result.text().strip() or None,
                channel=self.channel.text().strip() or None,
                version=self.version.text().strip() or None,
                installation_id=self.installation_id.text().strip() or None,
                limit=self.limit, offset=self.offset,
            )
        finally:
            client.close()

    def _load_timeline(self, correlation_id: str) -> dict:
        client, token = self._client_and_token()
        try:
            return UpdateAuditApiClient(client).get_timeline(token, correlation_id)
        finally:
            client.close()

    def _show_page(self, data: dict) -> None:
        self.total = int(data.get("total") or 0)
        rows = data.get("items") or []
        self._rows = rows
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row.get("occurred_at"), row.get("event_type"), row.get("component"), row.get("result"),
                row.get("version"), row.get("channel"), row.get("installation_id"), row.get("message"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem("" if value is None else str(value))
                if column == 3:
                    color = _RESULT_BADGE.get(str(value), "#334155")
                    item.setForeground(Qt.GlobalColor.white)
                    item.setBackground(_qcolor(color))
                self.table.setItem(row_index, column, item)
        self.table.resizeColumnsToContents()
        if self._timeline_mode:
            self.page_label.setText(f"Linha do tempo: {len(rows)} evento(s)")
        else:
            shown_to = min(self.offset + self.limit, self.total) if self.total else 0
            self.page_label.setText(f"{self.offset + 1 if rows else 0}-{shown_to} de {self.total}")
        self.summary_label.setText(self._summary_text(rows))

    def _summary_text(self, rows: list[dict]) -> str:
        if not rows:
            return "Nenhum evento encontrado para os filtros atuais."
        latest = rows[0]
        return f"Evento mais recente na pagina: {latest.get('event_type')} ({latest.get('result')}) em {latest.get('occurred_at')}."

    def _show_error(self, exc: Exception) -> None:
        message = exc.user_message if isinstance(exc, ApiClientError) else "Nao foi possivel consultar a auditoria de atualizacoes."
        QMessageBox.warning(self, "Auditoria de atualizacoes", message)

    def _run_background(self, operation, on_success, on_error) -> None:
        thread = start_worker(self, operation, on_success, on_error)
        self._worker_threads.append(thread)
        thread.finished.connect(lambda target=thread: self._worker_threads.remove(target) if target in self._worker_threads else None)


def _qcolor(hex_value: str):
    from PySide6.QtGui import QColor

    return QColor(hex_value)
