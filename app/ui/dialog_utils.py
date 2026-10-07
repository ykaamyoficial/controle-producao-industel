from __future__ import annotations

from PySide6.QtWidgets import QApplication, QDialog


def apply_large_dialog_geometry(
    dialog: QDialog,
    parent=None,
    width_ratio: float = 0.94,
    height_ratio: float = 0.90,
    minimum_width: int = 1100,
    minimum_height: int = 650,
) -> None:
    """Apply the standard geometry for content-heavy dialogs."""
    dialog.setMinimumSize(minimum_width, minimum_height)
    dialog.setSizeGripEnabled(True)

    reference = parent.window() if parent and parent.window() else None
    if reference:
        available_width = reference.width()
        available_height = reference.height()
        center = reference.geometry().center()
    else:
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        available_width = available.width() if available else minimum_width
        available_height = available.height() if available else minimum_height
        center = available.center() if available else None

    width = max(minimum_width, int(available_width * width_ratio))
    height = max(minimum_height, int(available_height * height_ratio))
    dialog.resize(width, height)

    if center:
        frame = dialog.frameGeometry()
        frame.moveCenter(center)
        dialog.move(frame.topLeft())


def style_dialog_from_parent(dialog: QDialog, parent=None) -> None:
    owner = parent.window() if parent and parent.window() else None
    if owner:
        dialog.setStyleSheet(owner.styleSheet())
        # Ponto unico dos dialogos: e aqui que toda tela sobreposta ganha o
        # veu que escurece a janela de tras.
        from app.ui.components.dialog_scrim import attach_dialog_scrim

        attach_dialog_scrim(dialog, owner)
