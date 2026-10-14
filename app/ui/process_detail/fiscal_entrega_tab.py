from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHeaderView, QLabel, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from app.models.fiscal_table_model import fiscal_status_label
from app.ui.components.detail_widgets import (
    IconChip,
    ThinProgressBar,
    block_grid,
    clear_panel,
    key_label,
    kv_grid,
    make_panel,
    note_box,
)
from app.ui.format_utils import format_empty, format_quantity, format_weight_or_missing
from app.ui.numeric_utils import parse_decimal
from app.ui.styles import area_color
from app.ui.table_utils import resize_rows_to_contents


class FiscalEntregaTab(QWidget):
    """Aba "Fiscal/Entrega": dois paineis, um embaixo do outro.

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
        layout.setContentsMargins(0, 0, 8, 8)
        layout.setSpacing(12)

        palette = self.service.palette
        self.fiscal_panel, _ = make_panel("Fiscal", left=IconChip("fiscal", area_color("FISCAL", palette)))
        layout.addWidget(self.fiscal_panel)
        self.entrega_panel, _ = make_panel("Entrega", left=IconChip("expedition", area_color("EXPEDICAO", palette)))
        layout.addWidget(self.entrega_panel)
        layout.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def load(self, process: dict[str, Any], process_ids: list[int], history: list[dict[str, Any]]):
        self._load_fiscal(process_ids)
        self._load_entrega(process, history)

    def _load_fiscal(self, process_ids: list[int]):
        clear_panel(self.fiscal_panel)
        layout = self.fiscal_panel.layout()
        try:
            all_rows = self.service.fiscal_rows({})
        except Exception:
            all_rows = []
        ids = set(int(value) for value in process_ids)
        fiscal_rows = [row for row in all_rows if int(row.get("processo_id") or 0) in ids]
        if not fiscal_rows:
            layout.addWidget(key_label("Nenhuma movimentação fiscal registrada."))
            return
        for fiscal_row in fiscal_rows:
            summary_rows = [
                ("Situação fiscal", fiscal_status_label(fiscal_row.get("situacao_fiscal") or fiscal_row.get("status_fiscal") or "")),
                ("Entrada fiscal", format_empty(fiscal_row.get("data_entrada_fiscal"))),
                ("Última emissão", format_empty(fiscal_row.get("data_ultima_emissao"))),
                ("Quantidade de itens", format_quantity(fiscal_row.get("quantidade_itens"))),
                ("Itens faturados", format_quantity(fiscal_row.get("itens_faturados"))),
                ("Itens pendentes", format_quantity(fiscal_row.get("itens_pendentes"))),
                ("Peso total", format_weight_or_missing(fiscal_row.get("peso_total"))),
                ("Peso faturado", format_weight_or_missing(fiscal_row.get("peso_faturado"))),
                ("Peso pendente", format_weight_or_missing(fiscal_row.get("peso_pendente"))),
            ]
            layout.addLayout(block_grid(summary_rows, 3))
            self._add_invoiced_progress(layout, fiscal_row)

            fiscal_processo_id = fiscal_row.get("fiscal_processo_id")
            invoices = []
            if fiscal_processo_id:
                try:
                    invoices = self.service.fiscal_emissions(int(fiscal_processo_id))
                except Exception:
                    invoices = []
            layout.addWidget(self._invoices_table(invoices))

    @staticmethod
    def _add_invoiced_progress(layout, fiscal_row: dict[str, Any]) -> None:
        """Barra "X de Y itens faturados" - so quando os dois numeros existem."""
        try:
            total = parse_decimal(fiscal_row.get("quantidade_itens"), "0")
            invoiced = parse_decimal(fiscal_row.get("itens_faturados"), "0")
        except Exception:
            return
        if total <= 0:
            return
        fraction = max(0.0, min(1.0, float(invoiced / total)))
        layout.addWidget(
            key_label(
                f"{format_quantity(fiscal_row.get('itens_faturados') or 0)} de "
                f"{format_quantity(fiscal_row.get('quantidade_itens'))} itens faturados ({round(fraction * 100)}%)"
            )
        )
        layout.addWidget(ThinProgressBar(fraction))

    def _invoices_table(self, invoices: list[dict[str, Any]]) -> QWidget:
        if not invoices:
            return key_label("Nenhuma nota fiscal emitida.")
        table = QTableWidget(len(invoices), 5)
        table.setHorizontalHeaderLabels(["Número/Controle", "Série", "Emissão", "Qtd. emitida", "Peso emitido"])
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(40)
        table.verticalHeader().setMinimumSectionSize(40)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
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
                cell.setTextAlignment(Qt.AlignVCenter | (Qt.AlignRight if col >= 3 else Qt.AlignLeft))
                table.setItem(row, col, cell)
        resize_rows_to_contents(table)
        table.setMinimumHeight(40 + max(1, len(invoices)) * 40)
        table.setMaximumHeight(40 + max(1, min(len(invoices), 5)) * 40)
        return table

    def _load_entrega(self, process: dict[str, Any], history: list[dict[str, Any]]):
        clear_panel(self.entrega_panel)
        layout = self.entrega_panel.layout()
        delivered = process.get("quantidade_entregue")
        pending = process.get("saldo_pendente")
        status = process.get("status_expedicao") or ""
        if delivered in (None, "") and pending in (None, "") and not status:
            layout.addWidget(key_label("Nenhuma entrega registrada."))
            return
        last_delivery = self._latest_delivery_event(history)
        rows = [
            ("Status de expedição", self.service.area_status_label("EXPEDICAO", status) if status else "-"),
            ("Quantidade entregue", format_quantity(delivered)),
            ("Saldo pendente", format_quantity(pending)),
            ("Última movimentação de entrega", last_delivery),
        ]
        layout.addLayout(kv_grid(rows, key_width=210))
        layout.addWidget(
            note_box(
                "Transportadora, motorista e placa não são registrados para a entrega ao cliente neste sistema. "
                "Esses dados existem apenas para o transporte de envio e retorno de galvanização (aba \"Cargas\").",
                self.service.palette,
            )
        )

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
