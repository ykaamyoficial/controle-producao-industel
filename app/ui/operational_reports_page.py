from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.models.operational_report_table_model import OperationalReportTableModel
from app.services.operational_reports import OperationalReportsService
from app.ui.components.kpi_card import KpiCard
from app.ui.components.modern_button import ModernButton
from app.ui.components.modern_table import ModernTable


AREA_OPTIONS = [
    ("Producao", "PRODUCAO"),
    ("Galvanizacao", "GALVANIZACAO"),
    ("Expedicao", "EXPEDICAO"),
    ("Almoxarifado", "ALMOXARIFADO"),
    ("Remanejamentos", "REMANEJAMENTOS"),
]

REPORT_TYPES = {
    "PRODUCAO": [("Relatorio de producao", "PADRAO")],
    "GALVANIZACAO": [("Relatorio de galvanizacao", "PADRAO")],
    "EXPEDICAO": [("Relatorio de expedicao", "PADRAO")],
    "ALMOXARIFADO": [("Relatorio de almoxarifado", "PADRAO")],
    "REMANEJAMENTOS": [("Relatorio de remanejamentos", "PADRAO")],
}

TABLE_COLUMNS = {
    "PRODUCAO": [
        ("proposta", "Proposta"),
        ("cliente", "Cliente"),
        ("obra_site", "Obra/Site"),
        ("lote", "Lote"),
        ("tipo_processo", "Tipo"),
        ("status_producao", "Status producao"),
        ("data_final_producao", "Data producao"),
        ("total_itens", "Itens"),
        ("itens_produzidos", "Produzidos"),
        ("peso_total_itens", "Peso total"),
        ("peso_produzido_atual", "Peso produzido"),
        ("origem_remanejamento", "Origem remanej."),
    ],
    "GALVANIZACAO": [
        ("carga_id", "Carga"),
        ("status_carga", "Status carga"),
        ("proposta", "Proposta"),
        ("cliente", "Cliente"),
        ("obra_site", "Obra/Site"),
        ("lote", "Lote"),
        ("status_galvanizacao", "Status galv."),
        ("data_envio_galv", "Envio"),
        ("data_prevista_retorno", "Prev. retorno"),
        ("data_retorno", "Retorno"),
        ("peso_enviado", "Peso enviado"),
        ("peso_retornado", "Peso retornado"),
        ("peso_pendente", "Peso pendente"),
    ],
    "EXPEDICAO": [
        ("proposta", "Proposta"),
        ("cliente", "Cliente"),
        ("obra_site", "Obra/Site"),
        ("lote", "Lote"),
        ("tipo_processo", "Tipo"),
        ("status_expedicao", "Status expedicao"),
        ("data_retirada", "Retirada"),
        ("total_itens", "Itens"),
        ("itens_entregues", "Entregues"),
        ("itens_pendentes", "Pendentes"),
        ("kg_entregue_atual", "Kg entregue"),
    ],
    "ALMOXARIFADO": [
        ("proposta", "Proposta"),
        ("cliente", "Cliente"),
        ("obra_site", "Obra/Site"),
        ("lote", "Lote"),
        ("tipo_processo", "Tipo"),
        ("necessita_almoxarifado", "Necessita"),
        ("status_almoxarifado", "Status almox."),
        ("data_separacao", "Separacao"),
        ("observacoes_almoxarifado", "Observacao"),
    ],
    "REMANEJAMENTOS": [
        ("data_hora", "Data"),
        ("usuario", "Usuario"),
        ("proposta_origem", "Origem"),
        ("cliente_origem", "Cliente origem"),
        ("proposta_destino", "Destino"),
        ("cliente_destino", "Cliente destino"),
        ("numero_item", "Item"),
        ("item_descricao", "Descricao"),
        ("quantidade", "Qtd."),
        ("peso_remanejado", "Peso remanej."),
        ("proposta_reposicao", "Reposicao"),
        ("observacao", "Observacao"),
    ],
}

FORBIDDEN_EXPORT_TERMS = ("valor", "preco", "preço", "subtotal", "total financeiro", "imposto", "pagamento", "frete")


class OperationalReportsPage(QWidget):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.reports = OperationalReportsService(service.conn)
        self.current_report: dict[str, Any] | None = None
        self.model = OperationalReportTableModel(self)
        self._card_widgets: list[KpiCard] = []
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        filters = QFrame()
        filters.setObjectName("FilterBar")
        fl = QVBoxLayout(filters)
        fl.setContentsMargins(16, 12, 16, 12)
        fl.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Relatorios Operacionais")
        title.setObjectName("FilterTitle")
        subtitle = QLabel("Consultas por area para acompanhar producao, galvanizacao, expedicao, almoxarifado e remanejamentos.")
        subtitle.setObjectName("Caption")
        subtitle.setWordWrap(True)
        header.addWidget(title)
        header.addStretch()
        self.reliability_badge = QLabel("Confiabilidade: -")
        self.reliability_badge.setObjectName("TopInfoChip")
        header.addWidget(self.reliability_badge)
        fl.addLayout(header)
        fl.addWidget(subtitle)

        self.area = QComboBox()
        for label, value in AREA_OPTIONS:
            self.area.addItem(label, value)
        self.report_type = QComboBox()
        self.start = QLineEdit()
        self.start.setPlaceholderText("AAAA-MM-DD ou DD/MM/AAAA")
        self.end = QLineEdit()
        self.end.setPlaceholderText("AAAA-MM-DD ou DD/MM/AAAA")
        self.proposal = QLineEdit()
        self.proposal.setPlaceholderText("Proposta")
        self.client = QLineEdit()
        self.client.setPlaceholderText("Cliente")
        self.site = QLineEdit()
        self.site.setPlaceholderText("Obra/Site")
        self.lot = QLineEdit()
        self.lot.setPlaceholderText("Lote")
        self.status = QLineEdit()
        self.status.setPlaceholderText("Status")

        self.generate_btn = ModernButton("Gerar relatorio", "search", accent=True)
        self.clear_btn = ModernButton("Limpar filtros", "clear")
        self.export_csv_btn = ModernButton("Exportar CSV", "excel", accent=True)
        self.export_pdf_btn = ModernButton("Exportar PDF", "pdf")
        self.export_pdf_btn.setEnabled(False)
        self.export_pdf_btn.setToolTip("Planejado para versao futura")
        self.generate_btn.clicked.connect(self.refresh)
        self.clear_btn.clicked.connect(self.clear_filters)
        self.export_csv_btn.clicked.connect(self.export_csv)
        self.area.currentIndexChanged.connect(self._sync_report_types)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self._add_field(grid, 0, 0, "Area", self.area)
        self._add_field(grid, 0, 2, "Tipo de relatorio", self.report_type)
        self._add_field(grid, 0, 4, "Data inicial", self.start)
        self._add_field(grid, 0, 6, "Data final", self.end)
        self._add_field(grid, 1, 0, "Proposta", self.proposal)
        self._add_field(grid, 1, 2, "Cliente", self.client)
        self._add_field(grid, 1, 4, "Obra/Site", self.site)
        self._add_field(grid, 1, 6, "Lote", self.lot)
        self._add_field(grid, 1, 8, "Status", self.status)
        for column in (1, 3, 5, 7, 9):
            grid.setColumnStretch(column, 1)
        fl.addLayout(grid)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch()
        actions.addWidget(self.generate_btn)
        actions.addWidget(self.clear_btn)
        actions.addWidget(self.export_csv_btn)
        actions.addWidget(self.export_pdf_btn)
        fl.addLayout(actions)
        root.addWidget(filters)

        self.cards_frame = QFrame()
        self.cards_frame.setObjectName("Panel")
        self.cards_layout = QHBoxLayout(self.cards_frame)
        self.cards_layout.setContentsMargins(12, 12, 12, 12)
        self.cards_layout.setSpacing(10)
        root.addWidget(self.cards_frame)

        self.warning_box = QFrame()
        self.warning_box.setObjectName("Panel")
        warning_layout = QVBoxLayout(self.warning_box)
        warning_layout.setContentsMargins(14, 10, 14, 10)
        warning_title = QLabel("Avisos e confiabilidade")
        warning_title.setObjectName("FilterTitle")
        self.warning_text = QLabel("Gere um relatorio para visualizar os avisos tecnicos.")
        self.warning_text.setObjectName("Caption")
        self.warning_text.setWordWrap(True)
        warning_layout.addWidget(warning_title)
        warning_layout.addWidget(self.warning_text)
        root.addWidget(self.warning_box)

        self.table = ModernTable(self.service)
        self.table.status_shortcut_enabled = False
        self.table.setModel(self.model)
        root.addWidget(self.table, 1)

        self._sync_report_types()

    def _add_field(self, layout: QGridLayout, row: int, column: int, label_text: str, widget: QWidget) -> None:
        label = QLabel(label_text)
        label.setObjectName("FieldLabel")
        layout.addWidget(label, row, column)
        layout.addWidget(widget, row, column + 1)

    def _sync_report_types(self) -> None:
        area = self.area.currentData() or "PRODUCAO"
        self.report_type.clear()
        for label, value in REPORT_TYPES.get(area, []):
            self.report_type.addItem(label, value)

    def filters(self) -> dict[str, str]:
        return {
            "periodo_inicial": self.start.text().strip(),
            "periodo_final": self.end.text().strip(),
            "proposta": self.proposal.text().strip(),
            "cliente": self.client.text().strip(),
            "obra_site": self.site.text().strip(),
            "lote": self.lot.text().strip(),
            "status": self.status.text().strip(),
        }

    def refresh(self) -> None:
        area = self.area.currentData() or "PRODUCAO"
        self.current_report = self._generate_report(area, self.filters())
        columns = TABLE_COLUMNS.get(area) or self._columns_from_rows(self.current_report["linhas"])
        self.model.set_report(columns, self.current_report["linhas"])
        self.table.apply_column_layout()
        self._render_cards(self.current_report["cards"])
        self._render_warnings(self.current_report)

    def clear_filters(self) -> None:
        for widget in (self.start, self.end, self.proposal, self.client, self.site, self.lot, self.status):
            widget.clear()
        self.area.setCurrentIndex(0)
        self.refresh()

    def _generate_report(self, area: str, filters: dict[str, str]) -> dict[str, Any]:
        generators = {
            "PRODUCAO": self.reports.gerar_relatorio_producao,
            "GALVANIZACAO": self.reports.gerar_relatorio_galvanizacao,
            "EXPEDICAO": self.reports.gerar_relatorio_expedicao,
            "ALMOXARIFADO": self.reports.gerar_relatorio_almoxarifado,
            "REMANEJAMENTOS": self.reports.gerar_relatorio_remanejamentos,
        }
        return generators[area](filters)

    def _render_cards(self, cards: list[dict[str, Any]]) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._card_widgets = []
        colors = [
            self.service.palette["accent"],
            self.service.palette["success"],
            self.service.palette["secondary"],
            self.service.palette["warning"],
            self.service.palette["danger"],
        ]
        for index, card in enumerate(cards[:6]):
            value = card.get("valor", 0)
            unit = card.get("unidade", "")
            display = f"{value} {unit}".strip()
            widget = KpiCard(card.get("titulo", "-"), display, "reports", colors[index % len(colors)])
            self.cards_layout.addWidget(widget)
            self._card_widgets.append(widget)
        self.cards_layout.addStretch()

    def _render_warnings(self, report: dict[str, Any]) -> None:
        reliability = str(report.get("confiabilidade") or "-").title()
        self.reliability_badge.setText(f"Confiabilidade: {reliability}")
        warnings = report.get("avisos") or []
        if warnings:
            self.warning_text.setText("\n".join(f"- {warning}" for warning in warnings))
        else:
            self.warning_text.setText("Nenhum aviso tecnico para este relatorio.")

    def _columns_from_rows(self, rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
        if not rows:
            return []
        return [(key, key.replace("_", " ").title()) for key in rows[0].keys()]

    def export_csv(self) -> None:
        if not self.current_report or not self.model.rows:
            QMessageBox.information(self, "Relatorios Operacionais", "Nao ha dados para exportar.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar relatorio operacional",
            self._default_csv_name(),
            "CSV (*.csv)",
        )
        if not path:
            return
        self.write_csv(Path(path))
        QMessageBox.information(self, "Relatorios Operacionais", "CSV gerado com sucesso.")

    def write_csv(self, path: Path) -> None:
        safe_columns = [
            (key, label)
            for key, label in self.model.columns
            if not _contains_forbidden_financial_term(key) and not _contains_forbidden_financial_term(label)
        ]
        with path.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file, delimiter=";")
            writer.writerow([label for _key, label in safe_columns])
            for row in self.model.rows:
                writer.writerow([row.get(key, "") or "" for key, _label in safe_columns])

    def _default_csv_name(self) -> str:
        area = (self.area.currentData() or "relatorio").lower()
        return f"relatorio_operacional_{area}.csv"


def _contains_forbidden_financial_term(text: str) -> bool:
    normalized = str(text or "").lower()
    return any(term in normalized for term in FORBIDDEN_EXPORT_TERMS)
