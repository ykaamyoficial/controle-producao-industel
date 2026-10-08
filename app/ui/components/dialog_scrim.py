"""Veu que escurece a janela de tras enquanto um dialogo modal esta aberto
(padrao "telas que abrem por cima do programa" da skill qt-industrial-ui).

O dialogo continua sendo um QDialog de nivel superior; o veu e um widget
filho da janela dona, mostrado no Show do dialogo e escondido no Hide/Close.
Ligado em um ponto unico: `style_dialog_from_parent()`.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QDialog, QWidget

from app.ui.animations import animate_value
from app.ui.theme_tokens import active_tokens, relative_luminance

_SCRIM_COLOR = (8, 15, 30)
_ALPHA_LIGHT = 105
_ALPHA_DARK = 150


class DialogScrim(QWidget):
    def __init__(self, owner: QWidget):
        super().__init__(owner)
        self.setObjectName("DialogScrim")
        self._alpha = 0.0
        self._holders = 0
        self.hide()
        owner.installEventFilter(self)

    def eventFilter(self, watched, event):  # noqa: N802 (Qt override)
        if watched is self.parent() and event.type() == QEvent.Resize and self.isVisible():
            self.setGeometry(watched.rect())
        return False

    def acquire(self) -> None:
        self._holders += 1
        if self._holders > 1:
            return
        self.setGeometry(self.parent().rect())
        self._alpha = 0.0
        self.show()
        self.raise_()
        animate_value(self, "_alpha", 1.0, 200)

    def release(self) -> None:
        self._holders = max(0, self._holders - 1)
        if self._holders == 0:
            self.hide()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        dark_theme = relative_luminance(active_tokens()["bg"]) < 0.2
        alpha = int((_ALPHA_DARK if dark_theme else _ALPHA_LIGHT) * self._alpha)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(*_SCRIM_COLOR, alpha))
        painter.end()


class _ScrimHolder:
    """Quem segura o veu, fora de qualquer QObject. O sinal `destroyed` do
    dialogo nao pode ser ligado a um metodo de um filho dele: o filho ja esta
    sendo destruido quando o sinal sai, o PySide nao acha o slot ("Slot ...
    not found") e o processo pode cair com violacao de acesso. Ligado a um
    objeto Python comum, a liberacao roda sem tocar em objeto C++ destruido."""

    def __init__(self, owner: QWidget):
        self.owner = owner
        self.scrim: DialogScrim | None = None

    def release(self, *_args) -> None:
        scrim, self.scrim = self.scrim, None
        if scrim is None:
            return
        try:
            scrim.release()
        except RuntimeError:
            pass


class _ScrimBinding(QObject):
    """Acompanha um dialogo: segura o veu enquanto ele estiver visivel e
    garante a liberacao em qualquer forma de fechamento (accept, reject, Esc,
    close(), destruicao)."""

    def __init__(self, dialog: QDialog, owner: QWidget):
        super().__init__(dialog)
        self._holder = _ScrimHolder(owner)
        dialog.installEventFilter(self)
        dialog.destroyed.connect(self._holder.release)

    def eventFilter(self, watched, event):  # noqa: N802 (Qt override)
        event_type = event.type()
        if event_type == QEvent.Show:
            self._acquire(watched)
        elif event_type in (QEvent.Hide, QEvent.Close):
            self._release()
        return False

    def _acquire(self, dialog: QDialog) -> None:
        holder = self._holder
        if holder.scrim is not None:
            return
        try:
            # So dialogo modal: um dialogo nao modal deixa a janela de tras em
            # uso, e o veu bloquearia os cliques nela.
            if not dialog.isModal() or not holder.owner.isVisible():
                return
            scrim = getattr(holder.owner, "_dialog_scrim", None)
            if scrim is None:
                scrim = DialogScrim(holder.owner)
                holder.owner._dialog_scrim = scrim
            scrim.acquire()
            holder.scrim = scrim
        except RuntimeError:
            # Janela dona ja destruida pelo Qt.
            holder.scrim = None

    def _release(self, *_args) -> None:
        self._holder.release()


def attach_dialog_scrim(dialog: QDialog, owner: QWidget | None) -> None:
    if owner is None or owner is dialog or getattr(dialog, "_scrim_binding", None) is not None:
        return
    dialog._scrim_binding = _ScrimBinding(dialog, owner)
