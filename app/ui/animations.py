from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect, QVariantAnimation
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

# Curva unica do padrao visual: cubic-bezier(.23, 1, .32, 1) - sai rapido e
# assenta devagar. Duracoes de referencia (ms): hover 140, clique 80,
# marcador que desliza 240, entrada de conteudo 180-240.
STANDARD_CURVE = QEasingCurve(QEasingCurve.BezierSpline)
STANDARD_CURVE.addCubicBezierSegment(QPointF(0.23, 1.0), QPointF(0.32, 1.0), QPointF(1.0, 1.0))

# Janelas (abrir, fechar, veu): curva padrao do Core Animation,
# cubic-bezier(.25, .1, .25, 1), e uma mola pouco amortecida para o salto de
# entrada - ver docs/architecture/PADRAO_JANELAS_PLANO_MIGRACAO.md.
WINDOW_CURVE = QEasingCurve(QEasingCurve.BezierSpline)
WINDOW_CURVE.addCubicBezierSegment(QPointF(0.25, 0.1), QPointF(0.25, 1.0), QPointF(1.0, 1.0))
SPRING_MS = 550  # ate a mola assentar; a janela ja parece no lugar em ~200 ms
SPRING_RESPONSE = 0.40  # segundos de um ciclo: menor = mais rapida
SPRING_DAMPING = 0.68  # 1 = sem quique; 0.68 passa ~5% do ponto

_reduced_motion = False
_window_motion_forced: bool | None = None


def set_reduced_motion(enabled: bool) -> None:
    """Liga/desliga "reduzir animacoes" para o processo inteiro (chave
    `reduce_motion` da configuracao). Com ela ligada toda duracao vira zero."""
    global _reduced_motion
    _reduced_motion = bool(enabled)


def reduced_motion() -> bool:
    return _reduced_motion


def motion_duration(milliseconds: int) -> int:
    return 0 if _reduced_motion else max(0, int(milliseconds))


def window_motion_enabled() -> bool:
    """Abrir/fechar animado de janela. Fica desligado com "reduzir animacoes" e
    nas plataformas sem tela (`offscreen`/`minimal`: a suite e o CI), onde
    ninguem ve a animacao e os testes esperam que accept()/reject() fechem o
    dialogo na hora."""
    if _window_motion_forced is not None:
        return _window_motion_forced
    if _reduced_motion:
        return False
    app = QGuiApplication.instance()
    return isinstance(app, QGuiApplication) and app.platformName() not in ("offscreen", "minimal")


def force_window_motion(enabled: bool | None) -> None:
    """So para teste: liga (True) ou desliga (False) a animacao de janela em
    qualquer plataforma; None volta a regra normal."""
    global _window_motion_forced
    _window_motion_forced = enabled


def ease(progress: float) -> float:
    return WINDOW_CURVE.valueForProgress(progress)


def spring(progress: float) -> float:
    """Mola das janelas: devolve quanto do caminho ja foi andado e passa de 1
    no quique antes de assentar. `progress` vai de 0 a 1 ao longo de SPRING_MS."""
    elapsed = progress * SPRING_MS / 1000
    natural = 2 * math.pi / SPRING_RESPONSE
    decay = SPRING_DAMPING * natural
    swing = natural * math.sqrt(1 - SPRING_DAMPING**2)
    return 1 - math.exp(-decay * elapsed) * (math.cos(swing * elapsed) + decay / swing * math.sin(swing * elapsed))


def transition(widget: QWidget, attribute: str, end: float, duration: int, curve=ease, on_finished=None) -> None:
    """Anima um atributo pintado de `widget` ate `end` e chama `on_finished` na
    chegada. Uma animacao por atributo; `curve` recebe o progresso (0 a 1) e
    devolve quanto do caminho ja andou. Duracao zero (ou "reduzir animacoes")
    aplica o valor final e chama `on_finished` na hora."""
    animations = widget.__dict__.setdefault("_transitions", {})
    previous = animations.pop(attribute, None)
    if previous is not None:
        previous.stop()
        previous.deleteLater()
    start = float(getattr(widget, attribute))
    end = float(end)

    def arrived():
        animations.pop(attribute, None)
        setattr(widget, attribute, end)
        widget.update()
        if on_finished is not None:
            on_finished()

    duration = motion_duration(duration)
    if duration <= 0:
        arrived()
        return
    animation = QVariantAnimation(widget)
    animation.setDuration(duration)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)

    def apply(progress):
        setattr(widget, attribute, start + (end - start) * curve(progress))
        widget.update()

    animation.valueChanged.connect(apply)
    animation.finished.connect(arrived)
    animations[attribute] = animation
    animation.start()


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


def fade_out(widget: QWidget, duration: int = 160, on_finished=None) -> QPropertyAnimation:
    """Some com um widget filho por opacidade e chama `on_finished` no fim (o
    efeito grafico e temporario, como em `fade_in`)."""
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(motion_duration(duration))
    animation.setStartValue(1.0)
    animation.setEndValue(0.0)
    animation.setEasingCurve(WINDOW_CURVE)
    if on_finished is not None:
        animation.finished.connect(on_finished)
    animation.start()
    return animation


def painted_pixmap(widget: QWidget) -> QPixmap | None:
    """Foto do que `widget` ja pintou, copiada do backing store da janela dele
    (~3 ms). Repintar com `grab()` passa de 70 ms numa pagina inteira. Devolve
    None quando a janela ainda nao pintou nada (ou nao e de pixels comuns)."""
    window = widget.window()
    store = window.backingStore()
    image = store.paintDevice() if store is not None else None
    if not isinstance(image, QImage) or image.isNull():
        return None
    ratio = window.devicePixelRatioF()
    origin = widget.mapTo(window, QPoint(0, 0))
    area = QRect(round(origin.x() * ratio), round(origin.y() * ratio), round(widget.width() * ratio), round(widget.height() * ratio))
    if area.isEmpty() or not image.rect().contains(area):
        return None
    pixmap = QPixmap.fromImage(image.copy(area))
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


class _Backdrop(QWidget):
    """Foto da pagina que saiu, pintada ATRAS da pagina que entra."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._snapshot: QPixmap | None = None
        self.hide()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        if self._snapshot is not None:
            painter = QPainter(self)
            painter.drawPixmap(0, 0, self._snapshot)
            painter.end()


def crossfade(container: QWidget, incoming: QWidget, snapshot: QPixmap | None, duration: int = 200) -> QPropertyAnimation:
    """Troca de pagina sem piscar o fundo: `incoming` (a pagina nova, dentro
    de `container`) aparece por cima da foto da pagina antiga. `snapshot` vem
    de `painted_pixmap(container)` tirada ANTES da troca; sem ela vira o
    `fade_in` de sempre."""
    backdrop = None
    if snapshot is not None and motion_duration(duration) > 0:
        # Filho do proprio container, por baixo das paginas: fica acima do
        # fundo do container (que pode ser opaco) e abaixo de quem entra.
        backdrop = getattr(container, "_crossfade_backdrop", None)
        if backdrop is None:
            backdrop = _Backdrop(container)
            container._crossfade_backdrop = backdrop
        backdrop._snapshot = snapshot
        backdrop.setGeometry(container.rect())
        backdrop.lower()
        backdrop.show()
    animation = fade_in(incoming, duration=duration)
    animation.setEasingCurve(WINDOW_CURVE)
    if backdrop is not None:
        animation.finished.connect(backdrop.hide)
    return animation
