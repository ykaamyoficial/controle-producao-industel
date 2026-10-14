"""Roda do mouse nao troca o valor de caixas de selecao (QComboBox).

Por padrao o Qt troca a opcao de um combo quando a roda gira sobre ele, mesmo
sem ele estar selecionado. Numa tabela de fluxo ou num formulario com rolagem
isso muda a rota/o valor sem querer, so porque o usuario estava rolando a
tela. O filtro abaixo impede a troca e repassa a rolagem para o widget de tras
(tabela, area rolavel), que rola normalmente. O valor continua mudando por
clique, teclado e pela lista aberta.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QAbstractScrollArea, QApplication, QComboBox, QWidget


def _scroll_viewport(widget: QWidget) -> QWidget | None:
    """Viewport da area rolavel (tabela, QScrollArea) que contem `widget`."""
    parent = widget.parentWidget()
    while parent is not None:
        container = parent.parentWidget()
        if isinstance(container, QAbstractScrollArea) and container.viewport() is parent:
            return parent
        parent = container
    return None


class ComboWheelGuard(QObject):
    def eventFilter(self, watched, event):  # noqa: N802 (Qt override)
        if event.type() != QEvent.Wheel or not isinstance(watched, QComboBox):
            return False
        # Entrega a rolagem direto ao viewport: um QWheelEvent novo nasce
        # "aceito" e o Qt nao o repassaria sozinho para o widget de tras.
        target = _scroll_viewport(watched)
        if target is not None:
            position = QPointF(watched.mapTo(target, event.position().toPoint()))
            forwarded = QWheelEvent(
                position,
                event.globalPosition(),
                event.pixelDelta(),
                event.angleDelta(),
                event.buttons(),
                event.modifiers(),
                event.phase(),
                event.inverted(),
                event.source(),
            )
            QApplication.sendEvent(target, forwarded)
        event.accept()
        return True


def install_combo_wheel_guard(app: QApplication) -> ComboWheelGuard:
    """Liga o filtro uma vez por aplicacao (chamar de novo devolve o mesmo)."""
    guard = getattr(app, "_combo_wheel_guard", None)
    if guard is None:
        guard = ComboWheelGuard(app)
        app.installEventFilter(guard)
        app._combo_wheel_guard = guard
    return guard
