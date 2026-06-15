from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout


class ModernDialog(QDialog):
    def __init__(self, title: str, message: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 18px; font-weight: 800;")
        msg = QLabel(message)
        msg.setWordWrap(True)
        msg.setObjectName("Caption")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(title_label)
        layout.addWidget(msg)
        layout.addWidget(buttons, alignment=Qt.AlignRight)
