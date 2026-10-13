"""Casca das janelas que abrem por cima do programa: canto liso de 24 px,
borda com volume, sombra propria e abrir/fechar com mola.

Padrao aprovado em 13/10/2026 (prototipos/acoes_proposta/acoes.py); plano em
docs/architecture/PADRAO_JANELAS_PLANO_MIGRACAO.md.

A casca e instalada de fora, por `install_window_shell()`, chamada do ponto
unico dos dialogos (`style_dialog_from_parent()`): nenhum dialogo troca de
classe-base. O que ela faz com o dialogo:

- tira a moldura do Windows e deixa o fundo transparente; a moldura (aro,
  filete de luz, sombreado e duas sombras) e pintada com suavizacao no lugar
  do `paintEvent` do QDialog. Nada de mascara: mascara so liga ou desliga o
  pixel inteiro e deixa a curva serrilhada;
- reserva em volta uma margem transparente onde a sombra e pintada, somando-a
  ao tamanho que o dialogo pediu;
- ao abrir, cobre o dialogo com uma cortina que pinta uma foto dele saltando
  para o lugar; ao fechar, a foto encolhe e some, e so entao o `done()` de
  verdade roda. `exec()`, `finished` e `accept()`/`reject()` proprios seguem
  valendo.

Regras que vieram de medicao e nao podem ser desfeitas sem medir de novo:
o relogio da entrada so parte depois do primeiro quadro pintado; a cortina se
declara opaca para o Qt nao redesenhar tabela a cada quadro; fechamento pedido
de fora (Alt+F4, programa encerrando) nao espera a saida.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QSizeGrip, QWidget

from app.ui.animations import SPRING_MS, spring, transition, window_motion_enabled
from app.ui.theme_tokens import active_tokens, relative_luminance

WINDOW_RADIUS = 24
SHADOW_MARGIN = 48
ENTER_SCALE = 0.88  # a janela nasce com este tamanho e salta para 100%
EXIT_SCALE = 0.94  # e encolhe ate este enquanto some
APPEAR_MS = 160
EXIT_MS = 180
HEADER_DRAG_HEIGHT = 64
_GRIP_INSET = 9  # afasta a alca de redimensionar da curva do canto
_QWIDGETSIZE_MAX = 16777215

# Chave de ativacao. Enquanto as telas sao conferidas grupo a grupo a casca
# nova fica desligada por padrao; INDUSTEL_WINDOW_SHELL=1 liga e =0 desliga.
_enabled = os.environ.get("INDUSTEL_WINDOW_SHELL", "0") == "1"


def window_shell_enabled() -> bool:
    return _enabled


def set_window_shell_enabled(enabled: bool) -> None:
    global _enabled
    _enabled = bool(enabled)


def is_dark_theme() -> bool:
    return relative_luminance(active_tokens()["bg"]) < 0.2


def _tint(token: str, alpha: float) -> QColor:
    color = QColor(active_tokens()[token])
    color.setAlpha(max(0, min(255, round(alpha))))
    return color


def paint_shell_shadow(painter: QPainter, area: QRectF, radius: float, reach: float = 1.0) -> None:
    """Duas sombras em camadas: uma larga e fraca, que afasta a janela do
    fundo, e uma curta e mais escura colada na borda. `reach` encolhe as duas
    para popups e menus."""
    dark = is_dark_theme()
    painter.setPen(Qt.NoPen)
    for layers, step, drop, peak in ((30, 0.95, 14, 11 if dark else 7), (6, 1.0, 2, 16 if dark else 11)):
        for index in range(layers):
            weight = 1 - index / layers
            spread = (1 + index * step) * reach
            sink = drop * reach
            painter.setBrush(_tint("shell_ink", peak * weight * weight))
            painter.drawRoundedRect(area.adjusted(-spread, -spread + sink, spread, spread + sink), radius + spread, radius + spread)


def paint_shell_body(painter: QPainter, area: QRectF, radius: float) -> None:
    """Corpo da janela com um pouco de volume, como uma placa iluminada de
    cima: aro fino por fora, filete de luz logo por dentro (forte no alto) e
    sombreado na borda de baixo. O miolo e a cor `bg` chapada, para qualquer
    area de rolagem ou painel com esse mesmo fundo sumir nele."""
    dark = is_dark_theme()
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(active_tokens()["bg"]))
    painter.drawRoundedRect(area, radius, radius)

    # Chanfro: aneis concentricos cada vez mais fracos para dentro; a luz vem
    # de cima, entao o alto clareia e a base escurece.
    painter.setBrush(Qt.NoBrush)
    rings = 5
    for index in range(rings):
        strength = (1 - index / rings) ** 2
        light = QLinearGradient(area.topLeft(), area.bottomLeft())
        light.setColorAt(0.0, _tint("shell_light", (80 if dark else 255) * strength))
        light.setColorAt(0.3, _tint("shell_light", (14 if dark else 90) * strength))
        light.setColorAt(0.7, _tint("shell_ink", (30 if dark else 6) * strength))
        light.setColorAt(1.0, _tint("shell_ink", (150 if dark else 44) * strength))
        inset = 1.5 + index
        painter.setPen(QPen(QBrush(light), 1))
        painter.drawRoundedRect(area.adjusted(inset, inset, -inset, -inset), radius - inset, radius - inset)

    # Aro externo: da o recorte nitido contra qualquer fundo.
    painter.setPen(QPen(_tint("shell_ink", 200 if dark else 60), 1))
    painter.drawRoundedRect(area.adjusted(0.5, 0.5, -0.5, -0.5), radius - 0.5, radius - 0.5)


class _Curtain(QWidget):
    """Fica por cima da janela enquanto ela abre ou fecha e pinta, no lugar do
    conteudo, a foto dela mudando de tamanho e de opacidade.

    O conteudo de verdade continua embaixo, ja no lugar definitivo: na entrada
    a cortina deixa o mouse passar, entao a janela aceita clique e teclado
    desde o primeiro quadro. Na saida ela segura mouse e teclado. Declara-se
    opaca (repinta todos os seus pixels, apagando antes o que havia) para o Qt
    nao redesenhar o conteudo a cada quadro.
    """

    def __init__(self, window: QWidget, snapshot: QPixmap, scale: float, opacity: float, pass_mouse: bool):
        super().__init__(window)
        self._snapshot = snapshot
        self._scale = scale
        self._opacity = opacity
        self.on_first_paint = None
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, pass_mouse)
        self.setGeometry(window.rect())
        self.show()
        self.raise_()

    def hold_input(self) -> None:
        """Saida: nada do que esta embaixo recebe mais clique nem tecla."""
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFocus(Qt.OtherFocusReason)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        event.accept()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        center = QRectF(self.rect()).center()
        painter.setOpacity(max(0.0, min(1.0, self._opacity)))
        painter.translate(center)
        painter.scale(self._scale, self._scale)
        painter.translate(-center)
        painter.drawPixmap(0, 0, self._snapshot)
        painter.end()
        if self.on_first_paint is not None:
            callback, self.on_first_paint = self.on_first_paint, None
            QTimer.singleShot(0, self, callback)


class WindowShell(QObject):
    """Acompanha um dialogo: pinta a moldura, reserva a margem da sombra,
    anima a entrada e a saida e arrasta a janela pelo topo."""

    def __init__(self, dialog: QWidget, *, radius: int = WINDOW_RADIUS, margin: int = SHADOW_MARGIN):
        super().__init__(dialog)
        self._dialog = dialog
        self.radius = radius
        self.margin = margin
        self._frame: QPixmap | None = None
        self._frame_key = None
        self._curtain: _Curtain | None = None
        self._grip: QSizeGrip | None = None
        self._prepared = False
        self._entered = True
        self._closing = False
        self._external_close = False
        self._drag_offset: QPoint | None = None
        self._original_done = dialog.done
        dialog.setWindowFlag(Qt.FramelessWindowHint, True)
        dialog.setAttribute(Qt.WA_TranslucentBackground, True)
        dialog.setProperty("windowShell", True)
        # Gancho por instancia: accept(), reject() e Esc chegam aqui antes do
        # done() da classe, que e chamado quando a saida termina.
        dialog.done = self._done
        dialog.installEventFilter(self)

    # -- geometria -------------------------------------------------------

    def area(self) -> QRectF:
        """A parte visivel da janela, sem a faixa da sombra."""
        margin = self.margin
        return QRectF(self._dialog.rect()).adjusted(margin, margin, -margin, -margin)

    def outline(self) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(self.area(), self.radius, self.radius)
        return path

    def refresh(self) -> None:
        """Tema trocado com a janela aberta: repinta a moldura."""
        self._frame = None
        self._dialog.update()

    def _reserve_shadow_margin(self) -> None:
        """Soma a margem da sombra ao que o dialogo pediu: margens do conteudo,
        minimo e maximo explicitos, tamanho e posicao."""
        dialog = self._dialog
        margin = self.margin
        layout = dialog.layout()
        implicit = layout.totalMinimumSize() if layout is not None else None
        minimum = dialog.minimumSize()
        maximum = dialog.maximumSize()
        size = dialog.size()
        inner = dialog.contentsMargins()
        dialog.setContentsMargins(inner.left() + margin, inner.top() + margin, inner.right() + margin, inner.bottom() + margin)
        if maximum.width() < _QWIDGETSIZE_MAX:
            dialog.setMaximumWidth(maximum.width() + 2 * margin)
        if maximum.height() < _QWIDGETSIZE_MAX:
            dialog.setMaximumHeight(maximum.height() + 2 * margin)
        # Minimo que o proprio layout calcula cresce sozinho com a margem; so
        # o que foi fixado a mao (setMinimumWidth(720)) precisa ser somado.
        if minimum.width() > 0 and (implicit is None or minimum.width() != implicit.width()):
            dialog.setMinimumWidth(minimum.width() + 2 * margin)
        if minimum.height() > 0 and (implicit is None or minimum.height() != implicit.height()):
            dialog.setMinimumHeight(minimum.height() + 2 * margin)
        dialog.resize(size.width() + 2 * margin, size.height() + 2 * margin)
        if dialog.testAttribute(Qt.WA_Moved):
            dialog.move(dialog.x() - margin, dialog.y() - margin)

    def _place_grip(self) -> None:
        """A alca de redimensionar do QDialog nasce no canto da janela, que
        agora e sombra: fica no canto da parte visivel."""
        dialog = self._dialog
        grip = dialog.findChild(QSizeGrip, options=Qt.FindDirectChildrenOnly)
        if grip is None:
            return
        if grip is not self._grip:
            self._grip = grip
            grip.installEventFilter(self)
        offset = self.margin + _GRIP_INSET
        target = QPoint(dialog.width() - offset - grip.width(), dialog.height() - offset - grip.height())
        if grip.pos() != target:
            grip.move(target)

    # -- pintura ---------------------------------------------------------

    def _paint_frame(self) -> None:
        dialog = self._dialog
        ratio = dialog.devicePixelRatioF()
        key = (dialog.width(), dialog.height(), ratio, active_tokens()["bg"])
        if self._frame is None or self._frame_key != key:
            frame = QPixmap(dialog.size() * ratio)
            frame.setDevicePixelRatio(ratio)
            frame.fill(Qt.transparent)
            painter = QPainter(frame)
            painter.setRenderHint(QPainter.Antialiasing)
            paint_shell_shadow(painter, self.area(), self.radius)
            paint_shell_body(painter, self.area(), self.radius)
            painter.end()
            self._frame, self._frame_key = frame, key
        painter = QPainter(dialog)
        painter.drawPixmap(0, 0, self._frame)
        painter.end()

    # -- abrir e fechar --------------------------------------------------

    def _scrim(self, action: str) -> None:
        binding = getattr(self._dialog, "_scrim_binding", None)
        if binding is not None:
            getattr(binding, action)()

    def _drop_curtain(self) -> None:
        curtain, self._curtain = self._curtain, None
        if curtain is not None:
            curtain.hide()
            curtain.deleteLater()

    def _on_show(self) -> None:
        dialog = self._dialog
        self._closing = False
        if not self._prepared:
            self._prepared = True
            self._reserve_shadow_margin()
        self._place_grip()
        self._drop_curtain()
        if not window_motion_enabled():
            self._entered = True
            return
        # Os filhos ja foram exibidos e a janela ainda nao esta na tela: o
        # primeiro quadro que o usuario ve ja e o da animacao. O relogio so
        # parte quando esse quadro e pintado; se partisse aqui, o tempo de o
        # Windows criar a janela comia o comeco do salto.
        self._entered = False
        self._curtain = _Curtain(dialog, dialog.grab(), ENTER_SCALE, 0.0, pass_mouse=True)
        self._curtain.on_first_paint = self._start_entrance

    def _start_entrance(self) -> None:
        curtain = self._curtain
        if curtain is None or self._closing:
            return
        self._entered = True
        self._scrim("darken")
        transition(curtain, "_opacity", 1.0, APPEAR_MS)
        transition(curtain, "_scale", 1.0, SPRING_MS, spring, self._drop_curtain)

    def _done(self, result: int) -> None:
        if self._closing:
            return
        dialog = self._dialog
        waiting_first_frame = self._curtain is not None and not self._entered
        if not window_motion_enabled() or not dialog.isVisible() or self._external_close or waiting_first_frame:
            self._drop_curtain()
            self._original_done(result)
            return
        self._closing = True
        if self._curtain is None:
            self._curtain = _Curtain(dialog, dialog.grab(), 1.0, 1.0, pass_mouse=False)
        # Fechou no meio da entrada: a foto sai do tamanho em que estava.
        self._curtain.hold_input()
        self._scrim("lighten")
        transition(self._curtain, "_scale", EXIT_SCALE, EXIT_MS)
        transition(self._curtain, "_opacity", 0.0, EXIT_MS, on_finished=lambda: self._original_done(result))

    def _forget_external_close(self) -> None:
        self._external_close = False

    # -- eventos ---------------------------------------------------------

    def eventFilter(self, watched, event):  # noqa: N802 (Qt override)
        kind = event.type()
        if watched is self._grip:
            if kind == QEvent.Move:
                self._place_grip()
            return False
        dialog = self._dialog
        if watched is not dialog:
            return False
        if kind == QEvent.Paint:
            self._paint_frame()
            return True  # no lugar do paintEvent do QDialog
        if kind == QEvent.Show:
            if not event.spontaneous():
                self._on_show()
        elif kind == QEvent.Resize:
            self._frame = None
            if self._curtain is not None:
                self._curtain.setGeometry(dialog.rect())
            self._place_grip()
        elif kind == QEvent.StyleChange:
            self._frame = None
        elif kind == QEvent.Close:
            # Fechamento pedido de fora (Alt+F4, programa encerrando) nao
            # espera a saida: o QDialog recusa o fechamento se a janela ainda
            # estiver visivel depois do reject(), e isso cancelaria ate o
            # encerramento do programa.
            self._external_close = True
            QTimer.singleShot(0, self, self._forget_external_close)
        elif kind == QEvent.Hide:
            self._drop_curtain()
            self._closing = False
        elif kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            area = self.area()
            if QRectF(area.left(), area.top(), area.width(), HEADER_DRAG_HEIGHT).contains(event.position()):
                self._drag_offset = event.globalPosition().toPoint() - dialog.frameGeometry().topLeft()
        elif kind == QEvent.MouseMove and self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            dialog.move(event.globalPosition().toPoint() - self._drag_offset)
        elif kind == QEvent.MouseButtonRelease:
            self._drag_offset = None
        return False


def install_window_shell(dialog: QWidget) -> WindowShell:
    """Instala a casca no dialogo; chamar de novo so repinta a moldura (e o
    que acontece quando o tema muda com a janela aberta)."""
    shell = getattr(dialog, "_window_shell", None)
    if shell is not None:
        shell.refresh()
        return shell
    shell = WindowShell(dialog)
    dialog._window_shell = shell
    return shell
