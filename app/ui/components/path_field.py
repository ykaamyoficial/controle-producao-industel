from __future__ import annotations

import os

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QVBoxLayout, QWidget

from app.ui.components.modern_button import ModernButton

_web_schemes = ("http://", "https://")
_last_dir = ""


def open_path(text: str, parent: QWidget | None = None) -> bool:
    """Abre o link, o arquivo ou a pasta no programa padrão do Windows (pasta abre no Explorer)."""
    target = (text or "").strip()
    if not target:
        return False
    if target.lower().startswith(_web_schemes):
        return QDesktopServices.openUrl(QUrl(target))
    if target.lower().startswith("file://"):
        return QDesktopServices.openUrl(QUrl(target))
    if os.path.exists(target):
        return QDesktopServices.openUrl(QUrl.fromLocalFile(target))
    QMessageBox.warning(
        parent,
        "Caminho não encontrado",
        f"Não encontrei:\n{target}\n\nO arquivo ou a pasta pode ter sido movido, ou a pasta de rede não está acessível.",
    )
    return False


def _start_dir(current: str) -> str:
    path = (current or "").strip()
    if path and os.path.exists(path):
        return path if os.path.isdir(path) else os.path.dirname(path)
    parent = os.path.dirname(path) if path else ""
    if parent and os.path.isdir(parent):
        return parent
    return _last_dir


class PathField(QWidget):
    """Campo de caminho: escolhe o arquivo ou a pasta numa janela do Windows, guarda o caminho
    digitado/escolhido (ou um link http) e abre o local com um clique. `line` é o QLineEdit."""

    def __init__(self, placeholder: str = "Escolha um arquivo ou uma pasta", accessible_name: str = "", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.line = QLineEdit()
        self.line.setPlaceholderText(placeholder)
        self.line.setMinimumHeight(34)
        if accessible_name:
            self.line.setAccessibleName(accessible_name)
        self.line.textChanged.connect(self._sync)
        layout.addWidget(self.line, 1)
        self.file_button = ModernButton("Arquivo", "attach", variant="secondary")
        self.file_button.setToolTip("Escolher um arquivo")
        self.file_button.clicked.connect(self.choose_file)
        self.folder_button = ModernButton("Pasta", None, variant="secondary")
        self.folder_button.setToolTip("Escolher uma pasta")
        self.folder_button.clicked.connect(self.choose_folder)
        self.open_button = ModernButton("Abrir", None, variant="ghost")
        self.open_button.setToolTip("Abrir o arquivo ou a pasta salvos")
        self.open_button.clicked.connect(lambda _=False: open_path(self.line.text(), self))
        for button in (self.file_button, self.folder_button, self.open_button):
            layout.addWidget(button)
        self._sync()

    def text(self) -> str:
        return self.line.text().strip()

    def setText(self, text: str) -> None:
        self.line.setText(text)

    def _sync(self) -> None:
        self.open_button.setEnabled(bool(self.line.text().strip()))

    def _set_from_dialog(self, chosen: str) -> None:
        global _last_dir
        if not chosen:
            return
        path = os.path.normpath(chosen)
        _last_dir = path if os.path.isdir(path) else os.path.dirname(path)
        self.line.setText(path)

    def choose_file(self) -> None:
        chosen, _filter = QFileDialog.getOpenFileName(self, "Escolher arquivo", _start_dir(self.line.text()))
        self._set_from_dialog(chosen)

    def choose_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Escolher pasta", _start_dir(self.line.text()))
        self._set_from_dialog(chosen)


class PathValue(QWidget):
    """Caminho já salvo, em modo leitura: o texto e um botão para abrir o local rápido."""

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        label = QLabel(path)
        label.setObjectName("ValueLabel")
        label.setWordWrap(True)
        label.setToolTip(path)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(label, 1)
        self.open_button = ModernButton("Abrir", None, variant="ghost")
        self.open_button.setToolTip("Abrir o arquivo ou a pasta")
        self.open_button.clicked.connect(lambda _=False: open_path(path, self))
        layout.addWidget(self.open_button)


def path_rows_panel(rows: list[tuple[str, str]]) -> QWidget:
    """Lista 'nome + caminho + Abrir' para os documentos já registrados (ignora os vazios)."""
    body = QWidget()
    layout = QVBoxLayout(body)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for caption, path in rows:
        if not path:
            continue
        row = QHBoxLayout()
        title = QLabel(caption)
        title.setMinimumWidth(168)
        row.addWidget(title)
        row.addWidget(PathValue(path), 1)
        layout.addLayout(row)
    return body
