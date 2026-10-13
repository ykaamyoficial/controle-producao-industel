"""Canto liso e fade para o que flutua sem ter classe propria no programa:
menus de contexto (QMenu) e a lista que abre de um QComboBox.

Sao janelas criadas em dezenas de pontos (ou pelo proprio Qt), entao em vez de
tocar em cada um o filtro abaixo, ligado uma vez na aplicacao como o
`wheel_guard`, age no momento em que elas vao aparecer:

- fundo transparente e sem a sombra retangular do Windows, para o raio da
  folha de estilo sair com suavizacao (numa janela opaca o canto fica reto);
- fade curto ao abrir. Fechar continua na hora: menu que demora a sumir
  atrapalha.

As caixas de mensagem e de entrada de texto do Qt nao passam por aqui: ver
`message_boxes.py`.

So age com a casca nova ligada (`window_shell_enabled()`); sem ela nada muda.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QVariantAnimation
from PySide6.QtWidgets import QAbstractItemView, QApplication, QMenu, QWidget

from app.ui.animations import WINDOW_CURVE, window_motion_enabled
from app.ui.components.window_shell import window_shell_enabled

MENU_FADE_MS = 120


def soften_floating(widget: QWidget) -> None:
    """Deixa a janela flutuante pronta para canto liso. Precisa rodar antes de
    ela aparecer pela primeira vez (as marcas de janela recriam a janela)."""
    if widget.property("softFloating"):
        return
    widget.setProperty("softFloating", True)
    widget.setWindowFlag(Qt.FramelessWindowHint, True)
    widget.setWindowFlag(Qt.NoDropShadowWindowHint, True)
    widget.setAttribute(Qt.WA_TranslucentBackground, True)


def fade_floating(widget: QWidget) -> None:
    """Fade de entrada pela opacidade da janela (nao ha efeito grafico)."""
    if not window_motion_enabled():
        return
    animation = getattr(widget, "_floating_fade", None)
    if animation is None:
        animation = QVariantAnimation(widget)
        animation.setEasingCurve(WINDOW_CURVE)
        animation.setDuration(MENU_FADE_MS)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.valueChanged.connect(widget.setWindowOpacity)
        widget._floating_fade = animation
    animation.stop()
    widget.setWindowOpacity(0.0)
    animation.start()


class FloatingChrome(QObject):
    def eventFilter(self, watched, event):  # noqa: N802 (Qt override)
        kind = event.type()
        if kind != QEvent.Polish and kind != QEvent.Show:
            return False
        if not isinstance(watched, QWidget) or not window_shell_enabled():
            return False
        if not (isinstance(watched, QMenu) or watched.inherits("QComboBoxPrivateContainer")):
            return False
        if kind == QEvent.Polish:
            soften_floating(watched)
            if not isinstance(watched, QMenu):
                # O raio fica na lista (ver QComboBox QAbstractItemView na folha de estilo).
                view = watched.findChild(QAbstractItemView)
                if view is not None:
                    view.setProperty("softFloatingList", True)
        elif watched.property("softFloating"):
            fade_floating(watched)
        return False


def install_floating_chrome(app: QApplication) -> FloatingChrome:
    """Liga o filtro uma vez por aplicacao (chamar de novo devolve o mesmo)."""
    chrome = getattr(app, "_floating_chrome", None)
    if chrome is None:
        chrome = FloatingChrome(app)
        app.installEventFilter(chrome)
        app._floating_chrome = chrome
    return chrome
