from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QPainterPath, QRegion
from PySide6.QtWidgets import QDialog


DIALOG_CORNER_RADIUS = 14
HEADER_DRAG_HEIGHT = 64


def _extract_first(pattern: str, text: str, default: str) -> str:
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1) if match else default


def _rounded_region(width: int, height: int, radius: int) -> QRegion:
    path = QPainterPath()
    path.addRoundedRect(0, 0, width, height, radius, radius)
    return QRegion(path.toFillPolygon().toPolygon())


class _FramelessDialogController(QObject):
    """Um unico event filter cuida do dialogo sem moldura nativa:

    - recorta os cantos em um retangulo arredondado (via QRegion mask -
      evitamos WA_TranslucentBackground porque deixar toda a janela
      translucida quebra o repaint de widgets complexos como QTableView/
      QScrollArea em alguns dialogos, causando travamentos);
    - arrasta a janela clicando em area vazia do cabecalho (primeiros
      HEADER_DRAG_HEIGHT px) - botoes/campos ali continuam funcionando
      normalmente, pois consomem o evento de mouse antes dele chegar ao
      dialogo.
    """

    def __init__(self, dialog: QDialog, radius: int):
        super().__init__(dialog)
        self._dialog = dialog
        self._radius = radius
        self._offset: QPoint | None = None
        self._last_masked_size = None

    def _update_mask(self):
        dialog = getattr(self, "_dialog", None)
        if dialog is None:
            return
        size = dialog.size()
        if size.width() <= 0 or size.height() <= 0 or size == self._last_masked_size:
            return
        self._last_masked_size = size
        dialog.setMask(_rounded_region(size.width(), size.height(), self._radius))

    def eventFilter(self, watched, event):
        dialog = getattr(self, "_dialog", None)
        if dialog is None or watched is not dialog:
            return False
        event_type = event.type()
        if event_type in (QEvent.Resize, QEvent.Show):
            self._update_mask()
        elif event_type == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            if pos.y() <= HEADER_DRAG_HEIGHT:
                self._offset = event.globalPosition().toPoint() - dialog.frameGeometry().topLeft()
        elif event_type == QEvent.MouseMove and self._offset is not None and event.buttons() & Qt.LeftButton:
            dialog.move(event.globalPosition().toPoint() - self._offset)
        elif event_type == QEvent.MouseButtonRelease:
            self._offset = None
        return False


def apply_frameless_rounded_dialog(dialog: QDialog, radius: int = DIALOG_CORNER_RADIUS) -> None:
    """Padrao unico de janela para os dialogos do sistema: remove a barra
    de titulo nativa do SO (cada tela ja tem seus proprios botoes de acao,
    incluindo "Fechar") e recorta cantos arredondados no proprio dialogo.
    Esc continua fechando (comportamento padrao do QDialog, nao depende da
    moldura nativa) mesmo em telas sem botao de fechar visivel.

    Chamada a partir de `style_dialog_from_parent()`, que ja e o ponto
    unico usado por todos os dialogos do app - isso escala o padrao pra
    tela nova automaticamente, sem precisar tocar em cada dialogo.
    """
    if getattr(dialog, "_frameless_rounded_applied", False):
        return
    dialog._frameless_rounded_applied = True
    dialog.setWindowFlag(Qt.FramelessWindowHint, True)

    stylesheet = dialog.styleSheet() or ""
    border = _extract_first(r"border:\s*1px solid\s*(#[0-9a-fA-F]{6})", stylesheet, "#cbd5e1")
    dialog.setStyleSheet(stylesheet + f"\nQDialog {{ border: 1px solid {border}; border-radius: {radius}px; }}\n")

    controller = _FramelessDialogController(dialog, radius)
    dialog.installEventFilter(controller)
