"""Prototipo ISOLADO da tela "Controle Geral" com o refinamento visual proposto.

Nao importa nada de `app/` e nao fala com a API: os dados sao ficticios e os
botoes de acao nao executam nada. Serve so para avaliar o visual antes de
aprovar a skill `qt-industrial-ui`. Os unicos arquivos do projeto que ele le
(somente leitura) sao os SVGs Lucide em `app/assets/icons/lucide/`.

Uso:
    python prototipos/controle_geral/preview.py                 # abre a janela
    python prototipos/controle_geral/preview.py --tema escuro
    python prototipos/controle_geral/preview.py --sem-animacao
    python prototipos/controle_geral/preview.py --contraste     # confere WCAG e sai
    python prototipos/controle_geral/preview.py --shot saida.png --estado lote
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import (
    QAbstractTableModel,
    QByteArray,
    QEasingCurve,
    QModelIndex,
    QObject,
    QPointF,
    QRectF,
    QSize,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QIcon, QLinearGradient, QPainter, QPalette, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QStackedLayout,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)

AQUI = Path(__file__).resolve().parent
LUCIDE = AQUI.parents[1] / "app" / "assets" / "icons" / "lucide"
FONTES = AQUI / "fonts"

# --------------------------------------------------------------------------
# Tokens. O azul e o mesmo da paleta "aurora" atual (#006fc9) e o escuro e o
# "grafite"; o que muda e a quantidade de niveis (superficie, borda de campo,
# anel de foco, texto sutil) e o fato de cada par ter contraste conferido.
# --------------------------------------------------------------------------
TEMAS = {
    "claro": {
        "chrome": "#CBD8EF",
        "bg": "#F5F7FB",
        "surface": "#FFFFFF",
        "surface_alt": "#E8F1FF",
        "surface_hover": "#DCE9FB",
        "zebra": "#EEF4FE",
        "header": "#DBEAFE",
        "selected": "#BFDBFE",
        "status_text": "#FFFFFF",
        "text": "#0F172A",
        "muted": "#475569",
        "subtle": "#5B6B82",
        "border": "#DCE3EE",
        "input_border": "#8391A6",
        "accent": "#006FC9",
        "accent_hover": "#005AA3",
        "accent_text": "#FFFFFF",
        "accent_soft": "#E3F0FB",
        "ring": "#006FC9",
        "danger": "#B91C1C",
        "warning": "#A2500A",
        "success": "#047857",
    },
    "escuro": {
        "chrome": "#0A1020",
        "bg": "#0F172A",
        "surface": "#172033",
        "surface_alt": "#22304A",
        "surface_hover": "#2A3B59",
        "zebra": "#1C2740",
        "header": "#24324A",
        "selected": "#0E5E78",
        "status_text": "#0F172A",
        "text": "#F8FAFC",
        "muted": "#CBD5E1",
        "subtle": "#9FB0C6",
        "border": "#2C3B56",
        "input_border": "#6B7C95",
        "accent": "#38BDF8",
        "accent_hover": "#7DD3FC",
        "accent_text": "#0F172A",
        "accent_soft": "#17364F",
        "ring": "#38BDF8",
        "danger": "#FB7185",
        "warning": "#FACC15",
        "success": "#34D399",
    },
}

# Mesmas cores de categoria de `STATUS_BADGE_COLORS` em app/ui/styles.py; so o
# verde "done" do claro escureceu (#16A34A -> #15803D) para o texto branco do
# selo solido passar de 4.5:1.
STATUS = {
    "claro": {
        "neutral": "#64748B",
        "waiting": "#2563EB",
        "done": "#15803D",
        "final_done": "#0F766E",
        "danger": "#DC2626",
        "location_production": "#047857",
        "location_galvanization": "#7C3AED",
        "location_expedition": "#C2410C",
    },
    "escuro": {
        "neutral": "#CBD5E1",
        "waiting": "#60A5FA",
        "done": "#4ADE80",
        "final_done": "#2DD4BF",
        "danger": "#FB7185",
        "location_production": "#34D399",
        "location_galvanization": "#A78BFA",
        "location_expedition": "#FB923C",
    },
}

ICONE_STATUS = {
    "neutral": "circle-dashed",
    "waiting": "clock",
    "done": "circle-check",
    "final_done": "check-check",
    "danger": "circle-x",
    "location_production": "factory",
    "location_galvanization": "layers",
    "location_expedition": "truck",
}

RAIO_CAMPO = 10
RAIO_CARTAO = 14
ALTURA_CONTROLE = 34
ALTURA_LINHA = 40

ANIMAR = True
FAMILIA = "Segoe UI"

CURVA = QEasingCurve(QEasingCurve.BezierSpline)
CURVA.addCubicBezierSegment(QPointF(0.23, 1.0), QPointF(0.32, 1.0), QPointF(1.0, 1.0))


class Tema(QObject):
    mudou = Signal()

    def __init__(self):
        super().__init__()
        self.nome = "claro"

    @property
    def t(self) -> dict:
        return TEMAS[self.nome]

    def cor(self, chave: str, alfa: float | None = None) -> QColor:
        cor = QColor(self.t[chave])
        if alfa is not None:
            cor.setAlphaF(alfa)
        return cor

    def status(self, categoria: str) -> QColor:
        return QColor(STATUS[self.nome].get(categoria, STATUS[self.nome]["neutral"]))

    def definir(self, nome: str) -> None:
        self.nome = nome
        self.mudou.emit()


TEMA = Tema()


def mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        round(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


def fonte(px: int, peso: int = 400, tabular: bool = False) -> QFont:
    f = QFont(FAMILIA)
    f.setPixelSize(px)
    f.setWeight(QFont.Weight(peso))
    if tabular:
        try:
            f.setFeature(QFont.Tag("tnum"), 1)
        except (AttributeError, TypeError):
            pass
    return f


def animar(widget: QWidget, atributo: str, fim: float, ms: int) -> None:
    anims = widget.__dict__.setdefault("_anims", {})
    anim = anims.get(atributo)
    if anim is None:
        anim = QVariantAnimation(widget)
        anim.setEasingCurve(CURVA)

        def aplica(valor, a=atributo):
            setattr(widget, a, valor)
            widget.update()

        anim.valueChanged.connect(aplica)
        anims[atributo] = anim
    anim.stop()
    if not ANIMAR or ms <= 0:
        setattr(widget, atributo, float(fim))
        widget.update()
        return
    anim.setDuration(ms)
    anim.setStartValue(float(getattr(widget, atributo)))
    anim.setEndValue(float(fim))
    anim.start()


def aparecer(widget: QWidget, ms: int = 220) -> None:
    if not ANIMAR:
        return
    efeito = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(efeito)
    anim = QVariantAnimation(widget)
    anim.setDuration(ms)
    anim.setEasingCurve(CURVA)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.valueChanged.connect(efeito.setOpacity)
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    anim.start()


_SVG_CACHE: dict[str, str] = {}


def _svg(nome: str) -> str:
    if nome not in _SVG_CACHE:
        arquivo = LUCIDE / f"{nome}.svg"
        _SVG_CACHE[nome] = arquivo.read_text(encoding="utf-8") if arquivo.exists() else ""
    return _SVG_CACHE[nome]


def pintar_icone(p: QPainter, nome: str, rect: QRectF, cor: QColor) -> None:
    texto = _svg(nome)
    if not texto:
        return
    QSvgRenderer(QByteArray(texto.replace("currentColor", cor.name()).encode("utf-8"))).render(p, rect)


def icone(nome: str, cor: QColor, tamanho: int = 16) -> QIcon:
    pix = QPixmap(tamanho * 2, tamanho * 2)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    pintar_icone(p, nome, QRectF(0, 0, tamanho * 2, tamanho * 2), cor)
    p.end()
    pix.setDevicePixelRatio(2)
    return QIcon(pix)


def foco_por_teclado(evento) -> bool:
    return evento.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason)


# --------------------------------------------------------------------------
# Componentes
# --------------------------------------------------------------------------
class Botao(QAbstractButton):
    """primario (azul cheio, um por tela), secundario (azul claro) ou fantasma (so texto).

    Nos dois ultimos o icone fica na cor de destaque, como nos botoes atuais.
    """

    def __init__(self, texto: str, icone_nome: str | None = None, variante: str = "secundario", parent=None):
        super().__init__(parent)
        self.setText(texto)
        self._icone = icone_nome
        self._variante = variante
        self._h = 0.0
        self._p = 0.0
        self._anel = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedHeight(ALTURA_CONTROLE)
        TEMA.mudou.connect(self.update)

    def sizeHint(self) -> QSize:
        largura = QFontMetrics(fonte(13, 600)).horizontalAdvance(self.text()) + 28
        if self._icone:
            largura += 22 if self.text() else 6
        return QSize(largura, ALTURA_CONTROLE)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def enterEvent(self, e):
        animar(self, "_h", 1.0, 140)
        super().enterEvent(e)

    def leaveEvent(self, e):
        animar(self, "_h", 0.0, 180)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        animar(self, "_p", 1.0, 80)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        animar(self, "_p", 0.0, 180)
        super().mouseReleaseEvent(e)

    def focusInEvent(self, e):
        self._anel = foco_por_teclado(e)
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self._anel = False
        super().focusOutEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.45)
        centro = QRectF(self.rect()).center()
        escala = 1.0 - 0.03 * self._p
        p.translate(centro)
        p.scale(escala, escala)
        p.translate(-centro)
        r = QRectF(self.rect()).adjusted(2.5, 2.5, -2.5, -2.5)
        h = self._h if self.isEnabled() else 0.0
        if self._variante == "primario":
            fundo = mix(TEMA.cor("accent"), TEMA.cor("accent_hover"), h)
            texto = cor_icone = TEMA.cor("accent_text")
        elif self._variante == "secundario":
            fundo = mix(TEMA.cor("surface_alt"), TEMA.cor("surface_hover"), h)
            texto = TEMA.cor("text")
            cor_icone = TEMA.cor("accent")
        else:
            fundo = TEMA.cor("surface_alt", h)
            texto = mix(TEMA.cor("muted"), TEMA.cor("text"), h)
            cor_icone = TEMA.cor("accent")
        p.setPen(Qt.NoPen)
        p.setBrush(fundo)
        p.drawRoundedRect(r, RAIO_CAMPO, RAIO_CAMPO)
        if self._anel:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(TEMA.cor("ring"), 2))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), RAIO_CAMPO + 2, RAIO_CAMPO + 2)

        f = fonte(13, 600)
        fm = QFontMetrics(f)
        largura_texto = fm.horizontalAdvance(self.text())
        total = largura_texto + (22 if self._icone and self.text() else 16 if self._icone else 0)
        x = r.center().x() - total / 2
        if self._icone:
            pintar_icone(p, self._icone, QRectF(x, r.center().y() - 8, 16, 16), cor_icone)
            x += 22
        p.setFont(f)
        p.setPen(texto)
        p.drawText(QRectF(x, r.top(), largura_texto + 2, r.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text())


class Segmentado(QWidget):
    """Filtro de status com contagem; o marcador desliza ate a opcao escolhida."""

    mudou = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._opcoes: list[tuple[str, str, int]] = []
        self._atual = 0
        self._x = 0.0
        self._w = 0.0
        self._hover = -1
        self._anel = False
        self.setFixedHeight(ALTURA_CONTROLE)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        TEMA.mudou.connect(self.update)

    def definir_opcoes(self, opcoes: list[tuple[str, str, int]]) -> None:
        self._opcoes = opcoes
        self.updateGeometry()
        x, w = self._faixa(self._atual)
        self._x, self._w = x, w
        self.update()

    def chave(self) -> str:
        return self._opcoes[self._atual][0] if self._opcoes else ""

    def selecionar(self, indice: int, emitir: bool = True) -> None:
        if not 0 <= indice < len(self._opcoes) or indice == self._atual:
            return
        self._atual = indice
        x, w = self._faixa(indice)
        animar(self, "_x", x, 240)
        animar(self, "_w", w, 240)
        if emitir:
            self.mudou.emit(self.chave())

    def _largura(self, indice: int) -> float:
        _chave, rotulo, total = self._opcoes[indice]
        return (
            QFontMetrics(fonte(13, 600)).horizontalAdvance(rotulo)
            + QFontMetrics(fonte(11, 600, True)).horizontalAdvance(str(total))
            + 12 + 6 + 14 + 12
        )

    def _faixa(self, indice: int) -> tuple[float, float]:
        x = 3.0
        for i in range(indice):
            x += self._largura(i)
        return x, (self._largura(indice) if self._opcoes else 0.0)

    def sizeHint(self) -> QSize:
        return QSize(int(sum(self._largura(i) for i in range(len(self._opcoes))) + 6), ALTURA_CONTROLE)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def _indice_em(self, x: float) -> int:
        for i in range(len(self._opcoes)):
            inicio, largura = self._faixa(i)
            if inicio <= x < inicio + largura:
                return i
        return -1

    def mouseMoveEvent(self, e):
        indice = self._indice_em(e.position().x())
        if indice != self._hover:
            self._hover = indice
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        indice = self._indice_em(e.position().x())
        if indice >= 0:
            self.selecionar(indice)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Right:
            self.selecionar(self._atual + 1)
        elif e.key() == Qt.Key_Left:
            self.selecionar(self._atual - 1)
        else:
            super().keyPressEvent(e)

    def focusInEvent(self, e):
        self._anel = foco_por_teclado(e)
        self.update()

    def focusOutEvent(self, e):
        self._anel = False
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(TEMA.cor("ring"), 2) if self._anel else Qt.NoPen)
        p.setBrush(TEMA.cor("surface_alt"))
        p.drawRoundedRect(r.adjusted(1, 1, -1, -1) if self._anel else r, RAIO_CAMPO, RAIO_CAMPO)
        p.setPen(QPen(TEMA.cor("border"), 1))
        p.setBrush(TEMA.cor("surface"))
        p.drawRoundedRect(QRectF(self._x, 3.5, self._w, self.height() - 7), RAIO_CAMPO - 2, RAIO_CAMPO - 2)
        for i, (_chave, rotulo, total) in enumerate(self._opcoes):
            x, w = self._faixa(i)
            ativo = i == self._atual
            cor = TEMA.cor("text") if ativo or i == self._hover else TEMA.cor("muted")
            f = fonte(13, 600 if ativo else 500)
            p.setFont(f)
            p.setPen(cor)
            largura_rotulo = QFontMetrics(fonte(13, 600)).horizontalAdvance(rotulo)
            p.drawText(QRectF(x + 12, 0, largura_rotulo + 2, self.height()), Qt.AlignVCenter | Qt.AlignLeft, rotulo)
            fc = fonte(11, 600, True)
            largura_total = QFontMetrics(fc).horizontalAdvance(str(total)) + 12
            pilula = QRectF(x + 12 + largura_rotulo + 6, self.height() / 2 - 9, largura_total, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(TEMA.cor("accent_soft") if ativo else TEMA.cor("border"))
            p.drawRoundedRect(pilula, 9, 9)
            p.setFont(fc)
            p.setPen(TEMA.cor("text"))
            p.drawText(pilula, Qt.AlignCenter, str(total))


class Seletor(QComboBox):
    """QComboBox com a mesma moldura dos campos (borda de campo + anel de foco)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(ALTURA_CONTROLE)
        self.setMinimumWidth(176)
        self.setCursor(Qt.PointingHandCursor)
        TEMA.mudou.connect(self.update)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        foco = self.hasFocus()
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1) if foco else QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(TEMA.cor("ring"), 2) if foco else QPen(TEMA.cor("input_border"), 1))
        p.setBrush(TEMA.cor("surface"))
        p.drawRoundedRect(r, RAIO_CAMPO, RAIO_CAMPO)
        p.setFont(fonte(13, 500))
        p.setPen(TEMA.cor("text"))
        p.drawText(QRectF(12, 0, self.width() - 40, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.currentText())
        p.translate(self.width() - 18, self.height() / 2)
        p.rotate(90)
        pintar_icone(p, "chevron-right", QRectF(-7, -7, 14, 14), TEMA.cor("muted"))


class ItemNav(QAbstractButton):
    def __init__(self, rotulo: str, icone_nome: str, ativo: bool = False, contador: int = 0, parent=None):
        super().__init__(parent)
        self.setText(rotulo)
        self._icone = icone_nome
        self._ativo = ativo
        self._contador = contador
        self._h = 0.0
        self.setFixedHeight(40)
        self.setCursor(Qt.PointingHandCursor)
        TEMA.mudou.connect(self.update)

    def enterEvent(self, e):
        animar(self, "_h", 1.0, 140)

    def leaveEvent(self, e):
        animar(self, "_h", 0.0, 180)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0, 1, 0, -1)
        p.setPen(Qt.NoPen)
        # Item ativo = pilula azul cheia, como na barra lateral atual.
        if self._ativo:
            p.setBrush(TEMA.cor("accent"))
            p.drawRoundedRect(r, RAIO_CAMPO, RAIO_CAMPO)
        elif self._h > 0:
            p.setBrush(TEMA.cor("surface", 0.6 * self._h))
            p.drawRoundedRect(r, RAIO_CAMPO, RAIO_CAMPO)
        cor = TEMA.cor("accent_text") if self._ativo else TEMA.cor("text")
        pintar_icone(p, self._icone, QRectF(14, r.center().y() - 10, 20, 20), cor if self._ativo else TEMA.cor("accent"))
        p.setFont(fonte(13, 700 if self._ativo else 600))
        p.setPen(cor)
        largura = self.width() - (82 if self._contador else 50)
        p.drawText(QRectF(44, 0, largura, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text())
        if self._contador:
            fc = fonte(11, 700, True)
            largura = max(20, QFontMetrics(fc).horizontalAdvance(str(self._contador)) + 12)
            pilula = QRectF(self.width() - largura - 10, self.height() / 2 - 9, largura, 18)
            p.setPen(Qt.NoPen)
            p.setBrush(TEMA.cor("accent_text") if self._ativo else TEMA.cor("accent"))
            p.drawRoundedRect(pilula, 9, 9)
            p.setFont(fc)
            p.setPen(TEMA.cor("accent") if self._ativo else TEMA.cor("accent_text"))
            p.drawText(pilula, Qt.AlignCenter, str(self._contador))


class BotaoFlutuante(QAbstractButton):
    """Botao redondo de chat no canto, como o atual, com contador pintado."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._h = 0.0
        self._nao_lidas = 5
        self.setFixedSize(64, 64)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Abrir central de chat")
        TEMA.mudou.connect(self.update)

    def enterEvent(self, e):
        animar(self, "_h", 1.0, 160)

    def leaveEvent(self, e):
        animar(self, "_h", 0.0, 200)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        centro = QRectF(self.rect()).center()
        raio = 26 + 3 * self._h
        p.setPen(Qt.NoPen)
        p.setBrush(mix(TEMA.cor("accent"), TEMA.cor("accent_hover"), self._h))
        p.drawEllipse(centro, raio, raio)
        pintar_icone(p, "message-circle", QRectF(centro.x() - 11, centro.y() - 11, 22, 22), TEMA.cor("accent_text"))
        if self._nao_lidas:
            bolha = QRectF(self.width() - 24, 2, 20, 20)
            p.setPen(QPen(TEMA.cor("bg"), 2))
            p.setBrush(TEMA.cor("danger"))
            p.drawEllipse(bolha)
            p.setFont(fonte(11, 700, True))
            p.setPen(TEMA.cor("surface") if TEMA.nome == "claro" else TEMA.cor("bg"))
            p.drawText(bolha, Qt.AlignCenter, str(self._nao_lidas))


class Esqueleto(QWidget):
    """Estado de carregamento: linhas-fantasma com brilho, no lugar de "Carregando..."."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fase = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(1300)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._tick)

    def _tick(self, valor):
        self._fase = valor
        self.update()

    def showEvent(self, e):
        if ANIMAR:
            self._anim.start()

    def hideEvent(self, e):
        self._anim.stop()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        base = TEMA.cor("surface_alt")
        brilho = mix(base, TEMA.cor("surface"), 0.75)
        grad = QLinearGradient(self.width() * (self._fase * 2 - 1), 0, self.width() * (self._fase * 2 - 0.4), 0)
        grad.setColorAt(0.0, base)
        grad.setColorAt(0.5, brilho if ANIMAR else base)
        grad.setColorAt(1.0, base)
        p.setPen(Qt.NoPen)
        fracoes = [(16, 18), (52, 76), (180, 0.26), (0.56, 150), (0.72, 84), (0.83, 0.12)]
        y = 34
        linha = 0
        while y + ALTURA_LINHA <= self.height():
            p.setBrush(grad)
            for inicio, largura in fracoes:
                x = inicio if inicio > 1 else self.width() * inicio
                w = largura if largura > 1 else self.width() * largura
                w *= 0.7 + 0.3 * ((linha * 7 + int(x)) % 5) / 4
                p.drawRoundedRect(QRectF(x, y + 13, w, 14), 5, 5)
            p.setBrush(TEMA.cor("border"))
            p.drawRect(QRectF(0, y + ALTURA_LINHA - 1, self.width(), 1))
            y += ALTURA_LINHA
            linha += 1


class EstadoVazio(QWidget):
    limpar = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        coluna = QVBoxLayout(self)
        coluna.setAlignment(Qt.AlignCenter)
        coluna.setSpacing(6)
        self._icone = QLabel()
        self._icone.setFixedSize(56, 56)
        self._icone.setAlignment(Qt.AlignCenter)
        self._icone.setObjectName("VazioIcone")
        titulo = QLabel("Nenhum resultado para os filtros aplicados")
        titulo.setObjectName("VazioTitulo")
        texto = QLabel("Ajuste a busca, o status ou o prazo para ampliar a consulta.")
        texto.setObjectName("Sub")
        botao = Botao("Limpar filtros", "x", "secundario")
        botao.clicked.connect(self.limpar)
        coluna.addWidget(self._icone, 0, Qt.AlignHCenter)
        coluna.addSpacing(6)
        coluna.addWidget(titulo, 0, Qt.AlignHCenter)
        coluna.addWidget(texto, 0, Qt.AlignHCenter)
        coluna.addSpacing(10)
        coluna.addWidget(botao, 0, Qt.AlignHCenter)
        TEMA.mudou.connect(self._tema)
        self._tema()

    def _tema(self):
        self._icone.setPixmap(icone("search", TEMA.cor("muted"), 24).pixmap(24, 24))


# --------------------------------------------------------------------------
# Tabela
# --------------------------------------------------------------------------
COLUNAS = [
    ("icone", ""),
    ("proposta", "Proposta"),
    ("chat", ""),
    ("cliente", "Cliente"),
    ("etapa", "Etapa/Status"),
    ("prazo", "Prazo"),
    ("obra", "Obra/Site"),
]
PAPEL_LINHA = Qt.UserRole
PAPEL_CHAVE = Qt.UserRole + 1
PAPEL_ORDEM = Qt.UserRole + 2
HOJE = date.today()


def linhas_ficticias() -> list[dict]:
    rnd = random.Random(7)
    clientes = [
        "Torres Norte Telecom", "Rede Sul Energia", "Vale Verde Transmissão", "Conecta Infra", "Atlas Estruturas",
        "Horizonte Telecom", "Usina Boa Vista", "Linha Viva Engenharia", "Serra Azul Energia", "Ponto Alto Torres",
    ]
    obras = [
        "SP-CAMP-014", "MG-UBER-203", "PR-LOND-077", "BA-FEIR-118", "GO-ANAP-052", "RS-PELO-031",
        "SC-JOIN-096", "PE-CARU-145", "MT-SINO-009", "CE-SOBR-061",
    ]
    etapas = [
        ("NAO_LIBERADO", "Não liberado", "neutral", 14),
        ("LIBERADO_PRODUCAO", "Liberado para produção", "waiting", 9),
        ("LIBERADO_PRODUCAO", "Em produção", "location_production", 13),
        ("LIBERADO_PRODUCAO", "Em galvanização", "location_galvanization", 8),
        ("LIBERADO_PRODUCAO", "Em expedição", "location_expedition", 7),
        ("LIBERADO_PRODUCAO", "Entregue", "final_done", 6),
        ("CANCELADA", "Cancelada", "danger", 3),
    ]
    pesos = [e[3] for e in etapas]
    linhas = []
    for i in range(60):
        geral, rotulo, categoria, _peso = rnd.choices(etapas, weights=pesos)[0]
        prazo = HOJE + timedelta(days=rnd.randint(-12, 45))
        linhas.append(
            {
                "id": 1000 + i,
                "proposta": f"{10480 + i * 3}/{rnd.choice(['A', 'B', 'C'])}",
                "cliente": rnd.choice(clientes),
                "obra": rnd.choice(obras),
                "status_geral": geral,
                "etapa": rotulo,
                "categoria": categoria,
                "prazo": prazo,
                "nao_lidas": rnd.choice([0, 0, 0, 0, 1, 3]),
                "encerrada": categoria in ("final_done", "danger"),
            }
        )
    return linhas


def situacao_prazo(linha: dict) -> tuple[str, str]:
    """(texto relativo, token de cor) - vazio quando o prazo nao pede atencao."""
    if linha["encerrada"]:
        return "", ""
    dias = (linha["prazo"] - HOJE).days
    if dias < 0:
        return f"vencido há {-dias} d", "danger"
    if dias == 0:
        return "vence hoje", "warning"
    if dias <= 7:
        return f"em {dias} d", "warning"
    return "", ""


class Modelo(QAbstractTableModel):
    selecao_mudou = Signal()

    def __init__(self, linhas: list[dict]):
        super().__init__()
        self.linhas = linhas
        self.colunas = list(COLUNAS)
        self.lote = False
        self.marcadas: set[int] = set()

    def definir_lote(self, ativo: bool) -> None:
        self.beginResetModel()
        self.lote = ativo
        self.colunas = [("sel", ""), *COLUNAS] if ativo else list(COLUNAS)
        if not ativo:
            self.marcadas.clear()
        self.endResetModel()
        self.selecao_mudou.emit()

    def alternar(self, linha: dict) -> None:
        self.marcadas.symmetric_difference_update({linha["id"]})
        self.dataChanged.emit(self.index(0, 0), self.index(len(self.linhas) - 1, len(self.colunas) - 1))
        self.selecao_mudou.emit()

    def limpar_marcadas(self) -> None:
        self.marcadas.clear()
        self.dataChanged.emit(self.index(0, 0), self.index(len(self.linhas) - 1, len(self.colunas) - 1))
        self.selecao_mudou.emit()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.linhas)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.colunas)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        linha = self.linhas[index.row()]
        chave = self.colunas[index.column()][0]
        if role == PAPEL_LINHA:
            return linha
        if role == PAPEL_CHAVE:
            return chave
        if role == PAPEL_ORDEM:
            if chave == "prazo":
                return linha["prazo"].isoformat()
            if chave in ("icone", "etapa"):
                return linha["etapa"]
            return str(linha.get(chave, "")).lower()
        if role == Qt.DisplayRole:
            if chave == "prazo":
                return linha["prazo"].strftime("%d/%m/%Y")
            if chave in ("icone", "chat", "sel"):
                return ""
            return linha.get(chave, "")
        if role == Qt.ToolTipRole:
            if chave == "icone":
                return f"{linha['etapa']}\nAbrir ações da proposta"
            if chave == "chat":
                return f"{linha['nao_lidas']} mensagem(ns) não lida(s)" if linha["nao_lidas"] else "Abrir chat da proposta"
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.colunas[section][1]
        return None


class Filtro(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.busca = ""
        self.status = ""
        self.prazo = ""
        self.setSortRole(PAPEL_ORDEM)

    def aplicar(self, busca: str, status: str, prazo: str) -> None:
        self.busca, self.status, self.prazo = busca.strip().lower(), status, prazo
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        linha = self.sourceModel().linhas[source_row]
        if self.status and linha["status_geral"] != self.status:
            return False
        dias = (linha["prazo"] - HOJE).days
        if self.prazo == "VENCIDOS" and not (dias < 0 and not linha["encerrada"]):
            return False
        if self.prazo == "PROXIMOS_7_DIAS" and not (0 <= dias <= 7 and not linha["encerrada"]):
            return False
        if self.busca:
            alvo = f"{linha['proposta']} {linha['cliente']} {linha['obra']}".lower()
            return self.busca in alvo
        return True


class Delegate(QStyledItemDelegate):
    def sizeHint(self, option, index) -> QSize:
        return QSize(0, ALTURA_LINHA)

    def paint(self, p: QPainter, option, index: QModelIndex) -> None:
        tabela: Tabela = self.parent()
        linha = index.data(PAPEL_LINHA)
        chave = index.data(PAPEL_CHAVE)
        modelo: Modelo = tabela.model().sourceModel()
        marcada = modelo.lote and linha["id"] in modelo.marcadas
        selecionada = tabela.selectionModel().isRowSelected(index.row(), QModelIndex()) and not modelo.lote
        r = QRectF(option.rect)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        # Linhas zebradas em azul claro, como na tabela atual (sem linhas divisorias).
        if marcada or selecionada:
            p.fillRect(r, TEMA.cor("selected"))
        elif tabela.linha_hover == index.row():
            p.fillRect(r, TEMA.cor("surface_hover"))
        elif index.row() % 2:
            p.fillRect(r, TEMA.cor("zebra"))
        if (marcada or selecionada) and index.column() == 0:
            p.fillRect(QRectF(r.left(), r.top(), 4, r.height()), TEMA.cor("accent"))
        apagada = linha["encerrada"] and linha["categoria"] == "danger"
        cy = r.center().y()

        if chave == "sel":
            caixa = QRectF(r.center().x() - 8, cy - 8, 16, 16)
            if marcada:
                p.setBrush(TEMA.cor("accent"))
                p.drawRoundedRect(caixa, 4, 4)
                pintar_icone(p, "check", caixa.adjusted(2, 2, -2, -2), TEMA.cor("accent_text"))
            else:
                p.setBrush(TEMA.cor("surface"))
                p.setPen(QPen(TEMA.cor("input_border"), 1.5))
                p.drawRoundedRect(caixa, 4, 4)
        elif chave == "icone":
            p.setBrush(TEMA.cor("surface"))
            p.setPen(QPen(TEMA.cor("border"), 1))
            p.drawEllipse(QPointF(r.center().x() + 2, cy), 13, 13)
            pintar_icone(p, ICONE_STATUS[linha["categoria"]], QRectF(r.center().x() - 6, cy - 8, 16, 16), TEMA.status(linha["categoria"]))
        elif chave == "chat":
            nao_lidas = linha["nao_lidas"]
            cor = TEMA.cor("accent") if nao_lidas else TEMA.cor("subtle")
            pintar_icone(p, "message-circle", QRectF(r.center().x() - 9, cy - 8, 17, 17), cor)
            if nao_lidas:
                bolha = QRectF(r.center().x() + 1, cy - 13, 15, 15)
                p.setPen(QPen(TEMA.cor("surface"), 1.5))
                p.setBrush(TEMA.cor("accent"))
                p.drawEllipse(bolha)
                p.setFont(fonte(10, 700, True))
                p.setPen(TEMA.cor("accent_text"))
                p.drawText(bolha, Qt.AlignCenter, str(nao_lidas))
        elif chave == "etapa":
            # Selo solido de largura fixa, como o atual: as cores se alinham em coluna.
            f = fonte(12, 600)
            pilula = QRectF(r.left() + 8, cy - 11, r.width() - 24, 22)
            p.setBrush(TEMA.status(linha["categoria"]))
            p.drawRoundedRect(pilula, 11, 11)
            p.setFont(f)
            p.setPen(TEMA.cor("status_text"))
            rotulo = QFontMetrics(f).elidedText(linha["etapa"], Qt.ElideRight, int(pilula.width()) - 16)
            p.drawText(pilula, Qt.AlignCenter, rotulo)
        elif chave == "prazo":
            f = fonte(13, 400, True)
            texto = index.data(Qt.DisplayRole)
            p.setFont(f)
            p.setPen(TEMA.cor("subtle") if apagada else TEMA.cor("text"))
            p.drawText(r.adjusted(10, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, texto)
            relativo, token = situacao_prazo(linha)
            if relativo:
                x = r.left() + 10 + QFontMetrics(f).horizontalAdvance(texto) + 10
                if token == "danger":
                    pintar_icone(p, "triangle-alert", QRectF(x, cy - 7, 14, 14), TEMA.cor(token))
                    x += 18
                p.setFont(fonte(12, 600, True))
                p.setPen(TEMA.cor(token))
                p.drawText(QRectF(x, r.top(), r.right() - x, r.height()), Qt.AlignVCenter | Qt.AlignLeft, relativo)
        else:
            if chave == "proposta":
                f, cor = fonte(13, 600, True), TEMA.cor("text")
            elif chave == "obra":
                f, cor = fonte(13, 400, True), TEMA.cor("text")
            else:
                f, cor = fonte(13, 400), TEMA.cor("text")
            if apagada:
                cor = TEMA.cor("subtle")
            p.setFont(f)
            p.setPen(cor)
            area = r.adjusted(10, 0, -10, 0)
            p.drawText(area, Qt.AlignVCenter | Qt.AlignLeft, QFontMetrics(f).elidedText(str(index.data(Qt.DisplayRole)), Qt.ElideRight, int(area.width())))
        p.restore()


class Tabela(QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.linha_hover = -1
        self.setItemDelegate(Delegate(self))
        self.setShowGrid(False)
        self.setFrameShape(QFrame.NoFrame)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setSortingEnabled(True)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(ALTURA_LINHA)
        cabecalho = self.horizontalHeader()
        cabecalho.setFixedHeight(34)
        cabecalho.setHighlightSections(False)
        cabecalho.setDefaultAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        # Sem coluna de ordenacao inicial: mantem a ordem por prioridade de status.
        cabecalho.setSortIndicator(-1, Qt.AscendingOrder)
        TEMA.mudou.connect(self.viewport().update)

    def ajustar_colunas(self) -> None:
        cabecalho = self.horizontalHeader()
        larguras = {"sel": 40, "icone": 44, "proposta": 116, "chat": 44, "etapa": 220, "prazo": 216}
        modelo: Modelo = self.model().sourceModel()
        for coluna, (chave, _rotulo) in enumerate(modelo.colunas):
            if chave in larguras:
                cabecalho.setSectionResizeMode(coluna, QHeaderView.Fixed)
                self.setColumnWidth(coluna, larguras[chave])
            else:
                cabecalho.setSectionResizeMode(coluna, QHeaderView.Stretch)

    def mouseMoveEvent(self, e):
        linha = self.indexAt(e.position().toPoint()).row()
        if linha != self.linha_hover:
            self.linha_hover = linha
            self.viewport().update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self.linha_hover = -1
        self.viewport().update()
        super().leaveEvent(e)


# --------------------------------------------------------------------------
# Pagina
# --------------------------------------------------------------------------
def folha_de_estilo() -> str:
    t = TEMA.t
    return f"""
    * {{ font-family: "{FAMILIA}"; font-size: 13px; color: {t['text']}; }}
    QWidget#Raiz {{ background: {t['chrome']}; }}
    QFrame#Lateral {{ background: {t['chrome']}; border: 0; }}
    QFrame#Conteudo {{ background: {t['bg']}; border: 0; border-top-left-radius: {RAIO_CARTAO}px; }}
    QFrame#Faixa {{ background: {t['surface']}; border: 0; border-bottom: 1px solid {t['border']};
        border-top-left-radius: {RAIO_CARTAO}px; }}
    QFrame#Rodape {{ background: transparent; border: 0; }}
    QFrame#Marca {{ background: {t['accent']}; border: 0; border-top-left-radius: {RAIO_CARTAO}px; }}
    QLabel {{ background: transparent; }}
    QLabel#Logo {{ font-size: 16px; font-weight: 700; }}
    QLabel#Titulo {{ color: {t['accent']}; font-size: 18px; font-weight: 700; }}
    QLabel#Sub {{ color: {t['muted']}; font-size: 12px; }}
    QLabel#Rotulo {{ font-size: 12px; font-weight: 700; }}
    QLabel#Grupo {{ color: {t['muted']}; font-size: 11px; font-weight: 700; padding-left: 14px; }}
    QLabel#Legenda {{ color: {t['muted']}; font-size: 12px; }}
    QLabel#Selecao {{ font-size: 14px; font-weight: 600; }}
    QLabel#VazioTitulo {{ font-size: 15px; font-weight: 600; }}
    QLabel#VazioIcone {{ background: {t['surface_alt']}; border-radius: 28px; }}
    QLineEdit {{
        background: {t['surface']}; border: 1px solid {t['input_border']}; border-radius: {RAIO_CAMPO}px;
        padding: 0 10px; min-height: {ALTURA_CONTROLE - 2}px; max-height: {ALTURA_CONTROLE - 2}px;
        selection-background-color: {t['accent']}; selection-color: {t['accent_text']};
    }}
    QLineEdit:focus {{ border: 2px solid {t['ring']}; padding: 0 9px;
        min-height: {ALTURA_CONTROLE - 4}px; max-height: {ALTURA_CONTROLE - 4}px; }}
    QComboBox QAbstractItemView {{
        background: {t['surface']}; border: 1px solid {t['border']}; outline: 0; padding: 4px;
        selection-background-color: {t['accent_soft']}; selection-color: {t['text']};
    }}
    QTableView {{ background: transparent; border: 0; outline: 0; }}
    QHeaderView {{ background: transparent; border: 0; }}
    QHeaderView::section {{
        background: {t['header']}; color: {t['text']}; font-size: 13px; font-weight: 700;
        border: 0; padding: 0 10px;
    }}
    QHeaderView::section:hover {{ color: {t['accent']}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 3px; min-height: 32px; }}
    QScrollBar::handle:vertical:hover {{ background: {t['input_border']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QToolTip {{ background: {t['text']}; color: {t['bg']}; border: 0; padding: 5px 8px; }}
    """


class Lateral(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Lateral")
        self.setFixedWidth(236)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(12, 18, 12, 14)
        coluna.setSpacing(2)
        logo = QLabel("Industel")
        logo.setObjectName("Logo")
        logo.setContentsMargins(14, 0, 0, 0)
        produto = QLabel("Controle de Produção")
        produto.setObjectName("Legenda")
        produto.setContentsMargins(14, 0, 0, 0)
        coluna.addWidget(logo)
        coluna.addWidget(produto)
        grupos = [
            ("PAINÉIS", [("Painel geral", "layout-dashboard", 0), ("Dashboard Executivo", "chart-column", 0)]),
            (
                "OPERAÇÃO",
                [
                    ("Controle Geral", "clipboard-check", 0),
                    ("Produção", "factory", 4),
                    ("Galvanização", "layers", 0),
                    ("Expedição", "truck", 2),
                    ("Fiscal", "receipt-text", 0),
                    ("Parciais", "package-open", 0),
                    ("Almoxarifado", "warehouse", 0),
                ],
            ),
            ("ANÁLISE", [("Relatórios Operacionais", "file-text", 0), ("Histórico", "file-clock", 0)]),
        ]
        for titulo, itens in grupos:
            coluna.addSpacing(14)
            rotulo = QLabel(titulo)
            rotulo.setObjectName("Grupo")
            coluna.addWidget(rotulo)
            coluna.addSpacing(2)
            for nome, icone_nome, contador in itens:
                coluna.addWidget(ItemNav(nome, icone_nome, ativo=nome == "Controle Geral", contador=contador))
        coluna.addStretch(1)
        self.tema_botao = Botao("Tema escuro", "moon", "fantasma")
        coluna.addWidget(self.tema_botao)


class Pagina(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Raiz")
        self.setWindowTitle("Protótipo - Controle Geral (dados fictícios)")
        self.modelo = Modelo(linhas_ficticias())
        self.filtro = Filtro(self)
        self.filtro.setSourceModel(self.modelo)

        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)
        self.lateral = Lateral()
        self.lateral.tema_botao.clicked.connect(self.alternar_tema)
        raiz.addWidget(self.lateral)

        # Mesma moldura da tela atual: fundo azulado em volta, conteudo com o
        # canto superior esquerdo arredondado, faixa de filtros com a barra
        # azul a esquerda e a tabela de ponta a ponta.
        moldura = QVBoxLayout()
        moldura.setContentsMargins(0, 10, 0, 0)
        raiz.addLayout(moldura, 1)
        painel = QFrame()
        painel.setObjectName("Conteudo")
        conteudo = QVBoxLayout(painel)
        conteudo.setContentsMargins(0, 0, 0, 0)
        conteudo.setSpacing(0)
        moldura.addWidget(painel)
        conteudo.addWidget(self._cabecalho())
        self._montar_tabela(conteudo)
        self.chat_flutuante = BotaoFlutuante(self)

        self.busca.textChanged.connect(self.filtrar)
        self.status.mudou.connect(self.filtrar)
        self.prazo.currentIndexChanged.connect(self.filtrar)
        self.modelo.selecao_mudou.connect(self._atualizar_lote)
        TEMA.mudou.connect(self._tema)
        self._tema()
        self._contagens()
        self.filtrar()

    # ---- montagem -------------------------------------------------------
    def _cabecalho(self) -> QFrame:
        cartao = QFrame()
        cartao.setObjectName("Faixa")
        faixa = QHBoxLayout(cartao)
        faixa.setContentsMargins(0, 0, 0, 0)
        faixa.setSpacing(0)
        marca = QFrame()
        marca.setObjectName("Marca")
        marca.setFixedWidth(8)
        faixa.addWidget(marca)
        coluna = QVBoxLayout()
        coluna.setContentsMargins(16, 12, 16, 12)
        coluna.setSpacing(10)
        faixa.addLayout(coluna, 1)

        topo = QHBoxLayout()
        topo.setSpacing(12)
        titulos = QVBoxLayout()
        titulos.setSpacing(1)
        titulo = QLabel("Controle Geral")
        titulo.setObjectName("Titulo")
        sub = QLabel("Visão geral das propostas e liberações.")
        sub.setObjectName("Sub")
        titulos.addWidget(titulo)
        titulos.addWidget(sub)
        topo.addLayout(titulos)
        topo.addStretch(1)

        # Uma unica acao primaria por tela; as demais sao secundarias.
        self.acoes = QWidget()
        linha_acoes = QHBoxLayout(self.acoes)
        linha_acoes.setContentsMargins(0, 0, 0, 0)
        linha_acoes.setSpacing(8)
        self.lote_botao = Botao("Ações em lote", "layers")
        self.lote_botao.clicked.connect(lambda: self.definir_lote(True))
        for botao in (Botao("Detalhes", "info"), Botao("Editar", "pencil"), Botao("Ações", "workflow"), self.lote_botao):
            linha_acoes.addWidget(botao)
        linha_acoes.addWidget(Botao("Novo processo", "plus", "primario"))

        self.barra_lote = QWidget()
        linha_lote = QHBoxLayout(self.barra_lote)
        linha_lote.setContentsMargins(0, 0, 0, 0)
        linha_lote.setSpacing(8)
        self.selecao_rotulo = QLabel("")
        self.selecao_rotulo.setObjectName("Selecao")
        self.ver_botao = Botao("Ver selecionadas", "list")
        self.limpar_selecao_botao = Botao("Limpar seleção", "x")
        self.limpar_selecao_botao.clicked.connect(self.modelo.limpar_marcadas)
        self.acoes_lote_botao = Botao("Ações", "workflow", "primario")
        cancelar = Botao("Cancelar", None, "fantasma")
        cancelar.clicked.connect(lambda: self.definir_lote(False))
        linha_lote.addWidget(self.selecao_rotulo)
        linha_lote.addSpacing(8)
        for botao in (self.ver_botao, self.limpar_selecao_botao, self.acoes_lote_botao, cancelar):
            linha_lote.addWidget(botao)
        self.barra_lote.setVisible(False)
        topo.addWidget(self.acoes)
        topo.addWidget(self.barra_lote)
        coluna.addLayout(topo)

        filtros = QHBoxLayout()
        filtros.setSpacing(10)
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Pesquisar proposta, cliente, site ou lote")
        self.busca.setClearButtonEnabled(True)
        self.busca.setAccessibleName("Busca geral")
        self._acao_busca = self.busca.addAction(QIcon(), QLineEdit.LeadingPosition)
        self.status = Segmentado()
        self.status.setAccessibleName("Status")
        self.prazo = Seletor()
        self.prazo.setAccessibleName("Prazo")
        self.prazo.addItem("Todos os prazos", "")
        self.prazo.addItem("Vencidos", "VENCIDOS")
        self.prazo.addItem("Próximos 7 dias", "PROXIMOS_7_DIAS")
        aplicar = Botao("Aplicar", "refresh-cw")
        aplicar.clicked.connect(self.recarregar)
        limpar = Botao("Limpar", "x", "fantasma")
        limpar.clicked.connect(self.limpar)
        # Sem rotulos ao lado: em 1360 px de largura eles espremiam a busca. O
        # placeholder, as opcoes do status e "Todos os prazos" ja se explicam.
        self.busca.setMinimumWidth(240)
        filtros.addWidget(self.busca, 1)
        filtros.addWidget(self.status)
        filtros.addWidget(self.prazo)
        filtros.addWidget(aplicar)
        filtros.addWidget(limpar)
        coluna.addLayout(filtros)
        return cartao

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.chat_flutuante.move(self.width() - 84, self.height() - 118)
        self.chat_flutuante.raise_()

    def _montar_tabela(self, coluna: QVBoxLayout) -> None:
        self.tabela = Tabela()
        self.tabela.setModel(self.filtro)
        self.tabela.ajustar_colunas()
        self.tabela.clicked.connect(self._clique)
        self.esqueleto = Esqueleto()
        self.vazio = EstadoVazio()
        self.vazio.limpar.connect(self.limpar)
        miolo = QWidget()
        self.pilha = QStackedLayout(miolo)
        self.pilha.setContentsMargins(0, 0, 0, 0)
        for widget in (self.tabela, self.esqueleto, self.vazio):
            self.pilha.addWidget(widget)
        coluna.addWidget(miolo, 1)

        rodape = QFrame()
        rodape.setObjectName("Rodape")
        linha = QHBoxLayout(rodape)
        linha.setContentsMargins(16, 6, 16, 8)
        linha.setSpacing(12)
        self.total = QLabel("")
        self.total.setObjectName("Legenda")
        anterior = Botao("Anterior", "chevron-left", "fantasma")
        proxima = Botao("Próxima", "chevron-right", "fantasma")
        anterior.setEnabled(False)
        proxima.setEnabled(False)
        linha.addStretch(1)
        linha.addWidget(anterior)
        linha.addWidget(self.total)
        linha.addWidget(proxima)
        linha.addStretch(1)
        coluna.addWidget(rodape)

    # ---- comportamento ---------------------------------------------------
    def _tema(self) -> None:
        self.setStyleSheet(folha_de_estilo())
        paleta = self.busca.palette()
        paleta.setColor(QPalette.PlaceholderText, TEMA.cor("subtle"))
        self.busca.setPalette(paleta)
        self._acao_busca.setIcon(icone("search", TEMA.cor("muted")))
        escuro = TEMA.nome == "escuro"
        self.lateral.tema_botao.setText("Tema claro" if escuro else "Tema escuro")
        self.lateral.tema_botao._icone = "sun" if escuro else "moon"

    def alternar_tema(self) -> None:
        TEMA.definir("claro" if TEMA.nome == "escuro" else "escuro")

    def _contagens(self) -> None:
        linhas = self.modelo.linhas
        conta = lambda chave: sum(1 for linha in linhas if linha["status_geral"] == chave)  # noqa: E731
        self.status.definir_opcoes(
            [
                ("", "Todos", len(linhas)),
                ("NAO_LIBERADO", "Não liberado", conta("NAO_LIBERADO")),
                ("LIBERADO_PRODUCAO", "Liberado", conta("LIBERADO_PRODUCAO")),
                ("CANCELADA", "Cancelada", conta("CANCELADA")),
            ]
        )

    def filtrar(self, *_args) -> None:
        self.filtro.aplicar(self.busca.text(), self.status.chave(), self.prazo.currentData() or "")
        visiveis = self.filtro.rowCount()
        self.total.setText(f"Página 1 de 1  |  {visiveis} de {len(self.modelo.linhas)} propostas")
        if self.pilha.currentWidget() is not self.esqueleto:
            self.pilha.setCurrentWidget(self.tabela if visiveis else self.vazio)

    def limpar(self) -> None:
        self.busca.clear()
        self.status.selecionar(0, emitir=False)
        self.prazo.setCurrentIndex(0)
        self.filtrar()

    def recarregar(self) -> None:
        self.pilha.setCurrentWidget(self.esqueleto)
        QTimer.singleShot(700 if ANIMAR else 0, self._carregado)

    def _carregado(self) -> None:
        self.pilha.setCurrentWidget(self.tabela if self.filtro.rowCount() else self.vazio)
        aparecer(self.pilha.currentWidget())

    def definir_lote(self, ativo: bool) -> None:
        self.modelo.definir_lote(ativo)
        self.tabela.ajustar_colunas()
        self.acoes.setVisible(not ativo)
        self.barra_lote.setVisible(ativo)
        aparecer(self.barra_lote if ativo else self.acoes, 180)

    def _atualizar_lote(self) -> None:
        total = len(self.modelo.marcadas)
        self.selecao_rotulo.setText("1 proposta selecionada" if total == 1 else f"{total} propostas selecionadas")
        for botao in (self.ver_botao, self.limpar_selecao_botao, self.acoes_lote_botao):
            botao.setEnabled(total > 0)

    def _clique(self, index: QModelIndex) -> None:
        if self.modelo.lote:
            self.modelo.alternar(index.data(PAPEL_LINHA))


# --------------------------------------------------------------------------
# Verificacao de contraste (WCAG 2.x)
# --------------------------------------------------------------------------
def _luminancia(hexa: str) -> float:
    cor = QColor(hexa)
    canais = []
    for canal in (cor.redF(), cor.greenF(), cor.blueF()):
        canais.append(canal / 12.92 if canal <= 0.03928 else ((canal + 0.055) / 1.055) ** 2.4)
    return 0.2126 * canais[0] + 0.7152 * canais[1] + 0.0722 * canais[2]


def contraste(a: str, b: str) -> float:
    la, lb = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _sobre(frente: str, fundo: str, alfa: float) -> str:
    return mix(QColor(fundo), QColor(frente), alfa).name()


def conferir_contraste() -> int:
    falhas = 0
    for nome, t in TEMAS.items():
        pares = [
            ("texto / fundo", t["text"], t["bg"], 4.5),
            ("texto / superficie", t["text"], t["surface"], 4.5),
            ("texto / linha selecionada", t["text"], t["selected"], 4.5),
            ("texto / linha zebrada", t["text"], t["zebra"], 4.5),
            ("texto / cabecalho da tabela", t["text"], t["header"], 4.5),
            ("texto / barra lateral", t["text"], t["chrome"], 4.5),
            ("grupo / barra lateral", t["muted"], t["chrome"], 4.5),
            ("icone / barra lateral", t["accent"], t["chrome"], 3.0),
            ("titulo / faixa", t["accent"], t["surface"], 4.5),
            ("icone / botao secundario", t["accent"], t["surface_alt"], 3.0),
            ("prazo vencido / linha zebrada", t["danger"], t["zebra"], 4.5),
            ("prazo proximo / linha zebrada", t["warning"], t["zebra"], 4.5),
            ("muted / superficie", t["muted"], t["surface"], 4.5),
            ("muted / fundo", t["muted"], t["bg"], 4.5),
            ("sutil / superficie", t["subtle"], t["surface"], 4.5),
            ("sutil / campo segmentado", t["muted"], t["surface_alt"], 4.5),
            ("texto do botao primario", t["accent_text"], t["accent"], 4.5),
            ("texto do botao primario (hover)", t["accent_text"], t["accent_hover"], 4.5),
            ("prazo vencido / superficie", t["danger"], t["surface"], 4.5),
            ("prazo proximo / superficie", t["warning"], t["surface"], 4.5),
            ("borda de campo / superficie", t["input_border"], t["surface"], 3.0),
            ("anel de foco / superficie", t["ring"], t["surface"], 3.0),
            ("anel de foco / fundo", t["ring"], t["bg"], 3.0),
        ]
        for categoria, cor in STATUS[nome].items():
            pares.append((f"texto no selo {categoria}", t["status_text"], cor, 4.5))
            pares.append((f"icone de status {categoria}", cor, t["surface"], 3.0))
        print(f"\nTema {nome}")
        for rotulo, frente, fundo, minimo in pares:
            valor = contraste(frente, fundo)
            ok = valor >= minimo
            falhas += 0 if ok else 1
            print(f"  {'ok   ' if ok else 'FALHA'} {valor:5.2f} (min {minimo})  {rotulo}")
    print(f"\n{falhas} falha(s)")
    return 1 if falhas else 0


def carregar_fonte() -> str:
    familias = set()
    if FONTES.is_dir():
        for arquivo in sorted(FONTES.glob("*.ttf")):
            identificador = QFontDatabase.addApplicationFont(str(arquivo))
            familias.update(QFontDatabase.applicationFontFamilies(identificador))
    if "Inter" in familias or "Inter" in QFontDatabase.families():
        return "Inter"
    return "Segoe UI"


def main() -> int:
    global ANIMAR, FAMILIA
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tema", choices=("claro", "escuro"), default="claro")
    parser.add_argument("--sem-animacao", action="store_true")
    parser.add_argument("--contraste", action="store_true")
    parser.add_argument("--shot", metavar="ARQUIVO.png")
    parser.add_argument("--estado", choices=("normal", "lote", "vazio", "carregando"), default="normal")
    args = parser.parse_args()

    app = QApplication(sys.argv[:1])
    if args.contraste:
        return conferir_contraste()
    ANIMAR = not (args.sem_animacao or args.shot)
    FAMILIA = carregar_fonte()
    TEMA.nome = args.tema
    pagina = Pagina()
    pagina.resize(1440, 860)
    if args.estado == "lote":
        pagina.definir_lote(True)
        for linha in pagina.modelo.linhas[2:5]:
            pagina.modelo.alternar(linha)
    elif args.estado == "vazio":
        pagina.busca.setText("proposta inexistente")
    elif args.estado == "carregando":
        pagina.pilha.setCurrentWidget(pagina.esqueleto)
    else:
        pagina.tabela.selectRow(3)
    pagina.show()
    if args.shot:
        def fotografar():
            pagina.grab().save(args.shot)
            print(f"fonte={FAMILIA} salvo={args.shot}")
            app.quit()

        QTimer.singleShot(500, fotografar)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
