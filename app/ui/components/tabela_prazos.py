from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from app.ui.components.badge_status import BadgeStatus


class TabelaPrazos(QWidget):
    item_clicked = Signal(str)

    def __init__(self, rows, palette: dict, parent=None):
        super().__init__(parent)
        values = {str(row["label"] if isinstance(row, dict) else row[0]).lower(): int(row["total"] if isinstance(row, dict) else row[1]) for row in rows}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        total = sum(values.values())
        summary = QLabel(f"Visao consolidada de {total} processo(s)")
        summary.setStyleSheet(f"color: {palette['muted']}; font-size: 10px;")
        root.addWidget(summary)
        grid = QGridLayout()
        grid.setSpacing(10)
        definitions = [
            ("Vencidos", values.get("vencidos", 0), palette["danger"]),
            ("Hoje", values.get("hoje", 0), palette["secondary"]),
            ("Prox. 7 dias", values.get("7 dias", values.get("prox. 7 dias", 0)), palette["warning"]),
            ("No prazo", values.get("no prazo", 0), palette["success"]),
            ("Entregues", values.get("entregues", 0), palette["success"]),
        ]
        for index, (label, value, color) in enumerate(definitions):
            badge = BadgeStatus(label, value, color, palette)
            badge.clicked.connect(self.item_clicked)
            grid.addWidget(badge, index // 3, index % 3)
        root.addLayout(grid)
        root.addStretch()
