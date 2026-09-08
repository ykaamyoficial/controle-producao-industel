from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QDialog, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout

from app.ui.components.modern_button import ModernButton
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent


class DashboardDetailsDialog(QDialog):
    def __init__(self, service, title: str, rows: list[dict], parent=None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle(title)
        apply_large_dialog_geometry(self, parent)
        style_dialog_from_parent(self, parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        heading = QLabel(title)
        heading.setStyleSheet("font-size: 18px; font-weight: 800;")
        summary = QLabel(f"{len(rows)} proposta(s) relacionada(s)")
        summary.setObjectName("Caption")
        root.addWidget(heading)
        root.addWidget(summary)

        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(["Proposta", "Cliente", "Obra/Site", "Localizacao", "Status", "Prazo"])
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(34)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        table.horizontalHeader().setStretchLastSection(True)
        widths = (130, 180, 190, 120, 210, 110)
        for column, width in enumerate(widths):
            table.setColumnWidth(column, width)
        for row_data in rows:
            row = table.rowCount()
            table.insertRow(row)
            if row_data.get("status_fiscal"):
                area_label = "Fiscal"
                status = service.fiscal_status_label(row_data.get("status_fiscal") or "")
                prazo = row_data.get("data_entrada_fiscal") or "-"
            else:
                area_key, area_label, status_key = service.current_location(row_data)
                status = service.area_status_label(area_key, status_key) if status_key else "-"
                prazo = row_data.get("prazo_entrega") or "-"
            values = (
                row_data.get("proposta") or "-",
                row_data.get("cliente") or "-",
                row_data.get("obra_site") or "-",
                area_label or "-",
                status,
                prazo,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                table.setItem(row, column, item)
        root.addWidget(table, 1)

        close = ModernButton("Fechar", "clear")
        close.clicked.connect(self.accept)
        root.addWidget(close, 0, Qt.AlignRight)
