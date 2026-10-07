"""Pecas das telas que abrem por cima do programa (skill qt-industrial-ui,
references/janelas-sobrepostas.md): paineis, grades chave/valor, numeros de
resumo, barra de progresso, trilha do fluxo e abas com contagem.

Tudo aqui e so apresentacao - nenhuma regra de negocio. As cores vem de
`active_tokens()` ou da folha de estilo (`app/ui/styles.py`).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget

from app.ui.animations import animate_value, fade_in, reduced_motion
from app.ui.components.count_tabs import CountTabs
from app.ui.icons import make_icon
from app.ui.styles import _contrast_text
from app.ui.theme_tokens import active_tokens

EMPTY_VALUES = ("", "-", "Não informado", "Nao informado", "Sem movimentação registrada", "Sem registro")
EM_DASH = "—"


# ---- paineis e textos ----------------------------------------------------
def make_panel(
    title: str | None = None,
    *,
    highlight: bool = False,
    left: QWidget | None = None,
    right: QWidget | None = None,
) -> tuple[QFrame, QVBoxLayout]:
    """Painel branco de raio 14 com titulo opcional. `highlight` da o fundo
    azul-claro com borda azulada (no maximo um por tela). O primeiro item do
    layout e sempre o cabecalho (titulo + widgets a esquerda/direita)."""
    panel = QFrame()
    panel.setObjectName("DetailPanelHighlight" if highlight else "DetailPanel")
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(10)
    if title is not None:
        header = QHBoxLayout()
        header.setSpacing(10)
        if left is not None:
            header.addWidget(left)
        label = QLabel(title)
        label.setObjectName("PanelTitle")
        header.addWidget(label)
        header.addStretch(1)
        if right is not None:
            header.addWidget(right)
        layout.addLayout(header)
    return panel, layout


def clear_panel(panel: QFrame, keep: int = 1) -> None:
    """Remove tudo do painel menos os `keep` primeiros itens (o cabecalho)."""
    layout = panel.layout()
    while layout.count() > keep:
        _dispose(layout.takeAt(keep))


def _dispose(item) -> None:
    widget = item.widget()
    if widget is not None:
        widget.deleteLater()
        return
    child_layout = item.layout()
    if child_layout is not None:
        while child_layout.count():
            _dispose(child_layout.takeAt(0))


def key_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("KeyLabel")
    return label


def value_label(text: str) -> QLabel:
    """Valor em destaque; valor ausente vira travessao em cor discreta."""
    text = str(text if text is not None else "")
    empty = text.strip() in EMPTY_VALUES
    label = QLabel(EM_DASH if text.strip() in ("", "-") else text)
    label.setObjectName("ValueEmpty" if empty else "ValueLabel")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


def kv_grid(rows: list[tuple[str, object]], key_width: int = 168) -> QGridLayout:
    """Chave a esquerda e valor a direita. O valor pode ser texto, um widget
    (ex.: selo) ou um layout (ex.: texto + barra de progresso)."""
    grid = QGridLayout()
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(8)
    for row, (key, value) in enumerate(rows):
        grid.addWidget(key_label(key), row, 0, Qt.AlignTop)
        if isinstance(value, QWidget):
            grid.addWidget(value, row, 1, Qt.AlignLeft | Qt.AlignVCenter)
        elif isinstance(value, (QVBoxLayout, QHBoxLayout)):
            grid.addLayout(value, row, 1)
        else:
            grid.addWidget(value_label(value), row, 1)
    grid.setColumnMinimumWidth(0, key_width)
    grid.setColumnStretch(1, 1)
    return grid


def block_grid(rows: list[tuple[str, str]], columns: int = 3) -> QGridLayout:
    """Chave em cima e valor embaixo, em varias colunas - para grupos de numeros."""
    grid = QGridLayout()
    grid.setHorizontalSpacing(24)
    grid.setVerticalSpacing(12)
    for index, (key, value) in enumerate(rows):
        block = QVBoxLayout()
        block.setSpacing(2)
        block.addWidget(key_label(key))
        block.addWidget(value_label(value))
        grid.addLayout(block, index // columns, index % columns)
    for column in range(columns):
        grid.setColumnStretch(column, 1)
    return grid


def stat_block(number: str, caption: str) -> QVBoxLayout:
    """Numero grande com legenda - resumo de uma lista, acima da tabela."""
    block = QVBoxLayout()
    block.setSpacing(0)
    number_label = QLabel(str(number))
    number_label.setObjectName("StatNumber")
    block.addWidget(number_label)
    block.addWidget(key_label(caption))
    return block


def note_box(text: str, palette: dict | None = None) -> QFrame:
    """Observacao fixa: caixa azul-clara com icone de informacao."""
    box = QFrame()
    box.setObjectName("NoteBox")
    row = QHBoxLayout(box)
    row.setContentsMargins(12, 9, 12, 9)
    row.setSpacing(10)
    icon = QLabel()
    accent = (palette or active_tokens()).get("accent", "#006fc9")
    icon.setPixmap(make_icon("info", accent, 16).pixmap(16, 16))
    row.addWidget(icon, 0, Qt.AlignTop)
    label = QLabel(text)
    label.setObjectName("KeyLabel")
    label.setWordWrap(True)
    row.addWidget(label, 1)
    return box


# ---- widgets pintados ----------------------------------------------------
class ThinProgressBar(QWidget):
    """Barra de progresso fina (6 px); enche ao aparecer."""

    def __init__(self, fraction: float = 0.0, parent=None, *, color: str | None = None, height: int = 6):
        super().__init__(parent)
        self._target = 0.0
        self._value = 0.0
        # `color` e uma cor de token (cor de area, status); sem ela vale o destaque.
        self._color = color
        self._height = height
        self.setFixedHeight(height)
        self.setMinimumWidth(120)
        self.set_fraction(fraction)

    def set_fraction(self, fraction: float) -> None:
        self._target = max(0.0, min(1.0, float(fraction or 0.0)))
        if self.isVisible():
            animate_value(self, "_value", self._target, 600)
        else:
            self._value = self._target
            self.update()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._value = 0.0
        animate_value(self, "_value", self._target, 600)
        super().showEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        tokens = active_tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        radius = self._height / 2
        painter.setBrush(QColor(tokens["surface_alt"]))
        painter.drawRoundedRect(QRectF(self.rect()), radius, radius)
        if self._value > 0:
            painter.setBrush(QColor(self._color or tokens["accent"]))
            width = max(float(self._height), self.width() * self._value)
            painter.drawRoundedRect(QRectF(0, 0, width, self._height), radius, radius)
        painter.end()


class IconChip(QWidget):
    """Icone dentro de um circulo, a esquerda do titulo de um painel."""

    def __init__(self, icon_name: str, color: str, parent=None, *, size: int = 32):
        super().__init__(parent)
        self._icon_name = icon_name
        self._color = color
        self._size = size
        self.setFixedSize(size, size)

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        tokens = active_tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(tokens["border"]), 1))
        painter.setBrush(QColor(tokens["surface_alt"]))
        painter.drawEllipse(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        icon = self._size // 2
        offset = (self._size - icon) // 2
        painter.drawPixmap(offset, offset, make_icon(self._icon_name, self._color, icon).pixmap(icon, icon))
        painter.end()


# Estados de uma etapa da trilha.
STEP_DONE = "done"
STEP_CURRENT = "current"
STEP_ACTIVE = "active"
STEP_BLOCKED = "blocked"
STEP_PENDING = "pending"


class FlowTrail(QWidget):
    """Fluxo da proposta como uma trilha: etapa concluida (check), etapa atual
    (pulsa), em andamento (cor do status), bloqueada (X) e pendente
    (tracejada), com o nome e o status escritos embaixo de cada uma - o
    estado nunca depende so da cor.

    `set_steps([{"name", "state", "label", "color"}, ...])`.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._steps: list[dict] = []
        self._pulse = 0.0
        self.setFixedHeight(92)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(1700)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setLoopCount(-1)
        self._animation.valueChanged.connect(self._advance)

    def set_steps(self, steps: list[dict]) -> None:
        self._steps = list(steps)
        self.update()

    def steps(self) -> list[dict]:
        return list(self._steps)

    def _advance(self, value) -> None:
        self._pulse = value
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if not reduced_motion():
            self._animation.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._animation.stop()
        super().hideEvent(event)

    def _draw_glyph(self, painter: QPainter, state: str, x: float, y: float, color: QColor) -> None:
        pen = QPen(color, 2)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        if state == STEP_DONE:
            path = QPainterPath(QPointF(x - 5, y))
            path.lineTo(x - 1.5, y + 3.5)
            path.lineTo(x + 5, y - 3.5)
            painter.drawPath(path)
        elif state == STEP_CURRENT:
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            path = QPainterPath(QPointF(x - 3, y - 5))
            path.lineTo(x + 5, y)
            path.lineTo(x - 3, y + 5)
            path.closeSubpath()
            painter.drawPath(path)
        elif state == STEP_ACTIVE:
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            for offset in (-5, 0, 5):
                painter.drawEllipse(QPointF(x + offset, y), 1.6, 1.6)
        elif state == STEP_BLOCKED:
            painter.drawLine(QPointF(x - 4, y - 4), QPointF(x + 4, y + 4))
            painter.drawLine(QPointF(x + 4, y - 4), QPointF(x - 4, y + 4))
        else:
            painter.drawLine(QPointF(x - 2.5, y - 4), QPointF(x - 2.5, y + 4))
            painter.drawLine(QPointF(x + 2.5, y - 4), QPointF(x + 2.5, y + 4))

    def paintEvent(self, _event) -> None:  # noqa: N802
        if not self._steps:
            return
        tokens = active_tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        total = len(self._steps)
        margin = 84
        step = min(236.0, (self.width() - 2 * margin) / max(1, total - 1))
        xs = [margin + index * step for index in range(total)]
        center_y = 24.0
        done_color = QColor(tokens.get("success", tokens["accent"]))
        for index in range(total - 1):
            if self._steps[index + 1]["state"] == STEP_PENDING:
                painter.setPen(QPen(QColor(tokens["input_border"]), 2, Qt.DashLine))
            else:
                painter.setPen(QPen(done_color, 3))
            painter.drawLine(QPointF(xs[index] + 22, center_y), QPointF(xs[index + 1] - 22, center_y))
        name_font = QFont(self.font())
        name_font.setPixelSize(13)
        label_font = QFont(self.font())
        label_font.setPixelSize(12)
        for x, item in zip(xs, self._steps):
            state = item["state"]
            color = done_color if state == STEP_DONE else QColor(item.get("color") or tokens["accent"])
            center = QPointF(x, center_y)
            if state == STEP_CURRENT and self._animation.state() == QVariantAnimation.Running:
                halo = QColor(color)
                halo.setAlphaF(0.38 * (1 - self._pulse))
                painter.setPen(Qt.NoPen)
                painter.setBrush(halo)
                painter.drawEllipse(center, 16 + 10 * self._pulse, 16 + 10 * self._pulse)
            if state == STEP_PENDING:
                painter.setPen(QPen(QColor(tokens["input_border"]), 1.5, Qt.DashLine))
                painter.setBrush(QColor(tokens["surface"]))
                painter.drawEllipse(center, 15, 15)
                self._draw_glyph(painter, state, x, center_y, QColor(tokens["subtle"]))
            else:
                painter.setPen(Qt.NoPen)
                painter.setBrush(color)
                painter.drawEllipse(center, 16, 16)
                self._draw_glyph(painter, state, x, center_y, QColor(_contrast_text(color.name())))
            name_font.setWeight(QFont.Weight.Bold if state == STEP_CURRENT else QFont.Weight.DemiBold)
            painter.setFont(name_font)
            painter.setPen(QColor(tokens["text"]))
            painter.drawText(QRectF(x - 110, 48, 220, 18), Qt.AlignCenter, str(item.get("name") or ""))
            painter.setFont(label_font)
            painter.setPen(QColor(tokens["muted"]))
            painter.drawText(QRectF(x - 110, 67, 220, 16), Qt.AlignCenter, str(item.get("label") or ""))
        painter.end()


class CountTabWidget(QWidget):
    """Abas das telas sobrepostas: barra `CountTabs` + paginas. Mantem o
    pedaco da API do QTabWidget que as telas usavam (`addTab`, `count`,
    `tabText`, `widget`, `currentIndex`, `setCurrentIndex`) e acrescenta
    `set_tab_count()` para a contagem ao lado do nome."""

    currentChanged = Signal(int)  # noqa: N815 (mesmo nome do QTabWidget)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._titles: list[str] = []
        self._counts: list[int | None] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.bar = CountTabs()
        self.stack = QStackedWidget()
        layout.addWidget(self.bar)
        layout.addWidget(self.stack, 1)
        self.bar.changed.connect(self._on_bar_changed)

    def addTab(self, widget: QWidget, title: str, count: int | None = None) -> int:  # noqa: N802
        self._titles.append(title)
        self._counts.append(count)
        index = self.stack.addWidget(widget)
        self.bar.set_tabs(list(zip(self._titles, self._counts)))
        return index

    def count(self) -> int:
        return len(self._titles)

    def tabText(self, index: int) -> str:  # noqa: N802
        return self._titles[index] if 0 <= index < len(self._titles) else ""

    def widget(self, index: int) -> QWidget | None:
        return self.stack.widget(index)

    def currentIndex(self) -> int:  # noqa: N802
        return self.stack.currentIndex()

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        self.bar.set_current_index(index)

    def set_tab_count(self, index: int, count: int | None) -> None:
        if 0 <= index < len(self._counts):
            self._counts[index] = count
            self.bar.set_count(index, count)

    def _on_bar_changed(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        page = self.stack.currentWidget()
        if page is not None and self.isVisible():
            self._page_fade = fade_in(page, duration=160)
        self.currentChanged.emit(index)
