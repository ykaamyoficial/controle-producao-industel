"""Veu que escurece a janela de tras enquanto um dialogo modal esta aberto
(padrao "telas que abrem por cima do programa" da skill qt-industrial-ui).

O dialogo continua sendo um QDialog de nivel superior; o veu e um widget
filho da janela dona, mostrado no Show do dialogo e escondido no Hide/Close.
Ligado em um ponto unico: `style_dialog_from_parent()`.

Com a casca nova (`window_shell.py`) o veu escurece junto com o salto da
janela e clareia junto com a saida. Nesse modo ele pinta uma foto da janela
de tras, em vez de deixa-la repintar por baixo a cada quadro: repintar a
pagina inteira custa dezenas de ms e a animacao da janela perdia quadros. A
foto vem do que a janela ja pintou (~3 ms; repintar passava de 70 ms) e vale
ate o dialogo fechar; se a janela de tras mudar de tamanho ou de tema, o veu
volta a ser transparente.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QDialog, QWidget

from app.ui.animations import animate_value, transition, window_motion_enabled
from app.ui.theme_tokens import active_tokens, relative_luminance

_SCRIM_COLOR = (8, 15, 30)
_ALPHA_LIGHT = 105
_ALPHA_DARK = 150
_DARKEN_MS = 260
_LIGHTEN_MS = 180


class DialogScrim(QWidget):
    def __init__(self, owner: QWidget):
        super().__init__(owner)
        self.setObjectName("DialogScrim")
        self._alpha = 0.0
        self._holders = 0
        self._backdrop: QPixmap | None = None
        self._capturing = False
        self.hide()
        owner.installEventFilter(self)

    def eventFilter(self, watched, event):  # noqa: N802 (Qt override)
        if watched is self.parent() and self.isVisible():
            kind = event.type()
            if kind == QEvent.Resize:
                self._thaw()
                self.setGeometry(watched.rect())
            elif kind == QEvent.StyleChange:
                self._thaw()  # tema trocado com o dialogo aberto: a foto ficou velha
        return False

    def acquire(self, deferred: bool = False) -> None:
        """`deferred`: entra em cena ainda transparente e com a janela de tras
        fotografada; quem escurece e `darken()`, chamado pela casca quando o
        salto da janela comeca."""
        self._holders += 1
        if self._holders > 1:
            return
        self.setGeometry(self.parent().rect())
        self._alpha = 0.0
        if deferred:
            self._freeze()
        self.show()
        self.raise_()
        if not deferred:
            animate_value(self, "_alpha", 1.0, 200)

    def darken(self) -> None:
        transition(self, "_alpha", 1.0, _DARKEN_MS)

    def lighten(self) -> None:
        if self._holders > 1:
            return  # outra janela ainda segura o veu
        if self._backdrop is None:
            self._freeze(repaint=True)
        transition(self, "_alpha", 0.0, _LIGHTEN_MS)

    def release(self) -> None:
        self._holders = max(0, self._holders - 1)
        if self._holders == 0:
            self._thaw()
            self.hide()

    def _painted_owner(self) -> QPixmap | None:
        """O que a janela de tras ja pintou, copiado do backing store dela."""
        owner = self.parent()
        window = owner.window()
        store = window.backingStore()
        image = store.paintDevice() if store is not None else None
        if not isinstance(image, QImage) or image.isNull():
            return None
        ratio = window.devicePixelRatioF()
        origin = owner.mapTo(window, QPoint(0, 0))
        area = QRect(round(origin.x() * ratio), round(origin.y() * ratio), round(owner.width() * ratio), round(owner.height() * ratio))
        if area.isEmpty() or not image.rect().contains(area):
            return None
        pixmap = QPixmap.fromImage(image.copy(area))
        pixmap.setDevicePixelRatio(ratio)
        return pixmap

    def _freeze(self, repaint: bool = False) -> None:
        """`repaint`: o veu ja esta na tela (e portanto no que a janela pintou),
        entao a foto limpa so sai repintando a janela sem ele."""
        owner = self.parent()
        # Dona que tambem tem casca e pequena e de fundo transparente: repintar
        # sai barato e a foto perderia o canto.
        if getattr(owner, "_window_shell", None) is not None:
            return
        backdrop = None if repaint else self._painted_owner()
        if backdrop is None:
            self._capturing = True
            try:
                backdrop = owner.grab()
            finally:
                self._capturing = False
        self._backdrop = backdrop
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def _thaw(self) -> None:
        if self._backdrop is None:
            return
        self._backdrop = None
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        if self._capturing:
            return
        dark_theme = relative_luminance(active_tokens()["bg"]) < 0.2
        alpha = int((_ALPHA_DARK if dark_theme else _ALPHA_LIGHT) * max(0.0, min(1.0, self._alpha)))
        painter = QPainter(self)
        if self._backdrop is not None:
            painter.drawPixmap(0, 0, self._backdrop)
        shell = getattr(self.parent(), "_window_shell", None)
        if shell is not None:
            # Dona com canto transparente: o veu nao pode pintar fora dela.
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setClipPath(shell.outline())
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

    def darken(self) -> None:
        scrim = self._holder.scrim
        if scrim is not None:
            scrim.darken()

    def lighten(self) -> None:
        scrim = self._holder.scrim
        if scrim is not None:
            scrim.lighten()

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
            # Com a casca nova e animacao ligada, quem escurece e a casca.
            scrim.acquire(deferred=getattr(dialog, "_window_shell", None) is not None and window_motion_enabled())
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
