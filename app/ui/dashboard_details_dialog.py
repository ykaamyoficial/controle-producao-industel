from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QDialog, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout

from app.ui.components.modern_button import ModernButton


class DashboardDetailsDialog(QDialog):
    def __init__(self, service, title: str, rows: list[dict], parent=None):
        super().__init__(parent)
        self.service = service
        self.setWindowTitle(title)
        self.resize(920, 520)
        self.setMinimumSize(720, 420)
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
            area_key, area_label, status = service.current_location(row_data)
            values = (
                row_data.get("proposta") or "-",
                row_data.get("cliente") or "-",
                row_data.get("obra_site") or "-",
                area_label or "-",
                service.area_status_label(area_key, status) if status else "-",
                row_data.get("prazo_entrega") or "-",
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
