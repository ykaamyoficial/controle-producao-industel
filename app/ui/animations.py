from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QVariantAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

# Curva unica do padrao visual: cubic-bezier(.23, 1, .32, 1) - sai rapido e
# assenta devagar. Duracoes de referencia (ms): hover 140, clique 80,
# marcador que desliza 240, entrada de conteudo 180-240.
STANDARD_CURVE = QEasingCurve(QEasingCurve.BezierSpline)
STANDARD_CURVE.addCubicBezierSegment(QPointF(0.23, 1.0), QPointF(0.32, 1.0), QPointF(1.0, 1.0))

_reduced_motion = False


def set_reduced_motion(enabled: bool) -> None:
    """Liga/desliga "reduzir animacoes" para o processo inteiro (chave
    `reduce_motion` da configuracao). Com ela ligada toda duracao vira zero."""
    global _reduced_motion
    _reduced_motion = bool(enabled)


def reduced_motion() -> bool:
    return _reduced_motion


def motion_duration(milliseconds: int) -> int:
    return 0 if _reduced_motion else max(0, int(milliseconds))


def animate_value(widget: QWidget, attribute: str, end: float, duration: int) -> None:
    """Anima um atributo float de um widget pintado a mao (ex.: `_hover`) e
    chama `update()` a cada passo. Uma animacao por atributo e reaproveitada,
    entao entrar/sair rapido do widget nunca empilha animacoes."""
    animations = widget.__dict__.setdefault("_value_animations", {})
    animation = animations.get(attribute)
    if animation is None:
        animation = QVariantAnimation(widget)
        animation.setEasingCurve(STANDARD_CURVE)

        def apply(value, name=attribute):
            setattr(widget, name, value)
            widget.update()

        animation.valueChanged.connect(apply)
        animations[attribute] = animation
    animation.stop()
    duration = motion_duration(duration)
    if duration <= 0:
        setattr(widget, attribute, float(end))
        widget.update()
        return
    animation.setDuration(duration)
    animation.setStartValue(float(getattr(widget, attribute)))
    animation.setEndValue(float(end))
    animation.start()


def animate_width(widget: QWidget, start: int, end: int, duration: int = 220) -> QPropertyAnimation:
    animation = QPropertyAnimation(widget, b"minimumWidth", widget)
    animation.setDuration(motion_duration(duration))
    animation.setStartValue(start)
    animation.setEndValue(end)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    animation.start()
    return animation


def fade_in(widget: QWidget, duration: int = 180) -> QPropertyAnimation:
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(motion_duration(duration))
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    animation.finished.connect(lambda: widget.setGraphicsEffect(None))
    animation.start()
    return animation
