from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHeaderView, QLabel, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from app.models.fiscal_table_model import fiscal_status_label
from app.ui.format_utils import format_empty, format_quantity, format_weight_or_missing
from app.ui.table_utils import resize_rows_to_contents


class FiscalEntregaTab(QWidget):
    """Aba "Fiscal/Entrega": duas sub-secoes lado a lado.

    Fiscal reaproveita `service.fiscal_rows()`/`fiscal_emissions()` (multiplas
    notas por proposta) - sem novo bloqueio, o sistema pode emitir NF antes do
    material estar pronto, isso e regra de negocio existente e nao muda aqui.

    Entrega usa somente os campos que realmente existem para entrega ao
    cliente (`quantidade_entregue`, `saldo_pendente`, `status_expedicao`) -
    NAO existe hoje, no client, um registro de transportadora/motorista/placa
    de entrega ao cliente distinto do transporte de galvanizacao (o campo
    `motorista` que existe no sistema pertence a carga de galvanizacao, ver
    `app/services/api_proposal_storage.py::_api_galvanization_load_to_legacy`
    e a aba "Cargas"). Por isso essa sub-secao so mostra o que existe."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(2, 2, 6, 8)
        layout.setSpacing(12)

        self.fiscal_panel = self._panel("Fiscal")
        layout.addWidget(self.fiscal_panel)
        self.entrega_panel = self._panel("Entrega")
        layout.addWidget(self.entrega_panel)
        layout.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _panel(self, title: str) -> QFrame:
        panel = QFrame()
        panel.setObjectName("Panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(16, 14, 16, 14)
        panel_layout.setSpacing(8)
        label = QLabel(title)
        label.setStyleSheet("font-size: 14px; font-weight: 800;")
        panel_layout.addWidget(label)
        return panel

    def _clear(self, panel: QFrame):
        panel_layout = panel.layout()
        while panel_layout.count() > 1:
            item = panel_layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()

    def load(self, process: dict[str, Any], process_ids: list[int], history: list[dict[str, Any]]):
        self._load_fiscal(process_ids)
        self._load_entrega(process, history)

    def _load_fiscal(self, process_ids: list[int]):
        self._clear(self.fiscal_panel)
        layout = self.fiscal_panel.layout()
        try:
            all_rows = self.service.fiscal_rows({})
        except Exception:
            all_rows = []
        ids = set(int(value) for value in process_ids)
        fiscal_rows = [row for row in all_rows if int(row.get("processo_id") or 0) in ids]
        if not fiscal_rows:
            layout.addWidget(QLabel("Nenhuma movimentacao fiscal registrada."))
            return
        for fiscal_row in fiscal_rows:
            grid = QGridLayout()
            summary_rows = [
                ("Situacao fiscal", fiscal_status_label(fiscal_row.get("situacao_fiscal") or fiscal_row.get("status_fiscal") or "")),
                ("Entrada fiscal", format_empty(fiscal_row.get("data_entrada_fiscal"))),
                ("Ultima emissao", format_empty(fiscal_row.get("data_ultima_emissao"))),
                ("Quantidade de itens", format_quantity(fiscal_row.get("quantidade_itens"))),
                ("Itens faturados", format_quantity(fiscal_row.get("itens_faturados"))),
                ("Itens pendentes", format_quantity(fiscal_row.get("itens_pendentes"))),
                ("Peso total", format_weight_or_missing(fiscal_row.get("peso_total"))),
                ("Peso faturado", format_weight_or_missing(fiscal_row.get("peso_faturado"))),
                ("Peso pendente", format_weight_or_missing(fiscal_row.get("peso_pendente"))),
            ]
            for row, (field_label, value) in enumerate(summary_rows):
                left = QLabel(field_label)
                left.setObjectName("Caption")
                right = QLabel(value)
                right.setStyleSheet("font-weight: 700;")
                grid.addWidget(left, row, 0, Qt.AlignTop)
                grid.addWidget(right, row, 1)
            grid.setColumnMinimumWidth(0, 150)
            grid.setColumnStretch(1, 1)
            layout.addLayout(grid)

            fiscal_processo_id = fiscal_row.get("fiscal_processo_id")
            invoices = []
            if fiscal_processo_id:
                try:
                    invoices = self.service.fiscal_emissions(int(fiscal_processo_id))
                except Exception:
                    invoices = []
            layout.addWidget(self._invoices_table(invoices))

    def _invoices_table(self, invoices: list[dict[str, Any]]) -> QWidget:
        if not invoices:
            label = QLabel("Nenhuma nota fiscal emitida.")
            label.setObjectName("Caption")
            return label
        table = QTableWidget(len(invoices), 5)
        table.setHorizontalHeaderLabels(["Numero/Controle", "Serie", "Emissao", "Qtd. emitida", "Peso emitido"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for row, invoice in enumerate(invoices):
            values = [
                format_empty(invoice.get("numero_controle")),
                format_empty(invoice.get("serie")),
                format_empty(invoice.get("data_emissao")),
                format_quantity(invoice.get("quantidade_emitida")),
                format_weight_or_missing(invoice.get("peso_emitido")),
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value or ""))
                cell.setTextAlignment(Qt.AlignVCenter | (Qt.AlignLeft if col == 0 else Qt.AlignCenter))
                table.setItem(row, col, cell)
        resize_rows_to_contents(table)
        table.setMinimumHeight(40 + max(1, len(invoices)) * 32)
        table.setMaximumHeight(40 + max(1, min(len(invoices), 5)) * 32)
        return table

    def _load_entrega(self, process: dict[str, Any], history: list[dict[str, Any]]):
        self._clear(self.entrega_panel)
        layout = self.entrega_panel.layout()
        delivered = process.get("quantidade_entregue")
        pending = process.get("saldo_pendente")
        status = process.get("status_expedicao") or ""
        if delivered in (None, "") and pending in (None, "") and not status:
            layout.addWidget(QLabel("Nenhuma entrega registrada."))
            return
        last_delivery = self._latest_delivery_event(history)
        rows = [
            ("Status de expedicao", self.service.area_status_label("EXPEDICAO", status) if status else "-"),
            ("Quantidade entregue", format_quantity(delivered)),
            ("Saldo pendente", format_quantity(pending)),
            ("Ultima movimentacao de entrega", last_delivery),
        ]
        grid = QGridLayout()
        for row, (field_label, value) in enumerate(rows):
            left = QLabel(field_label)
            left.setObjectName("Caption")
            right = QLabel(value)
            right.setWordWrap(True)
            right.setStyleSheet("font-weight: 700;")
            grid.addWidget(left, row, 0, Qt.AlignTop)
            grid.addWidget(right, row, 1)
        grid.setColumnMinimumWidth(0, 190)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        note = QLabel(
            "Transportadora/motorista/placa nao sao registrados para a entrega ao cliente neste sistema - "
            "esses dados existem apenas para o transporte de envio/retorno de galvanizacao (aba \"Cargas\")."
        )
        note.setObjectName("Caption")
        note.setWordWrap(True)
        layout.addWidget(note)

    @staticmethod
    def _latest_delivery_event(history: list[dict[str, Any]]) -> str:
        candidates = [
            entry
            for entry in history
            if str(entry.get("area") or "").strip().upper() == "EXPEDICAO"
            and "ENTREG" in str(entry.get("status_novo") or "").upper()
        ]
        if not candidates:
            return "Sem registro"
        latest = max(candidates, key=lambda entry: str(entry.get("data_hora") or ""))
        when = format_empty(latest.get("data_hora"))
        who = latest.get("usuario")
        return f"{when} ({who})" if who else when
