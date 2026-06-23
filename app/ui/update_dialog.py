from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QTextEdit, QVBoxLayout

from app.ui.components.modern_button import ModernButton


class UpdateDialog(QDialog):
    def __init__(self, update_info: dict, parent=None):
        super().__init__(parent)
        self.update_info = update_info
        self.setWindowTitle("Nova versao disponivel")
        self.setMinimumSize(560, 420)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        header = QFrame()
        header.setObjectName("Panel")
        header_layout = QVBoxLayout(header)
        title = QLabel("Nova versao disponivel")
        title.setStyleSheet("font-size: 20px; font-weight: 800;")
        subtitle = QLabel("Confira as informacoes da versao antes de atualizar manualmente.")
        subtitle.setObjectName("Caption")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        root.addWidget(header)

        info = QFrame()
        info.setObjectName("Panel")
        info_layout = QVBoxLayout(info)
        info_layout.setSpacing(8)
        info_layout.addWidget(QLabel(f"Versao atual: {self.update_info.get('current_version', '-')}"))
        info_layout.addWidget(QLabel(f"Versao disponivel: {self.update_info.get('latest_version', '-')}"))
        info_layout.addWidget(QLabel(f"Publicada em: {self.update_info.get('published_at') or '-'}"))
        root.addWidget(info)

        notes_label = QLabel("Notas da versao")
        notes_label.setStyleSheet("font-weight: 800;")
        root.addWidget(notes_label)

        notes = QTextEdit()
        notes.setReadOnly(True)
        notes.setPlainText(self.update_info.get("release_notes") or "Sem notas de versao informadas.")
        root.addWidget(notes, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        close = ModernButton("Fechar", "close")
        close.clicked.connect(self.accept)
        footer.addWidget(close, alignment=Qt.AlignRight)
        root.addLayout(footer)
