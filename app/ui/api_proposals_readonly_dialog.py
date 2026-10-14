from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout

from app.integrations.api.auth_client import AuthApiClient
from app.integrations.api.client import DesktopApiClient
from app.integrations.api.compatibility import compatibility_report
from app.integrations.api.config import DesktopApiConfigStore
from app.integrations.api.exceptions import ApiClientError
from app.integrations.api.proposals_client import ProposalsApiClient
from app.integrations.api.session import ExperimentalApiSession
from app.integrations.api.system_client import SystemApiClient
from app.integrations.api.token_store import ApiTokenStore
from app.ui.background_worker import start_worker
from app.ui.components.dialog_shell import dialog_header
from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import style_dialog_from_parent


class ApiProposalsReadonlyDialog(QDialog):
    def __init__(self, parent=None, *, store: DesktopApiConfigStore | None = None, token_store: ApiTokenStore | None = None):
        super().__init__(parent)
        self.setWindowTitle("Consulta de propostas pela API")
        self.store = store or DesktopApiConfigStore()
        self.token_store = token_store or ApiTokenStore()
        self._worker_threads = []
        self._access_token: str | None = None
        self._build()
        style_dialog_from_parent(self, parent)
        self.setMinimumSize(900, 620)
        self.resize(1020, 680)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        title = QLabel("Consulta oficial pela API")
        subtitle = QLabel("Fonte oficial: API / PostgreSQL.")

        filters = QFrame()
        filters.setObjectName("DetailPanel")
        grid = QGridLayout(filters)
        grid.setContentsMargins(16, 14, 16, 14)
        self.proposal = QLineEdit()
        self.customer = QLineEdit()
        self.project = QLineEdit()
        self.status = QLineEdit()
        for column, (label, widget) in enumerate((("Proposta", self.proposal), ("Cliente", self.customer), ("Site/Lote", self.project), ("Status", self.status))):
            field_label = QLabel(label)
            field_label.setObjectName("KeyLabel")
            grid.addWidget(field_label, 0, column)
            grid.addWidget(widget, 1, column)

        self.search_btn = ModernButton("Pesquisar", "search", accent=True)
        self.prev_btn = ModernButton("Anterior", "previous", variant="ghost")
        self.next_btn = ModernButton("Próximo", "next", variant="ghost")
        self.detail_btn = ModernButton("Detalhes e itens", "search")
        self.page_label = QLabel("Página 1")
        self.page_label.setObjectName("KeyLabel")
        close = ModernButton("Fechar", "close", variant="ghost")
        root.addWidget(dialog_header(title, subtitle, actions=[self.detail_btn, self.search_btn, close]))
        root.addWidget(filters)
        pager = QHBoxLayout()
        pager.addWidget(self.prev_btn)
        pager.addWidget(self.page_label)
        pager.addWidget(self.next_btn)
        pager.addStretch()
        root.addLayout(pager)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["ID legado", "Proposta", "Cliente", "Site", "Lote", "Área", "Status", "Sincronizado em"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        root.addWidget(self.table, 1)

        self.detail = QTableWidget(0, 7)
        self.detail.setHorizontalHeaderLabels(["Item", "Código", "Descrição", "Qtd.", "Peso unit.", "Peso total", "Fluxo"])
        self.detail.verticalHeader().setVisible(False)
        self.detail.setWordWrap(True)
        self.detail.setEditTriggers(QTableWidget.NoEditTriggers)
        items_title = QLabel("Itens da proposta selecionada")
        items_title.setObjectName("PanelTitle")
        root.addWidget(items_title)
        root.addWidget(self.detail, 1)

        self.search_btn.clicked.connect(self.search)
        self.prev_btn.clicked.connect(self.previous_page)
        self.next_btn.clicked.connect(self.next_page)
        self.detail_btn.clicked.connect(self.load_details)
        close.clicked.connect(self.accept)
        self.offset = 0
        self.limit = 50
        self.total = 0

    def search(self):
        self.offset = 0
        self._run_background(self._load_page, self._show_page, self._show_error)

    def previous_page(self):
        self.offset = max(0, self.offset - self.limit)
        self._run_background(self._load_page, self._show_page, self._show_error)

    def next_page(self):
        if self.offset + self.limit < self.total:
            self.offset += self.limit
        self._run_background(self._load_page, self._show_page, self._show_error)

    def load_details(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Consulta API", "Selecione uma proposta.")
            return
        proposal_id = int(self.table.item(row, 0).data(Qt.UserRole))
        self._run_background(lambda: self._load_items(proposal_id), self._show_items, self._show_error)

    def _client_and_token(self):
        settings = self.store.load_settings()
        if not settings.enabled:
            raise ApiClientError("disabled", "A integracao com a API esta desabilitada.")
        client = DesktopApiClient(settings)
        version = SystemApiClient(client).version()
        features = set(version.supported_features)
        required = {"proposals_read", "proposal_items_read"}
        if not required.issubset(features):
            report = compatibility_report(version)
            missing = ", ".join(sorted(required - features)) or ", ".join(report.missing_features)
            client.close()
            raise ApiClientError("incompatible", f"A API nao possui os recursos de propostas: {missing}.")
        if not self._access_token:
            session = ExperimentalApiSession(settings=settings, auth_client=AuthApiClient(client), token_store=self.token_store)
            self._access_token = session.refresh_if_needed(force=True).access_token
        if not self._access_token:
            client.close()
            raise ApiClientError("session_missing", "Faça login experimental no Diagnóstico da API antes de consultar propostas.")
        return client, self._access_token

    def _load_page(self):
        client, token = self._client_and_token()
        try:
            return ProposalsApiClient(client).list_proposals(
                token,
                proposal_number=self.proposal.text().strip(),
                customer=self.customer.text().strip(),
                project=self.project.text().strip(),
                current_status=self.status.text().strip(),
                limit=self.limit,
                offset=self.offset,
            )
        finally:
            client.close()

    def _load_items(self, proposal_id: int):
        client, token = self._client_and_token()
        try:
            return ProposalsApiClient(client).list_items(token, proposal_id)
        finally:
            client.close()

    def _show_page(self, data):
        self.total = int(data.get("total") or 0)
        rows = data.get("items") or []
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [row.get("legacy_id"), row.get("proposal_number"), row.get("customer_name"), row.get("project_name"), row.get("lot"), row.get("current_area"), row.get("current_status"), row.get("synced_at")]
            for column, value in enumerate(values):
                item = QTableWidgetItem("" if value is None else str(value))
                if column == 0:
                    item.setData(Qt.UserRole, int(row.get("id")))
                self.table.setItem(row_index, column, item)
        self.table.resizeColumnsToContents()
        self.page_label.setText(f"{self.offset + 1}-{min(self.offset + self.limit, self.total)} de {self.total}")

    def _show_items(self, rows):
        self.detail.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            flow = f"Prod: {row.get('produce_internally')} | Galv: {row.get('requires_galvanization')}"
            values = [row.get("item_number"), row.get("product_code"), row.get("description"), row.get("quantity"), row.get("unit_weight"), row.get("total_weight"), flow]
            for column, value in enumerate(values):
                self.detail.setItem(row_index, column, QTableWidgetItem("" if value is None else str(value)))
        self.detail.resizeColumnsToContents()
        self.detail.resizeRowsToContents()

    def _show_error(self, exc):
        message = exc.user_message if isinstance(exc, ApiClientError) else "Não foi possível consultar propostas pela API."
        QMessageBox.warning(self, "Consulta API", message)

    def _run_background(self, operation, on_success, on_error):
        thread = start_worker(self, operation, on_success, on_error)
        self._worker_threads.append(thread)
        thread.finished.connect(lambda target=thread: self._worker_threads.remove(target) if target in self._worker_threads else None)
