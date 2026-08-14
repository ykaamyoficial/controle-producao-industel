"""Microanimacoes de icone (PDF secao 10): curtas, orientadas a evento, nunca
em loop por engano, canceláveis. Implementadas com QPropertyAnimation nativo
do Qt - sem timers soltos por tela.

Cuidado ja pago em bug real desta base (ver app/ui/animations.py): animar
`pos`/`geometry` de um widget dentro de um layout que e reconstruido com
frequencia (ex.: uma lista de mensagens re-renderizada a cada refresh) faz o
alvo da animacao ficar obsoleto em pleno voo e sobrepor outros itens.
`shake()` usa `pos`, entao so deve ser chamado em widgets de posicao estavel
(botoes fixos de barra de ferramentas/titulo) - nunca em itens de lista.
`pulse()` anima `iconSize`, que nunca afeta a posicao/tamanho do widget em si,
sendo seguro em qualquer contexto.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QSequentialAnimationGroup, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import QWidget

_ACTIVE_SHORT: dict[int, object] = {}
_ACTIVE_ROTATION: dict[int, object] = {}


def _stop_short(widget: QWidget) -> None:
    existing = _ACTIVE_SHORT.pop(id(widget), None)
    if existing is not None:
        existing.stop()


def _track_short(widget: QWidget, anim) -> None:
    _stop_short(widget)
    _ACTIVE_SHORT[id(widget)] = anim
    cleanup = lambda: _ACTIVE_SHORT.pop(id(widget), None)  # noqa: E731
    anim.finished.connect(cleanup)
    # Se o widget for destruido antes da animacao terminar sozinha (ex.:
    # dialog fechado no meio de um pulse), tira a referencia do dict pra nao
    # ficar segurando um QPropertyAnimation preso a um widget morto.
    widget.destroyed.connect(cleanup)
    anim.start(QPropertyAnimation.DeleteWhenStopped)


def pulse(widget: QWidget, duration: int = 220, grow: float = 1.3) -> None:
    """Cresce e volta o iconSize do botao uma vez. `widget` precisa expor a
    propriedade Qt `iconSize` (QAbstractButton e subclasses)."""
    if not widget.isEnabled():
        return
    base = widget.iconSize()
    grown = base * grow

    group = QSequentialAnimationGroup(widget)
    up = QPropertyAnimation(widget, b"iconSize", widget)
    up.setDuration(max(1, duration // 2))
    up.setStartValue(base)
    up.setEndValue(grown)
    up.setEasingCurve(QEasingCurve.OutCubic)
    down = QPropertyAnimation(widget, b"iconSize", widget)
    down.setDuration(max(1, duration // 2))
    down.setStartValue(grown)
    down.setEndValue(base)
    down.setEasingCurve(QEasingCurve.InCubic)
    group.addAnimation(up)
    group.addAnimation(down)
    _track_short(widget, group)


def shake(widget: QWidget, duration: int = 260, amplitude: int = 3) -> None:
    """Balanco horizontal curto que sempre termina exatamente na posicao
    original. Use somente em widgets de posicao estavel (ver aviso no topo
    do modulo)."""
    if not widget.isEnabled():
        return
    origin = widget.pos()
    offsets = [amplitude, -amplitude, amplitude, -amplitude, 0]

    group = QSequentialAnimationGroup(widget)
    step_duration = max(20, duration // len(offsets))
    previous = origin
    for offset in offsets:
        target = QPoint(origin.x() + offset, origin.y())
        step = QPropertyAnimation(widget, b"pos", widget)
        step.setDuration(step_duration)
        step.setStartValue(previous)
        step.setEndValue(target)
        step.setEasingCurve(QEasingCurve.InOutSine)
        group.addAnimation(step)
        previous = target
    _track_short(widget, group)


def rotate_while(widget: QWidget, active: bool, duration: int = 900) -> None:
    """Gira o icone continuamente enquanto `active` for True; `active=False`
    para imediatamente e restaura o icone original. Pensado pra acoes de
    "atualizar"/loading - nunca fica girando por engano porque quem chamou
    controla explicitamente o inicio/fim."""
    key = id(widget)
    existing = _ACTIVE_ROTATION.pop(key, None)
    base_icon = getattr(widget, "_icon_motion_base_icon", None)
    if existing is not None:
        existing.stop()
    if base_icon is not None and not active:
        widget.setIcon(base_icon)

    if not active or not widget.isEnabled():
        return

    base_icon = widget.icon()
    widget._icon_motion_base_icon = base_icon
    base_pixmap = base_icon.pixmap(widget.iconSize())
    if base_pixmap.isNull():
        return

    from PySide6.QtCore import QVariantAnimation

    anim = QVariantAnimation(widget)
    anim.setStartValue(0.0)
    anim.setEndValue(360.0)
    anim.setDuration(duration)
    anim.setLoopCount(-1)

    def _apply(angle: float) -> None:
        transform = QTransform()
        transform.translate(base_pixmap.width() / 2, base_pixmap.height() / 2)
        transform.rotate(angle)
        transform.translate(-base_pixmap.width() / 2, -base_pixmap.height() / 2)
        rotated = base_pixmap.transformed(transform, Qt.SmoothTransformation)
        centered = QPixmap(base_pixmap.size())
        centered.fill(Qt.transparent)
        painter = QPainter(centered)
        painter.drawPixmap(
            round((centered.width() - rotated.width()) / 2),
            round((centered.height() - rotated.height()) / 2),
            rotated,
        )
        painter.end()
        widget.setIcon(QIcon(centered))

    anim.valueChanged.connect(_apply)
    widget.destroyed.connect(lambda: _ACTIVE_ROTATION.pop(key, None))
    _ACTIVE_ROTATION[key] = anim
    anim.start(QVariantAnimation.DeleteWhenStopped)
