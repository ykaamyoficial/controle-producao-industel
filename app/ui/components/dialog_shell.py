"""Casca das telas que abrem por cima do programa (skill qt-industrial-ui,
references/janelas-sobrepostas.md).

- `dialog_header()`: cabecalho-cartao (titulo, subtitulo, linha de situacao e
  acoes a direita, com "Fechar" sempre por ultimo).
- `dialog_footer()`: rodape de acoes (Cancelar fantasma, Voltar secundario,
  confirmacao primaria), com espaco a esquerda para resumo/indicador de passo.
- `StepIndicator`: "Passo 2 de 5" dos assistentes.
- `standardize_tables()`: aparencia padrao das tabelas dentro de um dialogo.

Tudo aqui e apresentacao; nenhum dialogo perde widget: as funcoes recebem os
widgets que a tela ja criava (e que os testes consultam) e so os arrumam.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QSizePolicy,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme_tokens import active_tokens
from app.ui.fonts import scaled_px

DIALOG_MARGINS = (16, 14, 16, 14)
DIALOG_SPACING = 10
TABLE_ROW_HEIGHT = 40
TABLE_HEADER_HEIGHT = 34


def _as_label(value: str | QLabel, object_name: str) -> QLabel:
    label = value if isinstance(value, QLabel) else QLabel(str(value))
    label.setObjectName(object_name)
    return label


def _add(layout: QHBoxLayout | QVBoxLayout, item, *args) -> None:
    if isinstance(item, QLayout):
        layout.addLayout(item)
    elif item is not None:
        layout.addWidget(item, *args)


def dialog_layout(dialog: QWidget) -> QVBoxLayout:
    """Layout raiz com as margens e o espacamento padrao de janela sobreposta."""
    root = QVBoxLayout(dialog)
    root.setContentsMargins(*DIALOG_MARGINS)
    root.setSpacing(DIALOG_SPACING)
    return root


def dialog_header(
    title: str | QLabel,
    subtitle: str | QLabel | None = None,
    *,
    status: tuple | list = (),
    actions: tuple | list = (),
) -> QFrame:
    """Cabecalho-cartao. `title`/`subtitle` aceitam texto ou o QLabel que a
    tela ja tinha; `status` sao widgets da linha de situacao (selo, prazo);
    `actions` sao os botoes a direita, na ordem: secundarios, UM primario e
    "Fechar" por ultimo."""
    frame = QFrame()
    frame.setObjectName("DetailPanel")
    row = QHBoxLayout(frame)
    row.setContentsMargins(18, 12, 14, 12)
    row.setSpacing(8)

    text_column = QVBoxLayout()
    text_column.setSpacing(3)
    title_label = _as_label(title, "DetailTitle")
    title_label.setWordWrap(True)
    text_column.addWidget(title_label)
    subtitle_label = None
    if subtitle is not None:
        subtitle_label = _as_label(subtitle, "FilterSubtitle")
        subtitle_label.setWordWrap(True)
        text_column.addWidget(subtitle_label)
    if status:
        status_row = QHBoxLayout()
        status_row.setSpacing(12)
        for item in status:
            _add(status_row, item)
        status_row.addStretch(1)
        text_column.addSpacing(3)
        text_column.addLayout(status_row)
    row.addLayout(text_column, 1)
    for action in actions:
        _add(row, action, 0, Qt.AlignVCenter)
    frame.title_label = title_label
    frame.subtitle_label = subtitle_label
    return frame


def dialog_footer(*, left: tuple | list = (), right: tuple | list = ()) -> QFrame:
    """Rodape de acoes: `left` para resumo, aviso ou indicador de passo;
    `right` para os botoes, na ordem Cancelar, Voltar, confirmacao."""
    frame = QFrame()
    frame.setObjectName("DialogFooter")
    row = QHBoxLayout(frame)
    row.setContentsMargins(0, 10, 0, 0)
    row.setSpacing(8)
    flexible = False
    for item in left:
        if isinstance(item, QLabel):
            # Resumo/aviso longo quebra linha em vez de ser cortado pelos botoes.
            item.setWordWrap(True)
            item.setMinimumWidth(60)
            row.addWidget(item, 1)
            flexible = True
        else:
            _add(row, item)
    if not flexible:
        row.addStretch(1)
    for item in right:
        _add(row, item)
    return frame


def info_notice(text: str) -> QFrame:
    """Aviso fixo da tela: caixa azul-clara com icone de informacao (nunca
    texto solto em cinza). O QLabel com o texto fica em `frame.text_label`."""
    from app.ui.icons import make_icon

    frame = QFrame()
    frame.setObjectName("InfoNotice")
    row = QHBoxLayout(frame)
    row.setContentsMargins(14, 9, 14, 9)
    row.setSpacing(10)
    icon = QLabel()
    icon.setFixedSize(18, 18)
    icon.setPixmap(make_icon("info", active_tokens()["accent"], 18).pixmap(18, 18))
    label = QLabel(text)
    label.setWordWrap(True)
    row.addWidget(icon, 0, Qt.AlignVCenter)
    row.addWidget(label, 1)
    frame.text_label = label
    return frame


def set_notice_kind(label: QLabel, kind: str = "") -> QLabel:
    """Marca um QLabel como aviso em linha: "danger" (erro que bloqueia),
    "warning" (atencao) ou "" (informativo). A cor vem da folha de estilo
    pelo estado, nunca de `setStyleSheet` com hexadecimal."""
    label.setObjectName("InlineNotice")
    label.setProperty("kind", kind)
    label.style().unpolish(label)
    label.style().polish(label)
    return label


def set_validation_state(widget: QWidget, state: str = "") -> None:
    """Marca um campo como "error"/"warning" (ou limpa com ""); a borda vem da
    folha de estilo (`[validationState=...]`), nunca de `setStyleSheet`."""
    widget.setProperty("validationState", state)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class StepIndicator(QWidget):
    """"Passo 2 de 5" com uma trilha de segmentos; o passo atual e os ja
    feitos ficam na cor de destaque. O texto garante que a posicao nunca
    dependa so da cor."""

    def __init__(self, current: int, total: int, parent=None):
        super().__init__(parent)
        self._current = max(1, int(current))
        self._total = max(self._current, int(total))
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setAccessibleName(self.text())

    def text(self) -> str:
        return f"Passo {self._current} de {self._total}"

    def _font(self) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(scaled_px(12))
        font.setWeight(QFont.Weight.DemiBold)
        return font

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        text_width = QFontMetricsF(self._font()).horizontalAdvance(self.text())
        return QSize(int(text_width + 12 + self._total * 26), 24)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def paintEvent(self, _event) -> None:  # noqa: N802
        tokens = active_tokens()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        font = self._font()
        painter.setFont(font)
        painter.setPen(QColor(tokens["muted"]))
        text_width = QFontMetricsF(font).horizontalAdvance(self.text())
        painter.drawText(QRectF(0, 0, text_width + 2, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text())
        x = text_width + 12
        painter.setPen(Qt.NoPen)
        for step in range(1, self._total + 1):
            painter.setBrush(QColor(tokens["accent"] if step <= self._current else tokens["border"]))
            painter.drawRoundedRect(QRectF(x, self.height() / 2 - 2.5, 20, 5), 2.5, 2.5)
            x += 26
        painter.end()


class LeftAlignedDelegate(QStyledItemDelegate):
    """Delegate padrao das tabelas de dialogo: texto a esquerda e centrado na
    vertical, casando com o titulo de coluna alinhado a esquerda. Colunas com
    delegate proprio (selo, editor) nao passam por aqui."""

    def initStyleOption(self, option, index) -> None:  # noqa: N802 (Qt override)
        super().initStyleOption(option, index)
        option.displayAlignment = Qt.AlignLeft | Qt.AlignVCenter


def standardize_tables(root: QWidget) -> None:
    """Aplica a aparencia padrao a toda tabela dentro de `root`: sem grade,
    zebra, titulo de coluna a esquerda, cabecalho de 34 px e linha de pelo
    menos 40 px. Idempotente; nao mexe em modelo, colunas nem selecao. Tabela
    que ja tem delegate proprio para a tabela inteira continua com ele."""
    for table in root.findChildren(QTableView):
        if table.property("standardTable"):
            continue
        table.setProperty("standardTable", True)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        header = table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setHighlightSections(False)
        header.setMinimumHeight(TABLE_HEADER_HEIGHT)
        rows = table.verticalHeader()
        rows.setMinimumSectionSize(max(rows.minimumSectionSize(), 36))
        if rows.defaultSectionSize() < TABLE_ROW_HEIGHT:
            rows.setDefaultSectionSize(TABLE_ROW_HEIGHT)
        if type(table.itemDelegate()) is QStyledItemDelegate:
            table.setItemDelegate(LeftAlignedDelegate(table))


class _DialogShellController(QObject):
    """Padroniza as tabelas do dialogo quando ele e polido e a cada vez que
    aparece (pega tambem as tabelas criadas depois da primeira exibicao)."""

    def eventFilter(self, watched, event):  # noqa: N802 (Qt override)
        if event.type() in (QEvent.Polish, QEvent.Show):
            standardize_tables(watched)
        return False


def install_dialog_shell(dialog: QWidget, *, frameless: bool = True) -> None:
    """Casca padrao de tela sobreposta. Chamado por
    `style_dialog_from_parent()`; idempotente."""
    if getattr(dialog, "_dialog_shell_controller", None) is not None:
        # Chamado de novo quando o tema muda com a janela aberta.
        shell = getattr(dialog, "_window_shell", None)
        if shell is not None:
            shell.refresh()
        return
    controller = _DialogShellController(dialog)
    dialog.installEventFilter(controller)
    dialog._dialog_shell_controller = controller
    if frameless:
        from app.ui.components.window_shell import install_window_shell, window_shell_enabled

        if window_shell_enabled():
            install_window_shell(dialog)
            return
        from app.ui.components.frameless_dialog import apply_frameless_rounded_dialog

        apply_frameless_rounded_dialog(dialog)
