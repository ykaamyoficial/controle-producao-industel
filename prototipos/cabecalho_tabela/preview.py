"""Prototipo ISOLADO do CABECALHO da tabela padrao ("Como e hoje" x "Proposto").

Nao importa nada de `app/`, nao fala com a API e nao altera o sistema: os dados sao ficticios.
Le somente os SVGs Lucide em `app/assets/icons/lucide/`. Serve para o Henrique ver o cabecalho
novo ao lado do atual, com a mesma tabela, antes de qualquer mudanca real.

Uso:
    python prototipos/cabecalho_tabela/preview.py
    python prototipos/cabecalho_tabela/preview.py --tema escuro
    python prototipos/cabecalho_tabela/preview.py --sem-animacao
    python prototipos/cabecalho_tabela/preview.py --shot saida.png --estado lote
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import (
    QAbstractTableModel, QByteArray, QEasingCurve, QModelIndex, QPointF, QRect, QRectF, QSize,
    QSortFilterProxyModel, Qt, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton, QStyledItemDelegate,
    QStyle, QStyleOptionButton, QTableView, QVBoxLayout, QWidget,
)

AQUI = Path(__file__).resolve().parent
LUCIDE = AQUI.parents[1] / "app" / "assets" / "icons" / "lucide"
FONTES = AQUI.parents[1] / "app" / "assets" / "fonts"
FAMILIA = "Segoe UI"
ANIMAR = True
ALTURA_LINHA = 40

TEMAS = {
    "claro": {
        "bg": "#F5F7FB", "surface": "#FFFFFF", "zebra": "#EEF4FE", "header": "#DBEAFE", "header_hover": "#CFE1FB",
        "text": "#0F172A", "muted": "#475569", "subtle": "#5B6B82", "border": "#C3D3EA", "input_border": "#8391A6",
        "accent": "#006FC9", "accent_text": "#FFFFFF", "accent_soft": "#E3F0FB",
        "waiting": "#2563EB", "pending": "#A2500A", "running": "#C2410C", "danger": "#B91C1C",
    },
    "escuro": {
        "bg": "#0F172A", "surface": "#172033", "zebra": "#1C2740", "header": "#24324A", "header_hover": "#2D3D5A",
        "text": "#F8FAFC", "muted": "#CBD5E1", "subtle": "#9FB0C6", "border": "#3A4B6A", "input_border": "#6B7C95",
        "accent": "#38BDF8", "accent_text": "#0F172A", "accent_soft": "#17364F",
        "waiting": "#60A5FA", "pending": "#FACC15", "running": "#FB923C", "danger": "#FB7185",
    },
}
TEMA = {"nome": "claro"}


def cor(chave: str, alfa: float | None = None) -> QColor:
    c = QColor(TEMAS[TEMA["nome"]][chave])
    if alfa is not None:
        c.setAlphaF(alfa)
    return c


def mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(*(round(x + (y - x) * t) for x, y in zip(a.getRgb(), b.getRgb())))


CURVA = QEasingCurve(QEasingCurve.BezierSpline)
CURVA.addCubicBezierSegment(QPointF(0.23, 1.0), QPointF(0.32, 1.0), QPointF(1.0, 1.0))
_SVG: dict[str, str] = {}


def icone(p: QPainter, nome: str, rect: QRectF, cor_: QColor) -> None:
    if nome not in _SVG:
        arquivo = LUCIDE / f"{nome}.svg"
        _SVG[nome] = arquivo.read_text(encoding="utf-8") if arquivo.exists() else ""
    if _SVG[nome]:
        QSvgRenderer(QByteArray(_SVG[nome].replace("currentColor", cor_.name()).encode("utf-8"))).render(p, rect)


def seta(p: QPainter, caixa: QRectF, descendente: bool, cor_: QColor) -> None:
    """Seta de ordenacao desenhada no codigo (haste + ponta); a biblioteca de icones nao tem seta para cima."""
    p.save()
    p.setPen(QPen(cor_, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    x, topo, base = caixa.center().x(), caixa.top() + 2, caixa.bottom() - 2
    p.drawLine(QPointF(x, topo), QPointF(x, base))
    ponta = 3.6
    if descendente:
        p.drawLine(QPointF(x - ponta, base - ponta), QPointF(x, base))
        p.drawLine(QPointF(x + ponta, base - ponta), QPointF(x, base))
    else:
        p.drawLine(QPointF(x - ponta, topo + ponta), QPointF(x, topo))
        p.drawLine(QPointF(x + ponta, topo + ponta), QPointF(x, topo))
    p.restore()


def duplo(p: QPainter, caixa: QRectF, cor_: QColor) -> None:
    """Dois chevrons (sobe/desce): coluna ordenavel que ainda nao esta ordenada."""
    p.save()
    p.setPen(QPen(cor_, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    x, y = caixa.center().x(), caixa.center().y()
    p.drawPolyline([QPointF(x - 3.5, y - 1.5), QPointF(x, y - 5), QPointF(x + 3.5, y - 1.5)])
    p.drawPolyline([QPointF(x - 3.5, y + 1.5), QPointF(x, y + 5), QPointF(x + 3.5, y + 1.5)])
    p.restore()


def fonte(px: int, peso: int = 400) -> QFont:
    f = QFont(FAMILIA)
    f.setPixelSize(px)
    f.setWeight(QFont.Weight(peso))
    return f


# --------------------------------------------------------------------------------------------------
# Dados ficticios
# --------------------------------------------------------------------------------------------------
COLUNAS = [
    # (titulo, chave, largura, ordenavel, icone-no-cabecalho, dica)
    ("", "selecao", 46, False, None, ""),
    ("", "status_icone", 46, False, "circle-dot", "Situação rápida da proposta"),
    ("", "chat", 46, False, "message-circle", "Conversa da proposta"),
    ("Proposta", "proposta", 150, True, None, ""),
    ("Cliente", "cliente", 250, True, None, ""),
    ("Etapa/Status", "status", 210, True, None, ""),
    ("Prazo", "prazo", 190, True, None, ""),
    ("Obra/Site", "obra", 0, True, None, ""),
]
LINHAS = [
    ("CP 05640", "MNS ENGENHARIA", "Aguardando início", "waiting", "28/10/2026", "2026-10-28", "SITE - MSCMP007"),
    ("CP 05641", "MNS ENGENHARIA", "Aguardando início", "waiting", "28/10/2026", "2026-10-28", "SITE - MSCMP010"),
    ("CP 05630", "EQUATORIAL GOIAS DIST. DE ENERGIA S/A", "Aguardando início", "waiting", "24/10/2026", "2026-10-24", "PEDIDO COMPRA 7000056232"),
    ("CP 05620", "EQUATORIAL GOIAS DIST. DE ENERGIA S/A", "Aguardando início", "waiting", "23/10/2026", "2026-10-23", "PEDIDO COMPRA 7000056167"),
    ("CP 05530-2", "MNS ENGENHARIA", "Item pendente de fabricação", "pending", "01/10/2026", "2026-10-01", "TAMTSNOD004 - SN-SNOMN9 - COLLOG"),
    ("CP 05492", "MNS ENGENHARIA", "Item pendente de fabricação", "pending", "30/09/2026", "2026-09-30", "MSBTG004_A"),
    ("CP 05639", "MNS ENGENHARIA", "Em produção", "running", "28/10/2026", "2026-10-28", "PARA ESTOQUE"),
    ("CP 05632", "MNS ENGENHARIA", "Em produção", "running", "25/10/2026", "2026-10-25", "MTVRZ003 - MTW29"),
    ("CP 05633", "MNS ENGENHARIA", "Em produção", "running", "25/10/2026", "2026-10-25", "MTVRZ004 - MTW30"),
    ("CP 05634", "EQUATORIAL PARÁ DISTRIBUIDORA DE ENERGIA S.A.", "Em produção", "running", "26/10/2026", "2026-10-26", "PEDIDO COMPRA 7000056169"),
    ("CP 05635", "MNS ENGENHARIA", "Aguardando início", "waiting", "29/10/2026", "2026-10-29", "SITE - MSRBS015"),
    ("CP 05636", "MNS ENGENHARIA", "Em produção", "running", "30/10/2026", "2026-10-30", "MTVRZ005 - MTW31"),
]
PAPEL_ORDEM = Qt.UserRole + 1


class Modelo(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self.lote = False
        self.marcadas: set[int] = set()

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(LINHAS)

    def columnCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(COLUNAS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUNAS[section][0]
        if orientation == Qt.Horizontal and role == Qt.ToolTipRole:
            return COLUNAS[section][5] or None
        return None

    def data(self, index, role=Qt.DisplayRole):
        linha, coluna = index.row(), index.column()
        valores = LINHAS[linha]
        chave = COLUNAS[coluna][1]
        if role == PAPEL_ORDEM:
            return {"proposta": valores[0], "cliente": valores[1], "status": valores[2], "prazo": valores[5], "obra": valores[6]}.get(chave, "")
        if role == Qt.DisplayRole:
            return {"proposta": valores[0], "cliente": valores[1], "status": valores[2], "prazo": valores[4], "obra": valores[6]}.get(chave)
        if role == Qt.UserRole:
            return valores[3]
        return None


class Filtro(QSortFilterProxyModel):
    def lessThan(self, a, b):  # noqa: N802
        return str(a.data(PAPEL_ORDEM)) < str(b.data(PAPEL_ORDEM))


class Delegate(QStyledItemDelegate):
    def __init__(self, modelo: Modelo, parent=None):
        super().__init__(parent)
        self.modelo = modelo

    def paint(self, p: QPainter, option, index):  # noqa: N802
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = option.rect
        p.fillRect(r, cor("zebra") if index.row() % 2 else cor("surface"))
        chave = COLUNAS[index.column()][1]
        if chave == "selecao" and self.modelo.lote:
            marcar = index.row() in self.modelo.marcadas
            caixa = QRectF(r.center().x() - 8, r.center().y() - 8, 16, 16)
            p.setPen(QPen(cor("accent") if marcar else cor("input_border"), 1.4))
            p.setBrush(cor("accent") if marcar else cor("surface"))
            p.drawRoundedRect(caixa, 4, 4)
            if marcar:
                icone(p, "check", caixa.adjusted(2, 2, -2, -2), cor("accent_text"))
        elif chave == "status_icone":
            icone(p, "circle-dot", QRectF(r.center().x() - 9, r.center().y() - 9, 18, 18), cor(index.data(Qt.UserRole)))
        elif chave == "chat":
            icone(p, "message-circle", QRectF(r.center().x() - 9, r.center().y() - 9, 18, 18), cor("muted"))
        elif chave == "status":
            texto = str(index.data())
            p.setFont(fonte(12, 700))
            largura = min(r.width() - 24, QFontMetrics(p.font()).horizontalAdvance(texto) + 28)
            pilula = QRectF(r.center().x() - largura / 2, r.center().y() - 11, largura, 22)
            p.setPen(Qt.NoPen)
            p.setBrush(cor(index.data(Qt.UserRole)))
            p.drawRoundedRect(pilula, 11, 11)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(pilula, Qt.AlignCenter, texto)
        else:
            p.setFont(fonte(12, 700 if chave == "proposta" else 400))
            p.setPen(cor("text"))
            p.drawText(r.adjusted(8, 0, -8, 0), Qt.AlignCenter | Qt.TextWordWrap, str(index.data() or ""))
        p.restore()

    def sizeHint(self, option, index):  # noqa: N802
        return QSize(0, ALTURA_LINHA)


# --------------------------------------------------------------------------------------------------
# Cabecalho "como e hoje": reproduz o QHeaderView atual (estilo plano, seta nativa, caixa nativa)
# --------------------------------------------------------------------------------------------------
class CabecalhoAtual(QHeaderView):
    clicou_todos = Signal()

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.lote = False
        self.setDefaultAlignment(Qt.AlignCenter)
        self.setFixedHeight(34)
        self.setStretchLastSection(True)
        self.setSectionsClickable(True)
        self.setSortIndicatorShown(True)

    def paintSection(self, painter, rect, indice):  # noqa: N802
        painter.save()
        painter.fillRect(rect, cor("header"))
        painter.setPen(QPen(cor("border"), 1))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.setPen(cor("text"))
        painter.setFont(fonte(13, 700))
        painter.drawText(rect.adjusted(8, 3, -8, -3), Qt.AlignCenter, str(self.model().headerData(indice, Qt.Horizontal) or ""))
        painter.restore()
        if indice == self.sortIndicatorSection():
            painter.save()
            painter.setPen(cor("muted"))
            painter.drawText(rect.adjusted(0, 0, 0, 0), Qt.AlignHCenter | Qt.AlignTop, "⌄" if self.sortIndicatorOrder() == Qt.DescendingOrder else "⌃")
            painter.restore()
        if self.lote and indice == 0:
            opcao = QStyleOptionButton()
            ind = self.style().subElementRect(QStyle.SE_CheckBoxIndicator, opcao, self)
            opcao.rect = QRect(rect.x() + (rect.width() - ind.width()) // 2, rect.y() + (rect.height() - ind.height()) // 2, ind.width(), ind.height())
            opcao.state = QStyle.State_Enabled | QStyle.State_Off
            self.style().drawControl(QStyle.CE_CheckBox, opcao, painter, self)


# --------------------------------------------------------------------------------------------------
# Cabecalho proposto
# --------------------------------------------------------------------------------------------------
class CabecalhoNovo(QHeaderView):
    """Cabecalho pintado por token: separadores curtos, hover suave, seta de ordem propria (so na
    coluna ordenada, fantasma no hover das outras), icone nas colunas sem titulo e caixa de
    selecao igual a das linhas."""

    ALTURA = 38

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.lote = False
        self.todas = Qt.Unchecked
        self.setFixedHeight(self.ALTURA)
        self.setStretchLastSection(True)
        self.setSectionsClickable(True)
        self.setSortIndicatorShown(False)  # a seta nativa some: o cabecalho pinta a propria
        self.setMouseTracking(True)
        self.setHighlightSections(False)
        self._hover: dict[int, float] = {}
        self._anims: dict[int, QVariantAnimation] = {}
        self._barra: dict[int, float] = {}
        self._barra_anim: dict[int, QVariantAnimation] = {}
        self._atual = -1
        self.sortIndicatorChanged.connect(self._ordem_mudou)

    # -- movimento ----------------------------------------------------------------------------------
    def _animar(self, memoria: dict, anims: dict, secao: int, fim: float, ms: int) -> None:
        anim = anims.get(secao)
        if anim is None:
            anim = QVariantAnimation(self)
            anim.setEasingCurve(CURVA)
            anim.valueChanged.connect(lambda v, s=secao, m=memoria: (m.__setitem__(s, float(v)), self.viewport().update()))
            anims[secao] = anim
        anim.stop()
        if not ANIMAR:
            memoria[secao] = fim
            self.viewport().update()
            return
        anim.setDuration(ms)
        anim.setStartValue(memoria.get(secao, 0.0))
        anim.setEndValue(fim)
        anim.start()

    def _ordem_mudou(self, secao: int, _ordem) -> None:
        for outro in list(self._barra):
            if outro != secao:
                self._animar(self._barra, self._barra_anim, outro, 0.0, 120)
        self._barra[secao] = 0.0
        self._animar(self._barra, self._barra_anim, secao, 1.0, 240)

    def ordenavel(self, secao: int) -> bool:
        return bool(COLUNAS[secao][3])

    def mouseMoveEvent(self, evento):  # noqa: N802
        secao = self.logicalIndexAt(evento.position().toPoint())
        if secao != self._atual:
            if self._atual >= 0:
                self._animar(self._hover, self._anims, self._atual, 0.0, 140)
            self._atual = secao
            if secao >= 0 and (self.ordenavel(secao) or secao == 0 and self.lote):
                self._animar(self._hover, self._anims, secao, 1.0, 140)
        self.setCursor(Qt.PointingHandCursor if secao >= 0 and (self.ordenavel(secao) or secao == 0 and self.lote) else Qt.ArrowCursor)
        super().mouseMoveEvent(evento)

    def leaveEvent(self, evento):  # noqa: N802
        if self._atual >= 0:
            self._animar(self._hover, self._anims, self._atual, 0.0, 140)
        self._atual = -1
        super().leaveEvent(evento)

    def mousePressEvent(self, evento):  # noqa: N802
        secao = self.logicalIndexAt(evento.position().toPoint())
        if secao >= 0 and not self.ordenavel(secao):
            if secao == 0 and self.lote:
                self.todas = Qt.Unchecked if self.todas == Qt.Checked else Qt.Checked
                self.viewport().update()
            evento.accept()
            return
        super().mousePressEvent(evento)

    # -- pintura -------------------------------------------------------------------------------------
    def paintSection(self, p: QPainter, rect: QRect, secao: int) -> None:  # noqa: N802
        titulo, _chave, _w, ordenavel, glifo, _dica = COLUNAS[secao]
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        fundo = cor("header")
        h = self._hover.get(secao, 0.0)
        if h > 0:
            fundo = mix(fundo, cor("header_hover"), h)
        p.fillRect(rect, fundo)

        # linha de baixo: mais firme que a atual (separa de verdade o cabecalho do corpo)
        p.setPen(QPen(cor("border"), 1))
        p.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        # separador curto entre colunas (nao no fim, nao ao lado da coluna em hover)
        if secao < self.count() - 1 and h < 0.05 and self._hover.get(secao + 1, 0.0) < 0.05:
            p.setPen(QPen(cor("border"), 1))
            meio = rect.center().y()
            p.drawLine(rect.right(), meio - 8, rect.right(), meio + 8)

        ordenada = ordenavel and self.sortIndicatorSection() == secao
        destaque = cor("accent") if ordenada else cor("text")
        area = rect.adjusted(10, 0, -10, -1)

        if secao == 0:
            if self.lote:
                self._caixa(p, QRectF(rect.center().x() - 8, rect.center().y() - 8 - 0.5, 16, 16))
        elif glifo:
            icone(p, glifo, QRectF(rect.center().x() - 8, rect.center().y() - 8 - 0.5, 16, 16), mix(cor("muted"), cor("accent"), h))
        else:
            p.setFont(fonte(13, 700))
            fm = QFontMetrics(p.font())
            reserva = 14 if ordenavel else 0  # reserva o lugar da seta: o titulo nao "pula" quando ela aparece
            texto = fm.elidedText(str(titulo), Qt.ElideRight, max(10, area.width() - reserva - 4))
            largura_texto = fm.horizontalAdvance(texto)
            grupo = largura_texto + (reserva + 4 if ordenavel else 0)
            x = area.x() + (area.width() - grupo) / 2
            p.setPen(mix(destaque, cor("accent"), h * 0.6) if not ordenada else destaque)
            p.drawText(QRectF(x, rect.y(), largura_texto + 2, rect.height() - 1), Qt.AlignVCenter | Qt.AlignLeft, texto)
            if ordenavel:
                ax = x + largura_texto + 4
                caixa = QRectF(ax, rect.center().y() - 6.5, 13, 13)
                if ordenada:
                    seta(p, caixa, self.sortIndicatorOrder() == Qt.DescendingOrder, cor("accent"))
                elif h > 0.02:
                    duplo(p, caixa, cor("subtle", h))

        # barra de ordenacao: 2px na cor de destaque que cresce do centro
        b = self._barra.get(secao, 1.0 if ordenada else 0.0) if ordenada else self._barra.get(secao, 0.0)
        if b > 0.001:
            meia = rect.width() * 0.5 * b
            p.setPen(Qt.NoPen)
            p.setBrush(cor("accent"))
            p.drawRoundedRect(QRectF(rect.center().x() - meia, rect.bottom() - 1.5, meia * 2, 2.5), 1.2, 1.2)

        # pega de redimensionar: aparece quando o mouse esta na coluna
        if h > 0.05 and secao < self.count() - 1:
            p.setPen(QPen(cor("accent", 0.55 * h), 2))
            p.drawLine(rect.right() - 1, rect.top() + 8, rect.right() - 1, rect.bottom() - 8)
        p.restore()

    def _caixa(self, p: QPainter, caixa: QRectF) -> None:
        marcada = self.todas == Qt.Checked
        parcial = self.todas == Qt.PartiallyChecked
        p.setPen(QPen(cor("accent") if (marcada or parcial) else cor("input_border"), 1.4))
        p.setBrush(cor("accent") if (marcada or parcial) else cor("surface"))
        p.drawRoundedRect(caixa, 4, 4)
        if marcada:
            icone(p, "check", caixa.adjusted(2, 2, -2, -2), cor("accent_text"))
        elif parcial:
            p.setPen(QPen(cor("accent_text"), 2, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(caixa.left() + 4, caixa.center().y()), QPointF(caixa.right() - 4, caixa.center().y()))


class Tabela(QTableView):
    """Sombra fina sob o cabecalho quando a tabela foi rolada (da profundidade sem pesar)."""

    def __init__(self, cabecalho: QHeaderView, modelo: Modelo, parent=None, cantos: bool = False):
        super().__init__(parent)
        self.modelo = modelo
        self.cantos = cantos
        self.setHorizontalHeader(cabecalho)
        self.proxy = Filtro(self)
        self.proxy.setSourceModel(modelo)
        self.setModel(self.proxy)
        self.setItemDelegate(Delegate(modelo, self))
        self.setShowGrid(False)
        self.setFrameShape(QFrame.NoFrame)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(ALTURA_LINHA)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setSortingEnabled(True)
        for i, coluna in enumerate(COLUNAS):
            cabecalho.setSectionResizeMode(i, QHeaderView.Fixed if coluna[2] else QHeaderView.Stretch)
            if coluna[2]:
                self.setColumnWidth(i, coluna[2])
        self.setWordWrap(True)
        self.aplicar_tema()

    def aplicar_tema(self) -> None:
        """Canto superior direito: a barra de rolagem comeca ABAIXO do cabecalho e o espaco acima dela
        fica na cor do cabecalho, entao a faixa azul vai de ponta a ponta (sem 'degrau')."""
        if not self.cantos:  # "como e hoje": barra de rolagem padrao, com o degrau no canto
            self.setStyleSheet(f"QTableView {{ background: {TEMAS[TEMA['nome']]['surface']}; border: 0; }}")
            return
        altura = self.horizontalHeader().height()
        t = TEMAS[TEMA["nome"]]
        paleta = self.palette()
        paleta.setColor(paleta.ColorRole.Window, QColor(t["header"]))
        self.setPalette(paleta)
        self.setStyleSheet(f"""
            QTableView {{ background: {t['surface']}; border: 0; border-bottom-left-radius: 14px; border-bottom-right-radius: 14px; }}
            QScrollBar:vertical {{ background: {t['surface']}; width: 12px; margin: {altura}px 0 0 0; border: 0; }}
            QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 4px; min-height: 32px; margin: 2px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        """)

    def paintEvent(self, evento):  # noqa: N802
        super().paintEvent(evento)
        if self.verticalScrollBar().value() > 0:
            p = QPainter(self.viewport())
            g = QLinearGradient(0, 0, 0, 7)
            g.setColorAt(0, QColor(0, 0, 0, 38 if TEMA["nome"] == "claro" else 90))
            g.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(0, 0, self.viewport().width(), 7, g)
            p.end()


class Painel(QFrame):
    def __init__(self, titulo: str, nota: str, tabela: Tabela):
        super().__init__()
        self.setObjectName("Painel")
        caixa = QVBoxLayout(self)
        caixa.setContentsMargins(0, 0, 0, 0)
        caixa.setSpacing(0)
        topo = QWidget()
        linha = QVBoxLayout(topo)
        linha.setContentsMargins(16, 12, 16, 8)
        linha.setSpacing(2)
        t = QLabel(titulo)
        t.setObjectName("Titulo")
        n = QLabel(nota)
        n.setObjectName("Nota")
        n.setWordWrap(True)
        linha.addWidget(t)
        linha.addWidget(n)
        caixa.addWidget(topo)
        caixa.addWidget(tabela, 1)


class Janela(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Protótipo — cabeçalho da tabela padrão")
        self.resize(1360, 820)
        self.modelo = Modelo()
        self.atual = CabecalhoAtual()
        self.novo = CabecalhoNovo()
        self.tabela_atual = Tabela(self.atual, self.modelo)
        self.tabela_nova = Tabela(self.novo, self.modelo, cantos=True)
        self.tabela_atual.sortByColumn(0, Qt.AscendingOrder)
        self.tabela_nova.sortByColumn(6, Qt.AscendingOrder)

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(16, 12, 16, 12)
        raiz.setSpacing(10)
        barra = QHBoxLayout()
        titulo = QLabel("Cabeçalho da tabela — como é hoje × proposto")
        titulo.setObjectName("TituloGrande")
        barra.addWidget(titulo)
        barra.addStretch(1)
        self.b_lote = self._botao("Modo de seleção", self._alternar_lote, True)
        self.b_tema = self._botao("Tema escuro", self._alternar_tema)
        self.b_rolar = self._botao("Rolar tabela", self._rolar)
        for b in (self.b_lote, self.b_rolar, self.b_tema):
            barra.addWidget(b)
        raiz.addLayout(barra)
        dica = QLabel("Passe o mouse, clique nos títulos para ordenar e arraste a borda entre colunas. As duas tabelas usam os mesmos dados.")
        dica.setObjectName("Nota")
        raiz.addWidget(dica)
        raiz.addWidget(Painel("Como é hoje", "Seta nativa minúscula em cima do primeiro título, sem resposta ao passar o mouse, colunas de ícone sem nome, caixa de seleção diferente da das linhas e a faixa azul que termina antes da barra de rolagem (degrau no canto direito).", self.tabela_atual), 1)
        raiz.addWidget(Painel("Proposto", "Seta própria só na coluna ordenada (fantasma no hover das outras), barra de destaque, separadores curtos, ícones nas colunas sem título, caixa igual à das linhas, sombra fina ao rolar e a faixa azul indo até o canto direito (a barra de rolagem começa abaixo dela).", self.tabela_nova), 1)
        self._estilo()

    def _botao(self, texto, ao_clicar, marcavel=False):
        b = QPushButton(texto)
        b.setCheckable(marcavel)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(ao_clicar)
        return b

    def _alternar_lote(self):
        ligado = self.b_lote.isChecked()
        self.modelo.lote = ligado
        self.atual.lote = ligado
        self.novo.lote = ligado
        self.modelo.marcadas = {0, 2, 3} if ligado else set()
        self.novo.todas = Qt.PartiallyChecked if ligado else Qt.Unchecked
        for t in (self.tabela_atual, self.tabela_nova):
            t.viewport().update()
            t.horizontalHeader().viewport().update()

    def _alternar_tema(self):
        TEMA["nome"] = "escuro" if TEMA["nome"] == "claro" else "claro"
        self.b_tema.setText("Tema claro" if TEMA["nome"] == "escuro" else "Tema escuro")
        self._estilo()
        for t in (self.tabela_atual, self.tabela_nova):
            t.aplicar_tema()
            t.viewport().update()
            t.horizontalHeader().viewport().update()

    def _rolar(self):
        for t in (self.tabela_atual, self.tabela_nova):
            barra = t.verticalScrollBar()
            barra.setValue(0 if barra.value() > 0 else barra.maximum())

    def _estilo(self):
        t = TEMAS[TEMA["nome"]]
        self.setStyleSheet(f"""
            QWidget {{ background: {t['bg']}; color: {t['text']}; font-family: '{FAMILIA}'; font-size: 13px; }}
            QFrame#Painel {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 14px; }}
            QFrame#Painel QWidget {{ background: transparent; }}
            QLabel#Titulo {{ font-size: 15px; font-weight: 800; color: {t['accent']}; }}
            QLabel#TituloGrande {{ font-size: 18px; font-weight: 800; }}
            QLabel#Nota {{ color: {t['muted']}; font-size: 12px; }}
            QHeaderView {{ background: transparent; border: 0; }}
            QPushButton {{ background: {t['accent_soft']}; color: {t['text']}; border: 0; border-radius: 10px; padding: 7px 14px; font-weight: 600; }}
            QPushButton:hover {{ background: {t['header_hover']}; }}
            QPushButton:checked {{ background: {t['accent']}; color: {t['accent_text']}; }}
            QToolTip {{ background: {t['text']}; color: {t['bg']}; border: 0; padding: 5px 8px; }}
        """)


def main() -> int:
    global ANIMAR
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tema", choices=("claro", "escuro"), default="claro")
    parser.add_argument("--sem-animacao", action="store_true")
    parser.add_argument("--shot", metavar="ARQUIVO.png")
    parser.add_argument("--estado", choices=("normal", "lote", "rolado"), default="normal")
    args = parser.parse_args()
    ANIMAR = not args.sem_animacao
    TEMA["nome"] = args.tema
    app = QApplication(sys.argv)
    global FAMILIA
    familias: set[str] = set()
    if FONTES.is_dir():
        for arquivo in sorted(FONTES.glob("*.ttf")):
            familias.update(QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(str(arquivo))))
    if "Inter" in familias:
        FAMILIA = "Inter"
    janela = Janela()
    janela._estilo()
    if args.tema == "escuro":
        janela.b_tema.setText("Tema claro")
    if args.estado == "lote":
        janela.b_lote.setChecked(True)
        janela._alternar_lote()
    if args.estado == "rolado":
        janela._rolar()
    janela.show()
    if args.shot:
        def salvar():
            # mostra o hover do cabecalho novo para a captura
            janela.grab().save(args.shot)
            app.quit()
        QTimer.singleShot(700, salvar)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
