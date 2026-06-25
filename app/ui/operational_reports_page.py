from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.operational_report_table_model import OperationalReportTableModel
from app.services.operational_reports import OperationalReportsService
from app.ui.components.kpi_card import KpiCard
from app.ui.components.modern_button import ModernButton
from app.ui.components.modern_table import ModernTable
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.table_utils import configure_wrapping_table, item_product_code, resize_rows_to_contents


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
        ("status_producao", "Status producao"),
        ("obra_site", "Obra/Site"),
        ("peso_produzido_atual", "Peso produzido"),
        ("lote", "Lote"),
        ("tipo_processo", "Tipo"),
        ("data_final_producao", "Data producao"),
        ("total_itens", "Itens"),
        ("itens_produzidos", "Produzidos"),
        ("peso_total_itens", "Peso total"),
        ("origem_remanejamento", "Origem remanej."),
    ],
    "GALVANIZACAO": [
        ("proposta", "Proposta"),
        ("cliente", "Cliente"),
        ("status_galvanizacao", "Status galv."),
        ("carga_id", "Carga"),
        ("status_carga", "Status carga"),
        ("obra_site", "Obra/Site"),
        ("peso_enviado", "Peso enviado"),
        ("lote", "Lote"),
        ("data_envio_galv", "Envio"),
        ("data_prevista_retorno", "Prev. retorno"),
        ("data_retorno", "Retorno"),
        ("peso_retornado", "Peso retornado"),
        ("peso_pendente", "Peso pendente"),
    ],
    "EXPEDICAO": [
        ("proposta", "Proposta"),
        ("cliente", "Cliente"),
        ("status_expedicao", "Status expedicao"),
        ("obra_site", "Obra/Site"),
        ("kg_entregue_atual", "Kg entregue"),
        ("lote", "Lote"),
        ("tipo_processo", "Tipo"),
        ("data_retirada", "Retirada"),
        ("total_itens", "Itens"),
        ("itens_entregues", "Entregues"),
        ("itens_pendentes", "Pendentes"),
    ],
    "ALMOXARIFADO": [
        ("proposta", "Proposta"),
        ("cliente", "Cliente"),
        ("status_almoxarifado", "Status almox."),
        ("obra_site", "Obra/Site"),
        ("lote", "Lote"),
        ("tipo_processo", "Tipo"),
        ("necessita_almoxarifado", "Necessita"),
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
        ("codigo_produto", "Codigo"),
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
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.open_row_menu)
        self.table.doubleClicked.connect(self.open_selected_details)
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
            widget.setCursor(Qt.PointingHandCursor)
            widget.setToolTip("Clique para ver os registros relacionados.")
            widget.mousePressEvent = lambda event, selected=card: self.open_card_drilldown(selected)
            self.cards_layout.addWidget(widget)
            self._card_widgets.append(widget)
        self.cards_layout.addStretch()

    def open_card_drilldown(self, card: dict[str, Any]) -> None:
        if not self.current_report:
            return
        area = self.area.currentData() or "PRODUCAO"
        title = str(card.get("titulo") or "")
        rows = self._filter_rows_for_card(area, title, self.current_report.get("linhas") or [])
        columns = TABLE_COLUMNS.get(area) or self._columns_from_rows(rows)
        dialog = OperationalRowsDialog(
            self.service,
            f"{title} - {area.title()}",
            rows,
            columns,
            self,
        )
        dialog.exec()

    def _filter_rows_for_card(self, area: str, title: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = _normalize_text(title)
        if area == "PRODUCAO":
            if "completa" in normalized:
                return [row for row in rows if row.get("status_producao") == "FINALIZADO"]
            if "parcial" in normalized:
                return [row for row in rows if row.get("status_producao") == "FINALIZADO_PARCIAL"]
            if "remanej" in normalized or "pend" in normalized:
                return [
                    row for row in rows
                    if row.get("status_producao") == "ITEM_PENDENTE_FABRICACAO" or row.get("origem_remanejamento")
                ]
        if area == "GALVANIZACAO":
            if "aberta" in normalized:
                return [row for row in rows if row.get("status_carga") != "RETORNADA_GALVANIZACAO"]
            if "finalizada" in normalized or "retornado" in normalized:
                return [row for row in rows if row.get("status_carga") == "RETORNADA_GALVANIZACAO"]
            if "pend" in normalized:
                return [row for row in rows if float(row.get("peso_pendente") or 0) > 0 or row.get("status_carga") != "RETORNADA_GALVANIZACAO"]
        if area == "EXPEDICAO":
            if "completa" in normalized or "entregue" in normalized:
                return [row for row in rows if row.get("status_expedicao") == "ENTREGUE" or row.get("status_geral") == "ENTREGUE"]
            if "parcia" in normalized:
                return [row for row in rows if row.get("status_expedicao") == "ENTREGUE_PARCIAL"]
            if "pend" in normalized:
                return [row for row in rows if row.get("status_expedicao") not in ("ENTREGUE", "ENTREGUE_PARCIAL", "")]
        if area == "ALMOXARIFADO":
            if "pend" in normalized:
                return [row for row in rows if row.get("status_almoxarifado") in ("AGUARDANDO_CONFIRMACAO", "EM_SEPARACAO")]
            if "separada" in normalized:
                return [row for row in rows if row.get("status_almoxarifado") == "SEPARADO"]
            if "sem parafuso" in normalized:
                return [row for row in rows if row.get("status_almoxarifado") == "SEM_PARAFUSOS"]
        if area == "REMANEJAMENTOS":
            if "origem" in normalized:
                return _unique_rows(rows, "processo_origem_id")
            if "destino" in normalized:
                return _unique_rows(rows, "processo_destino_id")
            if "pend" in normalized:
                return [row for row in rows if row.get("status_reposicao") == "ITEM_PENDENTE_FABRICACAO"]
        return rows

    def selected_row(self) -> dict[str, Any] | None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        row = selected[0].row()
        if 0 <= row < len(self.model.rows):
            return self.model.rows[row]
        return None

    def open_row_menu(self, point: QPoint) -> None:
        index = self.table.indexAt(point)
        if index.isValid():
            self.table.selectRow(index.row())
        row = self.selected_row()
        if not row:
            return
        menu = QMenu(self)
        menu.addAction(QAction("Ver detalhes da proposta", self, triggered=lambda: self.show_process_details(row)))
        menu.addAction(QAction("Ver itens", self, triggered=lambda: self.show_items(row)))
        menu.addAction(QAction("Ver historico", self, triggered=lambda: self.show_history(row)))
        menu.addAction(QAction("Ver remanejamentos", self, triggered=lambda: self.show_remanagements(row)))
        menu.addAction(QAction("Ver carga de galvanizacao", self, triggered=lambda: self.show_load(row)))
        menu.addAction(QAction("Ver situacao da expedicao", self, triggered=lambda: self.show_expedition(row)))
        if (self.area.currentData() or "") == "REMANEJAMENTOS":
            menu.addSeparator()
            menu.addAction(QAction("Abrir proposta origem", self, triggered=lambda: self.show_related_process(row, "processo_origem_id")))
            menu.addAction(QAction("Abrir proposta destino", self, triggered=lambda: self.show_related_process(row, "processo_destino_id")))
        menu.addSeparator()
        menu.addAction(QAction("Copiar numero da proposta", self, triggered=lambda: self.copy_proposal(row)))
        menu.exec(self.table.viewport().mapToGlobal(point))

    def open_selected_details(self, _index=None) -> None:
        row = self.selected_row()
        if row:
            self.show_process_details(row)

    def show_related_process(self, row: dict[str, Any], key: str) -> None:
        process_id = _row_process_id(row, preferred_key=key)
        if not process_id:
            QMessageBox.information(self, "Relatorios Operacionais", "Nao foi possivel localizar esta proposta.")
            return
        OperationalProcessReadOnlyDialog(self.service, process_id, self).exec()

    def show_process_details(self, row: dict[str, Any]) -> None:
        process_id = _row_process_id(row)
        if not process_id:
            QMessageBox.information(self, "Relatorios Operacionais", "Nao foi possivel localizar a proposta.")
            return
        OperationalProcessReadOnlyDialog(self.service, process_id, self).exec()

    def show_items(self, row: dict[str, Any]) -> None:
        process_id = _row_process_id(row)
        if not process_id:
            QMessageBox.information(self, "Relatorios Operacionais", "Nao foi possivel localizar os itens.")
            return
        items = self.service.proposal_items(process_id)
        self._show_table_dialog(
            "Itens da proposta",
            items,
            [
                ("numero_item", "Item"),
                ("codigo_produto", "Codigo"),
                ("descricao", "Descricao"),
                ("quantidade", "Qtd."),
                ("peso", "Peso unit."),
                ("produzido", "Produzido"),
                ("galvanizado", "Galvanizado"),
                ("entregue", "Entregue"),
            ],
        )

    def show_history(self, row: dict[str, Any]) -> None:
        process_id = _row_process_id(row)
        if not process_id:
            QMessageBox.information(self, "Relatorios Operacionais", "Nao foi possivel localizar o historico.")
            return
        self._show_table_dialog(
            "Historico resumido",
            self.service.process_history_rows(process_id),
            [
                ("area", "Area"),
                ("status_anterior", "Anterior"),
                ("status_novo", "Novo"),
                ("data_hora", "Quando"),
                ("usuario", "Usuario"),
                ("observacao", "Observacao"),
            ],
        )

    def show_remanagements(self, row: dict[str, Any]) -> None:
        process_id = _row_process_id(row)
        rows = self._remanagement_rows_for(row, process_id)
        self._show_table_dialog(
            "Remanejamentos relacionados",
            rows,
            [
                ("data_hora", "Data"),
                ("usuario", "Usuario"),
                ("proposta_origem", "Origem"),
                ("proposta_destino", "Destino"),
                ("numero_item", "Item"),
                ("codigo_produto", "Codigo"),
                ("item_descricao", "Descricao"),
                ("quantidade", "Qtd."),
                ("peso_remanejado", "Peso"),
                ("observacao", "Observacao"),
            ],
        )

    def _remanagement_rows_for(self, row: dict[str, Any], process_id: int | None) -> list[dict[str, Any]]:
        if self.area.currentData() == "REMANEJAMENTOS" and row.get("remanejamento_id"):
            return [row]
        report = self.reports.gerar_relatorio_remanejamentos({})
        rows = report.get("linhas") or []
        if not process_id:
            return rows
        return [
            item for item in rows
            if int(item.get("processo_origem_id") or 0) == process_id
            or int(item.get("processo_destino_id") or 0) == process_id
        ]

    def show_load(self, row: dict[str, Any]) -> None:
        load_id = int(row.get("carga_id") or 0)
        if not load_id:
            process_id = _row_process_id(row)
            loads = self.service.process_loads(process_id) if process_id else []
            load_id = int(loads[0]["id"]) if loads else 0
        if not load_id:
            QMessageBox.information(self, "Relatorios Operacionais", "Esta linha nao possui carga de galvanizacao vinculada.")
            return
        OperationalLoadReadOnlyDialog(self.service, load_id, self).exec()

    def show_expedition(self, row: dict[str, Any]) -> None:
        process_id = _row_process_id(row)
        process = self.service.get_process_dict(process_id) if process_id else {}
        if not process:
            QMessageBox.information(self, "Relatorios Operacionais", "Nao foi possivel localizar a proposta.")
            return
        lines = [
            ("Proposta", process.get("proposta")),
            ("Cliente", process.get("cliente")),
            ("Status expedicao", self.service.area_status_label("EXPEDICAO", process.get("status_expedicao") or "")),
            ("Data separacao", process.get("data_separacao")),
            ("Data retirada", process.get("data_retirada")),
            ("Situacao fluxo", self.service.status_label(process.get("situacao_fluxo") or "")),
        ]
        text = "\n".join(f"{label}: {value or '-'}" for label, value in lines)
        QMessageBox.information(self, "Situacao da expedicao", text)

    def copy_proposal(self, row: dict[str, Any]) -> None:
        proposal = row.get("proposta") or row.get("proposta_destino") or row.get("proposta_origem") or ""
        QApplication.clipboard().setText(str(proposal))

    def _show_table_dialog(self, title: str, rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> None:
        dialog = OperationalRowsDialog(self.service, title, rows, columns, self)
        dialog.exec()

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


class OperationalRowsDialog(QDialog):
    def __init__(self, service, title: str, rows: list[dict[str, Any]], columns: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle(title)
        apply_large_dialog_geometry(self, parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)
        heading = QLabel(title)
        heading.setStyleSheet("font-size: 18px; font-weight: 800;")
        summary = QLabel(f"{len(rows)} registro(s) relacionado(s)")
        summary.setObjectName("Caption")
        root.addWidget(heading)
        root.addWidget(summary)
        table = QTableWidget(len(rows), len(columns))
        table.setHorizontalHeaderLabels([label for _key, label in columns])
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        table.horizontalHeader().setStretchLastSection(True)
        description_columns = tuple(
            index for index, (key, label) in enumerate(columns)
            if key in {"descricao", "item_descricao", "observacao"} or "Descricao" in label
        )
        code_columns = tuple(
            index for index, (key, label) in enumerate(columns)
            if "codigo" in key or "Codigo" in label or "Cod." in label
        )
        if description_columns:
            configure_wrapping_table(
                table,
                description_columns=description_columns,
                code_columns=code_columns,
                min_row_height=42,
            )
        for row_index, data in enumerate(rows):
            for col_index, (key, _label) in enumerate(columns):
                value = item_product_code(data) if "codigo" in key else _display_value(data.get(key))
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                if col_index in description_columns:
                    cell.setTextAlignment(Qt.AlignTop | Qt.AlignLeft)
                else:
                    cell.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                table.setItem(row_index, col_index, cell)
        resize_rows_to_contents(table)
        table.resizeColumnsToContents()
        root.addWidget(table, 1)
        close = ModernButton("Fechar", "clear")
        close.clicked.connect(self.accept)
        root.addWidget(close, 0, Qt.AlignRight)
        style_dialog_from_parent(self, parent)


class OperationalProcessReadOnlyDialog(QDialog):
    def __init__(self, service, process_id: int, parent=None):
        super().__init__(parent)
        self.service = service
        self.process_id = process_id
        self.process = service.get_process_dict(process_id)
        self.setWindowTitle("Detalhes da proposta")
        apply_large_dialog_geometry(self, parent)
        self._build()
        style_dialog_from_parent(self, parent)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)
        header = QFrame()
        header.setObjectName("Panel")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(16, 12, 16, 12)
        title = QLabel(f"{self.process.get('proposta') or '-'} | {self.process.get('cliente') or '-'}")
        title.setStyleSheet("font-size: 18px; font-weight: 800;")
        subtitle = QLabel(
            f"Obra/Site: {self.process.get('obra_site') or '-'} | Lote: {self.process.get('lote') or '-'} | "
            f"Peso: {self.process.get('peso') or '-'} | Prazo: {self.process.get('prazo_entrega') or '-'}"
        )
        subtitle.setObjectName("Caption")
        hl.addWidget(title)
        hl.addWidget(subtitle)
        root.addWidget(header)

        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(self._status_panel(), 1)
        body.addWidget(self._summary_panel(), 1)
        root.addLayout(body)
        root.addWidget(self._items_panel(), 1)
        root.addWidget(self._history_panel(), 1)
        close = ModernButton("Fechar", "clear")
        close.clicked.connect(self.accept)
        root.addWidget(close, 0, Qt.AlignRight)

    def _panel(self, title: str) -> QFrame:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        label = QLabel(title)
        label.setStyleSheet("font-size: 14px; font-weight: 800;")
        layout.addWidget(label)
        return panel

    def _status_panel(self) -> QFrame:
        panel = self._panel("Status por area")
        layout = panel.layout()
        statuses = [
            ("Controle Geral", self.process.get("status_geral")),
            ("Producao", self.process.get("status_producao")),
            ("Galvanizacao", self.process.get("status_galvanizacao")),
            ("Expedicao", self.process.get("status_expedicao")),
            ("Almoxarifado", self.process.get("status_almoxarifado")),
        ]
        for area, status in statuses:
            line = QLabel(f"{area}: {self.service.area_status_label(area.upper(), status or '') if status else '-'}")
            line.setWordWrap(True)
            layout.addWidget(line)
        layout.addStretch()
        return panel

    def _summary_panel(self) -> QFrame:
        panel = self._panel("Resumo operacional")
        layout = panel.layout()
        rows = [
            ("Tipo", self.process.get("tipo_processo")),
            ("Peso/Saldo", self.service.weight_progress_text(self.process_id)),
            ("Origem remanejamento", self.process.get("origem_remanejamento")),
            ("Obs. remanejamento", self.process.get("observacao_remanejamento")),
            ("Atualizado por", self.process.get("atualizado_por")),
            ("Atualizado em", self.process.get("atualizado_em")),
        ]
        for label, value in rows:
            text = QLabel(f"{label}: {value or '-'}")
            text.setWordWrap(True)
            layout.addWidget(text)
        layout.addStretch()
        return panel

    def _items_panel(self) -> QFrame:
        items = self.service.proposal_items(self.process_id)
        panel = self._panel(f"Itens da proposta ({len(items)})")
        table = QTableWidget(len(items), 8)
        table.setHorizontalHeaderLabels(["Item", "Codigo", "Descricao", "Qtd.", "Peso", "Produzido", "Galvanizado", "Entregue"])
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        configure_wrapping_table(table, description_columns=(2,), code_columns=(1,), min_row_height=42)
        for row, item in enumerate(items):
            values = [
                item.get("numero_item"),
                item_product_code(item),
                item.get("descricao"),
                item.get("quantidade"),
                f"{float(item.get('peso') or 0):g} kg",
                "Sim" if item.get("produzido") else "Nao",
                "Sim" if item.get("galvanizado") else "Nao",
                "Sim" if item.get("entregue") else "Nao",
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value or "-"))
                cell.setTextAlignment(Qt.AlignTop | Qt.AlignLeft if col == 2 else Qt.AlignCenter)
                table.setItem(row, col, cell)
        resize_rows_to_contents(table)
        panel.layout().addWidget(table)
        return panel

    def _history_panel(self) -> QFrame:
        history = self.service.process_history_rows(self.process_id)[:20]
        panel = self._panel(f"Historico resumido ({len(history)})")
        table = QTableWidget(len(history), 5)
        table.setHorizontalHeaderLabels(["Area", "Anterior", "Novo", "Quando", "Usuario"])
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        for row, item in enumerate(history):
            values = [item.get("area"), item.get("status_anterior"), item.get("status_novo"), item.get("data_hora"), item.get("usuario")]
            for col, value in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(str(value or "-")))
        panel.layout().addWidget(table)
        return panel


class OperationalLoadReadOnlyDialog(QDialog):
    def __init__(self, service, load_id: int, parent=None):
        super().__init__(parent)
        self.service = service
        self.load_id = load_id
        self.load = service.get_galvanization_load_dict(load_id)
        self.setWindowTitle(f"Carga de galvanizacao {load_id}")
        apply_large_dialog_geometry(self, parent)
        self._build()
        style_dialog_from_parent(self, parent)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        title = QLabel(
            f"Carga {self.load_id} | {self.service.load_status_label(self.load.get('status') or '')} | "
            f"Motorista: {self.load.get('motorista') or '-'}"
        )
        title.setStyleSheet("font-size: 18px; font-weight: 800;")
        root.addWidget(title)
        proposals = self.service.galvanization_load_items(self.load_id)
        table = QTableWidget(len(proposals), 6)
        table.setHorizontalHeaderLabels(["Proposta", "Cliente", "Peso total", "Peso enviado", "Parcial", "Itens"])
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        for row, data in enumerate(proposals):
            process_id = int(data.get("processo_id") or 0)
            items = self.service.galvanization_load_proposal_items(self.load_id, process_id) if process_id else []
            values = [
                data.get("proposta"),
                data.get("cliente"),
                _display_value(data.get("peso_total_proposta")),
                _display_value(data.get("peso_enviado")),
                "Sim" if data.get("parcial") else "Nao",
                sum(int(item.get("quantidade") or 1) for item in items),
            ]
            for col, value in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(str(value or "-")))
        root.addWidget(table, 1)
        close = ModernButton("Fechar", "clear")
        close.clicked.connect(self.accept)
        root.addWidget(close, 0, Qt.AlignRight)


def _row_process_id(row: dict[str, Any], preferred_key: str = "") -> int | None:
    keys = [preferred_key] if preferred_key else []
    keys.extend(["processo_id", "id", "processo_destino_id", "processo_origem_id"])
    for key in keys:
        if not key:
            continue
        try:
            value = int(row.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value:
            return value
    return None


def _display_value(value: Any) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _normalize_text(value: str) -> str:
    text = str(value or "").lower()
    replacements = {"ç": "c", "ã": "a", "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ê": "e"}
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


def _unique_rows(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for row in rows:
        value = row.get(key)
        if value in seen:
            continue
        seen.add(value)
        result.append(row)
    return result
