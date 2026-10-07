"""Prototipo ISOLADO da tela "Detalhes da proposta" (todas as abas).

Reaproveita os componentes do prototipo do Controle Geral
(`prototipos/controle_geral/preview.py`) e abre os detalhes por cima dele,
como no sistema. Nao importa nada de `app/` nem fala com a API: os dados sao
ficticios e Editar/Acoes/Abrir carga nao executam nada.

Uso:
    python prototipos/detalhes_proposta/detalhes.py                # aba Resumo
    python prototipos/detalhes_proposta/detalhes.py --aba 2        # 0..5
    python prototipos/detalhes_proposta/detalhes.py --tema escuro
    python prototipos/detalhes_proposta/detalhes.py --shot saida.png --aba 1

Com a janela aberta: Esc ou clique fora fecha; duplo clique numa linha da
tabela reabre.
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "controle_geral"))

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal  # noqa: E402
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractItemView,
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QStackedLayout,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)

import preview as base  # noqa: E402
from preview import ALTURA_LINHA, HOJE, RAIO_CAMPO, TEMA, Botao, Esqueleto, animar, aparecer, fonte, mix, pintar_icone  # noqa: E402

# Categorias que a tela do Controle Geral nao usava. Amarelo e laranja ficam
# mais escuros que os atuais (#CA8A04 / #EA580C) para o texto branco do selo
# solido passar de 4.5:1.
base.STATUS["claro"].update({"attention": "#A16207", "progress": "#C2410C"})
base.STATUS["escuro"].update({"attention": "#FACC15", "progress": "#FB923C"})


def dia(deslocamento: int, hora: str = "") -> str:
    texto = (HOJE + timedelta(days=deslocamento)).strftime("%d/%m/%Y")
    return f"{texto} {hora}".strip()


# --------------------------------------------------------------------------
# Dados ficticios
# --------------------------------------------------------------------------
PRAZO_DIAS = 5
PROPOSTA = {
    "titulo": "CP 05672 | Torres Norte Telecom",
    "obra": "SP-CAMP-014 - Torre autoportante 40 m",
    "etapa": ("PRODUÇÃO · Em produção", "location_production"),
}
PASSOS = [
    {"nome": "Controle Geral", "estado": "feito", "rotulo": "Liberado para produção", "categoria": "done"},
    {"nome": "Produção", "estado": "atual", "rotulo": "Em produção", "categoria": "location_production"},
    {"nome": "Galvanização", "estado": "andamento", "rotulo": "Retornou parcial", "categoria": "location_galvanization"},
    {"nome": "Expedição", "estado": "andamento", "rotulo": "Entregue parcial", "categoria": "location_expedition"},
    {"nome": "Almoxarifado", "estado": "pendente", "rotulo": "Aguardando confirmação", "categoria": "neutral"},
]
DADOS = [
    ("Proposta", "CP 05672"),
    ("Cliente", "Torres Norte Telecom"),
    ("Obra/Site", "SP-CAMP-014 - Torre autoportante 40 m"),
    ("PD / Pedido", "PEDIDO COMPRA 7000056167"),
    ("Lote", "-"),
    ("Tipo", "Principal"),
    ("Prazo de entrega", dia(PRAZO_DIAS)),
]
ITENS = [
    (1, "MT-40-001", "Montante principal L 100x100x8 - módulo 1", 8, "86,40 kg", ("Entregue", "final_done")),
    (2, "MT-40-002", "Montante principal L 100x100x8 - módulo 2", 8, "84,10 kg", ("Entregue", "final_done")),
    (3, "DG-40-010", "Diagonal L 60x60x5 - face A/B", 24, "18,75 kg", ("Galvanizado - aguardando expedição", "location_expedition")),
    (4, "DG-40-011", "Diagonal L 60x60x5 - face C/D", 24, "18,75 kg", ("Enviado para galvanização", "location_galvanization")),
    (5, "HZ-40-020", "Horizontal L 50x50x5", 16, "12,30 kg", ("Produzido - disponível para galvanização", "location_galvanization")),
    (6, "CH-40-031", "Chapa de ligação 3/8\" - conjunto", 20, "6,85 kg", ("Em produção", "location_production")),
    (7, "CH-40-032", "Chapa de base 1\" com furação", 4, "41,20 kg", ("Em produção", "location_production")),
    (8, "ES-40-040", "Escada tipo marinheiro com guarda-corpo", 4, "58,00 kg", ("Em produção", "location_production")),
    (9, "PL-40-050", "Plataforma de descanso", 2, "112,50 kg", ("Em produção", "location_production")),
    (10, "SU-40-060", "Suporte de antena tubular 3 m", 6, "27,90 kg", ("Fluxo não definido", "neutral")),
    (11, "PF-40-070", "Kit de parafusos ASTM A325 galvanizados", 30, "Não informado", ("Não será produzido", "neutral")),
    (12, "AT-40-080", "Haste de aterramento e cordoalha", 2, "9,40 kg", ("Fluxo não definido", "neutral")),
]
CARGAS = [
    ("CG-0412", ("Retornou da galvanização", "done"), dia(-9), dia(-4), "Carlos M.", 32, 3, "Retorno completo, sem avarias."),
    ("CG-0431", ("Enviado para galvanização", "location_galvanization"), dia(-2), "-", "Rogério S.", 24, 2, "Previsão de retorno em 4 dias úteis."),
]
NOTAS = [
    ("NF 000.184.220", "1", dia(-3), 52, "1.240,00 kg"),
    ("NF 000.184.377", "1", dia(-1), 12, "225,00 kg"),
]
HISTORICO = [
    (("Expedição", "location_expedition"), "Separado", ("Entregue parcial", "location_expedition"), dia(-1, "14:12"), "marcos.s", "Retirada parcial pelo cliente, 52 itens."),
    (("Fiscal", "danger"), "Aguardando NF", ("NF parcial", "attention"), dia(-1, "11:40"), "ana.p", "NF 000.184.377 emitida."),
    (("Galvanização", "location_galvanization"), "Enviado para galvanização", ("Retornou parcial", "location_galvanization"), dia(-4, "16:05"), "carlos.m", "Carga CG-0412 retornou."),
    (("Expedição", "location_expedition"), "Em separação", ("Separado", "done"), dia(-4, "17:30"), "marcos.s", "-"),
    (("Galvanização", "location_galvanization"), "Em carga", ("Enviado para galvanização", "location_galvanization"), dia(-9, "08:20"), "carlos.m", "Carga CG-0412."),
    (("Produção", "location_production"), "Iniciado", ("Finalizado parcial", "attention"), dia(-10, "15:48"), "joao.f", "Módulos 1 e 2 concluídos."),
    (("Produção", "location_production"), "Não iniciado", ("Iniciado", "progress"), dia(-21, "07:35"), "joao.f", "-"),
    (("Controle Geral", "waiting"), "Não liberado", ("Liberado para produção", "waiting"), dia(-22, "10:02"), "henrique.l", "Projeto aprovado pelo cliente."),
    (("Controle Geral", "waiting"), "-", ("Não liberado", "neutral"), dia(-25, "09:14"), "henrique.l", "Proposta cadastrada."),
]
AREAS_FLUXO = [
    ("Controle Geral", "clipboard-check", ("Liberado para produção", "waiting"), [
        ("Entrada", dia(-25)), ("Última movimentação", f"{dia(-22, '10:02')} (henrique.l)")]),
    ("Produção", "factory", ("Em produção", "location_production"), [
        ("Quantidade total", "148"), ("Itens produzidos", "88"), ("Itens pendentes", "60"),
        ("Peso produzido", "2.290,00 kg"), ("Última movimentação", f"{dia(-10, '15:48')} (joao.f)")]),
    ("Galvanização", "layers", ("Retornou parcial", "location_galvanization"), [
        ("Peso enviado", "1.915,00 kg"), ("Peso retornado", "1.465,00 kg"), ("Peso pendente", "450,00 kg"),
        ("Última movimentação", f"{dia(-4, '16:05')} (carlos.m)")]),
    ("Expedição", "truck", ("Entregue parcial", "location_expedition"), [
        ("Disponível", "32"), ("Separado", "12"), ("Entregue", "52"), ("Saldo pendente", "96"),
        ("Última movimentação", f"{dia(-1, '14:12')} (marcos.s)")]),
    ("Almoxarifado", "warehouse", ("Aguardando confirmação", "neutral"), [
        ("Necessita almoxarifado", "Sim"), ("Última movimentação", "Sem movimentação registrada")]),
]


# --------------------------------------------------------------------------
# Componentes desta tela
# --------------------------------------------------------------------------
class Selo(QWidget):
    """Selo solido de status, igual ao da tabela."""

    def __init__(self, texto: str, categoria: str, parent=None):
        super().__init__(parent)
        self._texto = texto
        self._categoria = categoria
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        TEMA.mudou.connect(self.update)

    def sizeHint(self) -> QSize:
        return QSize(QFontMetrics(fonte(12, 700)).horizontalAdvance(self._texto) + 28, 24)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(TEMA.status(self._categoria))
        p.drawRoundedRect(QRectF(self.rect()), 12, 12)
        p.setFont(fonte(12, 700))
        p.setPen(TEMA.cor("status_text"))
        p.drawText(self.rect(), Qt.AlignCenter, self._texto)


class PrazoInfo(QWidget):
    """"Prazo: dd/mm/aaaa" + aviso quando esta vencido ou vence em ate 7 dias."""

    def __init__(self, dias: int, parent=None):
        super().__init__(parent)
        self._data = f"Prazo: {dia(dias)}"
        if dias < 0:
            self._aviso, self._token = f"vencido há {-dias} d", "danger"
        elif dias <= 7:
            self._aviso, self._token = ("vence hoje" if dias == 0 else f"em {dias} d"), "warning"
        else:
            self._aviso, self._token = "", ""
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        TEMA.mudou.connect(self.update)

    def sizeHint(self) -> QSize:
        largura = 22 + QFontMetrics(fonte(13, 500, True)).horizontalAdvance(self._data)
        if self._aviso:
            largura += 12 + 18 + QFontMetrics(fonte(12, 700, True)).horizontalAdvance(self._aviso)
        return QSize(largura + 4, 24)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cy = self.height() / 2
        pintar_icone(p, "clock", QRectF(0, cy - 8, 16, 16), TEMA.cor("muted"))
        f = fonte(13, 500, True)
        p.setFont(f)
        p.setPen(TEMA.cor("text"))
        largura = QFontMetrics(f).horizontalAdvance(self._data)
        p.drawText(QRectF(22, 0, largura + 2, self.height()), Qt.AlignVCenter, self._data)
        if self._aviso:
            x = 22 + largura + 12
            pintar_icone(p, "triangle-alert", QRectF(x, cy - 7, 14, 14), TEMA.cor(self._token))
            p.setFont(fonte(12, 700, True))
            p.setPen(TEMA.cor(self._token))
            p.drawText(QRectF(x + 18, 0, self.width(), self.height()), Qt.AlignVCenter, self._aviso)


class ChipIcone(QWidget):
    def __init__(self, icone_nome: str, categoria: str, parent=None):
        super().__init__(parent)
        self._icone = icone_nome
        self._categoria = categoria
        self.setFixedSize(32, 32)
        TEMA.mudou.connect(self.update)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(TEMA.cor("border"), 1))
        p.setBrush(TEMA.cor("surface_alt"))
        p.drawEllipse(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        pintar_icone(p, self._icone, QRectF(7.5, 7.5, 17, 17), TEMA.status(self._categoria))


class Barra(QWidget):
    """Barra de progresso fina; enche ao aparecer."""

    def __init__(self, fracao: float, parent=None):
        super().__init__(parent)
        self._alvo = max(0.0, min(1.0, fracao))
        self._v = 0.0
        self.setFixedHeight(6)
        self.setMinimumWidth(120)
        TEMA.mudou.connect(self.update)

    def showEvent(self, e):
        self._v = 0.0
        animar(self, "_v", self._alvo, 600)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(TEMA.cor("surface_alt") if TEMA.nome == "claro" else TEMA.cor("border"))
        p.drawRoundedRect(QRectF(self.rect()), 3, 3)
        if self._v > 0:
            p.setBrush(TEMA.cor("accent"))
            p.drawRoundedRect(QRectF(0, 0, max(6.0, self.width() * self._v), 6), 3, 3)


class Trilha(QWidget):
    """Fluxo da proposta: concluido (verde com check), etapa atual (pulsa),
    em andamento (cor da area) e pendente (tracejado)."""

    def __init__(self, passos: list[dict], parent=None):
        super().__init__(parent)
        self._passos = passos
        self._pulso = 0.0
        self.setFixedHeight(92)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(1700)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._tick)
        TEMA.mudou.connect(self.update)

    def _tick(self, valor):
        self._pulso = valor
        self.update()

    def showEvent(self, e):
        if base.ANIMAR:
            self._anim.start()

    def hideEvent(self, e):
        self._anim.stop()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        total = len(self._passos)
        margem = 84
        passo = min(236.0, (self.width() - 2 * margem) / max(1, total - 1))
        xs = [margem + i * passo for i in range(total)]
        cy = 24
        for i in range(total - 1):
            if self._passos[i + 1]["estado"] == "pendente":
                p.setPen(QPen(TEMA.cor("input_border"), 2, Qt.DashLine))
            else:
                p.setPen(QPen(TEMA.status("done"), 3))
            p.drawLine(QPointF(xs[i] + 22, cy), QPointF(xs[i + 1] - 22, cy))
        for x, item in zip(xs, self._passos):
            estado = item["estado"]
            cor = TEMA.status(item["categoria"])
            centro = QPointF(x, cy)
            if estado == "atual" and base.ANIMAR:
                halo = QColor(cor)
                halo.setAlphaF(0.38 * (1 - self._pulso))
                p.setPen(Qt.NoPen)
                p.setBrush(halo)
                p.drawEllipse(centro, 16 + 10 * self._pulso, 16 + 10 * self._pulso)
            if estado == "pendente":
                p.setPen(QPen(TEMA.cor("input_border"), 1.5, Qt.DashLine))
                p.setBrush(TEMA.cor("surface"))
                p.drawEllipse(centro, 15, 15)
                pintar_icone(p, "pause", QRectF(x - 7, cy - 7, 14, 14), TEMA.cor("subtle"))
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(cor)
                p.drawEllipse(centro, 16, 16)
                nome_icone = {"feito": "check", "atual": "play", "andamento": "clock"}[estado]
                pintar_icone(p, nome_icone, QRectF(x - 8, cy - 8, 16, 16), TEMA.cor("status_text"))
            p.setFont(fonte(13, 700 if estado == "atual" else 600))
            p.setPen(TEMA.cor("text"))
            p.drawText(QRectF(x - 110, 48, 220, 18), Qt.AlignCenter, item["nome"])
            p.setFont(fonte(12, 500))
            p.setPen(TEMA.cor("muted"))
            p.drawText(QRectF(x - 110, 67, 220, 16), Qt.AlignCenter, item["rotulo"])


class Abas(QWidget):
    """Abas com contagem; o traco azul desliza ate a aba escolhida."""

    mudou = Signal(int)

    def __init__(self, itens: list[tuple[str, int | None]], parent=None):
        super().__init__(parent)
        self._itens = itens
        self._atual = 0
        self._hover = -1
        self._anel = False
        self._x, self._w = self._faixa(0)
        self.setFixedHeight(40)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        TEMA.mudou.connect(self.update)

    def _largura(self, indice: int) -> float:
        nome, contagem = self._itens[indice]
        largura = QFontMetrics(fonte(13, 700)).horizontalAdvance(nome) + 32
        if contagem is not None:
            largura += QFontMetrics(fonte(11, 700, True)).horizontalAdvance(str(contagem)) + 12 + 8
        return largura

    def _faixa(self, indice: int) -> tuple[float, float]:
        x = 2.0
        for i in range(indice):
            x += self._largura(i) + 4
        return x, self._largura(indice)

    def selecionar(self, indice: int, animado: bool = True) -> None:
        if not 0 <= indice < len(self._itens) or indice == self._atual:
            return
        self._atual = indice
        x, w = self._faixa(indice)
        animar(self, "_x", x, 240 if animado else 0)
        animar(self, "_w", w, 240 if animado else 0)
        self.mudou.emit(indice)

    def _indice_em(self, x: float) -> int:
        for i in range(len(self._itens)):
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

    def mousePressEvent(self, e):
        self.selecionar(self._indice_em(e.position().x()))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Right:
            self.selecionar(self._atual + 1)
        elif e.key() == Qt.Key_Left:
            self.selecionar(self._atual - 1)
        else:
            super().keyPressEvent(e)

    def focusInEvent(self, e):
        self._anel = base.foco_por_teclado(e)
        self.update()

    def focusOutEvent(self, e):
        self._anel = False
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        p.fillRect(QRectF(0, h - 1, self.width(), 1), TEMA.cor("border"))
        p.setClipRect(QRectF(0, 0, self.width(), h))
        for i, (nome, contagem) in enumerate(self._itens):
            x, w = self._faixa(i)
            ativo = i == self._atual
            corpo = QRectF(x + 0.5, 4.5, w - 1, h + 12)
            if ativo:
                p.setPen(QPen(TEMA.cor("border"), 1))
                p.setBrush(TEMA.cor("surface"))
                p.drawRoundedRect(corpo, RAIO_CAMPO, RAIO_CAMPO)
            elif i == self._hover:
                p.setPen(Qt.NoPen)
                p.setBrush(TEMA.cor("surface_alt"))
                p.drawRoundedRect(corpo.adjusted(0, 0, 0, -14), RAIO_CAMPO, RAIO_CAMPO)
            f = fonte(13, 700 if ativo else 500)
            p.setFont(f)
            p.setPen(TEMA.cor("text") if ativo or i == self._hover else TEMA.cor("muted"))
            largura_nome = QFontMetrics(fonte(13, 700)).horizontalAdvance(nome)
            p.drawText(QRectF(x + 16, 4, largura_nome + 2, h - 6), Qt.AlignVCenter | Qt.AlignLeft, nome)
            if contagem is not None:
                fc = fonte(11, 700, True)
                largura_pilula = QFontMetrics(fc).horizontalAdvance(str(contagem)) + 12
                pilula = QRectF(x + 16 + largura_nome + 8, h / 2 - 8, largura_pilula, 18)
                p.setPen(Qt.NoPen)
                p.setBrush(TEMA.cor("accent") if ativo else TEMA.cor("border"))
                p.drawRoundedRect(pilula, 9, 9)
                p.setFont(fc)
                p.setPen(TEMA.cor("accent_text") if ativo else TEMA.cor("text"))
                p.drawText(pilula, Qt.AlignCenter, str(contagem))
        p.setPen(Qt.NoPen)
        p.setBrush(TEMA.cor("accent"))
        p.drawRoundedRect(QRectF(self._x + 10, h - 3, self._w - 20, 3), 1.5, 1.5)
        if self._anel:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(TEMA.cor("ring"), 2))
            p.drawRoundedRect(QRectF(self._x + 2, 6, self._w - 4, h - 12), RAIO_CAMPO - 2, RAIO_CAMPO - 2)


# ---- tabela generica (itens, cargas, notas, historico) -------------------
class ModeloSimples(QAbstractTableModel):
    """colunas: (titulo, largura ou 0 para esticar, tipo). Tipos: texto, forte,
    mudo, centro, num, selo (rotulo, categoria) e area (rotulo, categoria)."""

    def __init__(self, colunas: list[tuple[str, int, str]], linhas: list[tuple]):
        super().__init__()
        self.colunas = colunas
        self.linhas = linhas

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.linhas)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.colunas)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        valor = self.linhas[index.row()][index.column()]
        texto = valor[0] if isinstance(valor, tuple) else str(valor)
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            return texto
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role=Qt.DisplayRole):
        if orientation != Qt.Horizontal:
            return None
        if role == Qt.DisplayRole:
            return self.colunas[section][0]
        if role == Qt.TextAlignmentRole:
            lado = Qt.AlignRight if self.colunas[section][2] == "num" else Qt.AlignLeft
            return int(lado | Qt.AlignVCenter)
        return None


class DelegateSimples(QStyledItemDelegate):
    def sizeHint(self, option, index) -> QSize:
        return QSize(0, ALTURA_LINHA)

    def paint(self, p: QPainter, option, index: QModelIndex) -> None:
        tabela: TabelaSimples = self.parent()
        modelo: ModeloSimples = tabela.model()
        valor = modelo.linhas[index.row()][index.column()]
        tipo = modelo.colunas[index.column()][2]
        r = QRectF(option.rect)
        cy = r.center().y()
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        selecionada = tabela.selecionavel and tabela.selectionModel().isRowSelected(index.row(), QModelIndex())
        if selecionada:
            p.fillRect(r, TEMA.cor("selected"))
            if index.column() == 0:
                p.fillRect(QRectF(r.left(), r.top(), 4, r.height()), TEMA.cor("accent"))
        elif tabela.linha_hover == index.row():
            p.fillRect(r, TEMA.cor("surface_hover"))
        elif index.row() % 2:
            p.fillRect(r, TEMA.cor("zebra"))

        if tipo == "selo":
            rotulo, categoria = valor
            f = fonte(12, 600)
            pilula = QRectF(r.left() + 8, cy - 11, r.width() - 24, 22)
            p.setBrush(TEMA.status(categoria))
            p.drawRoundedRect(pilula, 11, 11)
            p.setFont(f)
            p.setPen(TEMA.cor("status_text"))
            p.drawText(pilula, Qt.AlignCenter, QFontMetrics(f).elidedText(rotulo, Qt.ElideRight, int(pilula.width()) - 16))
        elif tipo == "area":
            rotulo, categoria = valor
            p.setBrush(TEMA.status(categoria))
            p.drawEllipse(QPointF(r.left() + 16, cy), 4.5, 4.5)
            p.setFont(fonte(13, 600))
            p.setPen(TEMA.cor("text"))
            p.drawText(r.adjusted(28, 0, -8, 0), Qt.AlignVCenter | Qt.AlignLeft, rotulo)
        else:
            texto = str(valor)
            vazio = texto in ("-", "Não informado")
            if vazio and texto == "-":
                texto = "—"
            peso = 600 if tipo == "forte" else 400
            f = fonte(13, peso, tabular=tipo in ("forte", "num", "centro"))
            cor = TEMA.cor("subtle") if vazio else TEMA.cor("muted") if tipo == "mudo" else TEMA.cor("text")
            area = r.adjusted(10, 0, -14 if tipo == "num" else -10, 0)
            lado = Qt.AlignRight if tipo == "num" else Qt.AlignHCenter if tipo == "centro" else Qt.AlignLeft
            p.setFont(f)
            p.setPen(cor)
            p.drawText(area, Qt.AlignVCenter | lado, QFontMetrics(f).elidedText(texto, Qt.ElideRight, int(area.width())))
        p.restore()


class TabelaSimples(QTableView):
    def __init__(self, colunas: list[tuple[str, int, str]], linhas: list[tuple], selecionavel: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("Simples")
        self.linha_hover = -1
        self.selecionavel = selecionavel
        self.setModel(ModeloSimples(colunas, linhas))
        self.setItemDelegate(DelegateSimples(self))
        self.setShowGrid(False)
        self.setFrameShape(QFrame.NoFrame)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection if selecionavel else QAbstractItemView.NoSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(ALTURA_LINHA)
        cabecalho = self.horizontalHeader()
        cabecalho.setFixedHeight(34)
        cabecalho.setHighlightSections(False)
        cabecalho.setSectionsClickable(False)
        for coluna, (_titulo, largura, _tipo) in enumerate(colunas):
            if largura:
                cabecalho.setSectionResizeMode(coluna, QHeaderView.Fixed)
                self.setColumnWidth(coluna, largura)
            else:
                cabecalho.setSectionResizeMode(coluna, QHeaderView.Stretch)
        TEMA.mudou.connect(self.viewport().update)

    def altura_total(self) -> int:
        return 34 + self.model().rowCount() * ALTURA_LINHA

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


# ---- ajudantes de montagem -----------------------------------------------
def rotulo(texto: str, nome: str) -> QLabel:
    label = QLabel(texto)
    label.setObjectName(nome)
    return label


def valor(texto: str) -> QLabel:
    vazio = texto in ("-", "", "Não informado", "Sem movimentação registrada")
    label = rotulo("—" if texto in ("-", "") else texto, "ValorVazio" if vazio else "Valor")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


def painel(titulo: str | None = None, nome: str = "Painel", direita: QWidget | None = None, esquerda: QWidget | None = None) -> tuple[QFrame, QVBoxLayout]:
    quadro = QFrame()
    quadro.setObjectName(nome)
    coluna = QVBoxLayout(quadro)
    coluna.setContentsMargins(16, 14, 16, 14)
    coluna.setSpacing(10)
    if titulo:
        topo = QHBoxLayout()
        topo.setSpacing(10)
        if esquerda:
            topo.addWidget(esquerda)
        topo.addWidget(rotulo(titulo, "PainelTitulo"))
        topo.addStretch(1)
        if direita:
            topo.addWidget(direita)
        coluna.addLayout(topo)
    return quadro, coluna


def grade_kv(pares: list[tuple[str, str | QWidget]], largura_chave: int = 168) -> QGridLayout:
    """Chave a esquerda e valor a direita, como hoje."""
    grade = QGridLayout()
    grade.setHorizontalSpacing(12)
    grade.setVerticalSpacing(8)
    for linha, (chave, conteudo) in enumerate(pares):
        grade.addWidget(rotulo(chave, "Chave"), linha, 0, Qt.AlignTop)
        if isinstance(conteudo, QWidget):
            grade.addWidget(conteudo, linha, 1, Qt.AlignLeft | Qt.AlignVCenter)
        elif isinstance(conteudo, QVBoxLayout):
            grade.addLayout(conteudo, linha, 1)
        else:
            grade.addWidget(valor(conteudo), linha, 1)
    grade.setColumnMinimumWidth(0, largura_chave)
    grade.setColumnStretch(1, 1)
    return grade


def grade_blocos(pares: list[tuple[str, str]], colunas: int = 3) -> QGridLayout:
    """Chave em cima e valor embaixo, em varias colunas - para grupos de numeros."""
    grade = QGridLayout()
    grade.setHorizontalSpacing(24)
    grade.setVerticalSpacing(12)
    for indice, (chave, conteudo) in enumerate(pares):
        bloco = QVBoxLayout()
        bloco.setSpacing(2)
        bloco.addWidget(rotulo(chave, "Chave"))
        bloco.addWidget(valor(conteudo))
        grade.addLayout(bloco, indice // colunas, indice % colunas)
    for coluna in range(colunas):
        grade.setColumnStretch(coluna, 1)
    return grade


def moldura_tabela(tabela: TabelaSimples, altura_fixa: bool = False) -> QFrame:
    quadro = QFrame()
    quadro.setObjectName("TabelaMoldura")
    coluna = QVBoxLayout(quadro)
    coluna.setContentsMargins(1, 1, 1, 6)
    coluna.addWidget(tabela)
    if altura_fixa:
        tabela.setFixedHeight(tabela.altura_total())
        tabela.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    return quadro


def rolagem(conteudo: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    conteudo.setObjectName("Rolagem")
    area.setWidget(conteudo)
    return area


def indicador(numero: str, legenda: str) -> QVBoxLayout:
    bloco = QVBoxLayout()
    bloco.setSpacing(0)
    bloco.addWidget(rotulo(numero, "Numero"))
    bloco.addWidget(rotulo(legenda, "Chave"))
    return bloco


def estilo_extra() -> str:
    t = TEMA.t
    borda_azul = mix(QColor(t["border"]), QColor(t["accent"]), 0.5).name()
    return f"""
    QFrame#Dialogo {{ background: {t['bg']}; border: 1px solid {t['border']}; border-radius: 16px; }}
    QFrame#Painel {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 14px; }}
    QFrame#PainelAzul {{ background: {t['surface_alt']}; border: 1px solid {borda_azul}; border-radius: 14px; }}
    QFrame#Nota {{ background: {t['surface_alt']}; border: 0; border-radius: 10px; }}
    QFrame#TabelaMoldura {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 12px; }}
    QLabel#DTitulo {{ font-size: 18px; font-weight: 800; }}
    QLabel#PainelTitulo {{ font-size: 14px; font-weight: 700; }}
    QLabel#Chave {{ color: {t['muted']}; font-size: 12px; }}
    QLabel#Valor {{ font-weight: 600; }}
    QLabel#ValorVazio {{ color: {t['subtle']}; }}
    QLabel#Numero {{ font-size: 20px; font-weight: 700; }}
    QScrollArea {{ background: transparent; border: 0; }}
    QWidget#Rolagem {{ background: transparent; }}
    QTableView#Simples QHeaderView::section:first {{ border-top-left-radius: 11px; }}
    QTableView#Simples QHeaderView::section:last {{ border-top-right-radius: 11px; }}
    """


# --------------------------------------------------------------------------
# A tela
# --------------------------------------------------------------------------
class Detalhes(QFrame):
    fechar = Signal()

    def __init__(self, parent: QWidget, aba: int = 0):
        super().__init__(parent)
        self.setObjectName("Dialogo")
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(16, 14, 16, 14)
        raiz.setSpacing(10)
        raiz.addWidget(self._cabecalho())

        self.abas = Abas([("Resumo", None), ("Itens", len(ITENS)), ("Fluxo", None), ("Cargas", len(CARGAS)), ("Fiscal/Entrega", None), ("Histórico", len(HISTORICO))])
        self.abas.mudou.connect(self._trocar)
        self.esqueleto = Esqueleto()
        corpo = QWidget()
        coluna = QVBoxLayout(corpo)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(12)
        coluna.addWidget(self.abas)
        paginas = QWidget()
        self.paginas = QStackedLayout(paginas)
        self.paginas.setContentsMargins(0, 0, 0, 0)
        for pagina in (self._resumo(), self._itens(), self._fluxo(), self._cargas(), self._fiscal(), self._historico()):
            self.paginas.addWidget(pagina)
        coluna.addWidget(paginas, 1)
        miolo = QWidget()
        self.pilha = QStackedLayout(miolo)
        self.pilha.setContentsMargins(0, 0, 0, 0)
        self.pilha.addWidget(self.esqueleto)
        self.pilha.addWidget(corpo)
        self._corpo = corpo
        raiz.addWidget(miolo, 1)

        TEMA.mudou.connect(self._tema)
        self._tema()
        self.abas.selecionar(aba, animado=False)
        if base.ANIMAR:
            QTimer.singleShot(480, self._carregado)
        else:
            self.pilha.setCurrentWidget(corpo)

    def _tema(self) -> None:
        self.setStyleSheet(estilo_extra())

    def _carregado(self) -> None:
        self.pilha.setCurrentWidget(self._corpo)
        aparecer(self._corpo)

    def _trocar(self, indice: int) -> None:
        self.paginas.setCurrentIndex(indice)
        if self.pilha.currentWidget() is self._corpo:
            aparecer(self.paginas.currentWidget(), 160)

    def mousePressEvent(self, e):
        e.accept()

    # ---- cabecalho -------------------------------------------------------
    def _cabecalho(self) -> QFrame:
        quadro = QFrame()
        quadro.setObjectName("Painel")
        linha = QHBoxLayout(quadro)
        linha.setContentsMargins(18, 12, 14, 12)
        linha.setSpacing(8)
        titulos = QVBoxLayout()
        titulos.setSpacing(3)
        titulos.addWidget(rotulo(PROPOSTA["titulo"], "DTitulo"))
        titulos.addWidget(rotulo(PROPOSTA["obra"], "Sub"))
        situacao = QHBoxLayout()
        situacao.setSpacing(14)
        situacao.addWidget(Selo(*PROPOSTA["etapa"]))
        situacao.addWidget(PrazoInfo(PRAZO_DIAS))
        situacao.addStretch(1)
        titulos.addSpacing(3)
        titulos.addLayout(situacao)
        linha.addLayout(titulos, 1)
        fechar = Botao("Fechar", "x", "fantasma")
        fechar.clicked.connect(self.fechar)
        for botao in (Botao("Editar", "pencil"), Botao("Ações", "workflow", "primario"), fechar):
            linha.addWidget(botao, 0, Qt.AlignVCenter)
        return quadro

    # ---- Resumo ----------------------------------------------------------
    def _resumo(self) -> QWidget:
        conteudo = QWidget()
        coluna = QVBoxLayout(conteudo)
        coluna.setContentsMargins(0, 0, 8, 8)
        coluna.setSpacing(12)

        fluxo, fluxo_col = painel("Fluxo da proposta", "PainelAzul")
        fluxo_col.addWidget(Trilha(PASSOS))
        coluna.addWidget(fluxo)

        lado = QHBoxLayout()
        lado.setSpacing(12)
        dados, dados_col = painel("Dados da proposta")
        dados_col.addLayout(grade_kv(DADOS))
        dados_col.addStretch(1)
        situacao, situacao_col = painel("Situação atual")
        peso = QVBoxLayout()
        peso.setSpacing(5)
        peso.addWidget(valor("1.240,00 / 3.812,40 kg entregues (33%)"))
        peso.addWidget(Barra(0.33))
        situacao_col.addLayout(
            grade_kv(
                [
                    ("Etapa atual", Selo("Produção - Em produção", "location_production")),
                    ("Situação do fluxo", "Fluxo definido"),
                    ("Quantidade de itens", "148"),
                    ("Peso total", "3.812,40 kg"),
                    ("Peso / saldo", peso),
                    ("Peso parcial", "1.240,00 kg"),
                    ("Saldo pendente", "2.572,40 kg"),
                    ("Atualizado por", "marcos.s"),
                    ("Atualizado em", dia(-1, "14:12")),
                ]
            )
        )
        situacao_col.addStretch(1)
        lado.addWidget(dados, 1)
        lado.addWidget(situacao, 1)
        coluna.addLayout(lado)

        vinculos, vinculos_col = painel("Vínculos")
        linha = QHBoxLayout()
        linha.setSpacing(28)
        linha.addLayout(indicador("1", "Parcial vinculada"))
        ver_itens = Botao("Ver itens", "list", "fantasma")
        ver_itens.clicked.connect(lambda: self.abas.selecionar(1))
        linha.addWidget(ver_itens)
        linha.addSpacing(20)
        linha.addLayout(indicador(str(len(CARGAS)), "Cargas de galvanização vinculadas"))
        ver_cargas = Botao("Ver cargas", "truck", "fantasma")
        ver_cargas.clicked.connect(lambda: self.abas.selecionar(3))
        linha.addWidget(ver_cargas)
        linha.addStretch(1)
        vinculos_col.addLayout(linha)
        coluna.addWidget(vinculos)
        coluna.addStretch(1)
        return rolagem(conteudo)

    # ---- Itens -----------------------------------------------------------
    def _itens(self) -> QWidget:
        pagina = QWidget()
        coluna = QVBoxLayout(pagina)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(12)
        resumo, resumo_col = painel()
        linha = QHBoxLayout()
        linha.setSpacing(44)
        for numero, legenda in (("12", "linhas"), ("148", "unidades"), ("3.812,40 kg", "peso conhecido"), ("11/12", "itens com peso informado")):
            linha.addLayout(indicador(numero, legenda))
        linha.addStretch(1)
        resumo_col.addLayout(linha)
        coluna.addWidget(resumo)
        tabela = TabelaSimples(
            [("Item", 64, "centro"), ("Código", 120, "forte"), ("Descrição", 0, "texto"), ("Qtd.", 72, "num"), ("Peso unit.", 130, "num"), ("Situação", 300, "selo")],
            ITENS,
        )
        coluna.addWidget(moldura_tabela(tabela), 1)
        return pagina

    # ---- Fluxo -----------------------------------------------------------
    def _fluxo(self) -> QWidget:
        conteudo = QWidget()
        grade = QGridLayout(conteudo)
        grade.setContentsMargins(0, 0, 8, 8)
        grade.setHorizontalSpacing(12)
        grade.setVerticalSpacing(12)
        for indice, (area, icone_nome, status, campos) in enumerate(AREAS_FLUXO):
            quadro, coluna = painel(area, direita=Selo(*status), esquerda=ChipIcone(icone_nome, status[1]))
            coluna.addLayout(grade_blocos(campos, 3))
            coluna.addStretch(1)
            grade.addWidget(quadro, indice // 2, indice % 2)
        grade.setColumnStretch(0, 1)
        grade.setColumnStretch(1, 1)
        grade.setRowStretch(3, 1)
        return rolagem(conteudo)

    # ---- Cargas ----------------------------------------------------------
    def _cargas(self) -> QWidget:
        pagina = QWidget()
        coluna = QVBoxLayout(pagina)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(12)
        tabela = TabelaSimples(
            [("Carga", 110, "forte"), ("Situação", 250, "selo"), ("Envio", 116, "centro"), ("Retorno", 116, "centro"),
             ("Motorista", 150, "texto"), ("Itens", 70, "num"), ("Propostas", 100, "num"), ("Observações", 0, "texto")],
            CARGAS,
            selecionavel=True,
        )
        abrir = Botao("Abrir carga selecionada", "package-open")
        abrir.setEnabled(False)
        tabela.selectionModel().selectionChanged.connect(lambda *_: abrir.setEnabled(tabela.selectionModel().hasSelection()))
        resumo, resumo_col = painel()
        linha = QHBoxLayout()
        linha.setSpacing(44)
        for numero, legenda in ((str(len(CARGAS)), "cargas vinculadas"), ("1", "retornou"), ("1", "em galvanização")):
            linha.addLayout(indicador(numero, legenda))
        linha.addStretch(1)
        linha.addWidget(abrir, 0, Qt.AlignVCenter)
        resumo_col.addLayout(linha)
        coluna.addWidget(resumo)
        coluna.addWidget(moldura_tabela(tabela), 1)
        return pagina

    # ---- Fiscal/Entrega --------------------------------------------------
    def _fiscal(self) -> QWidget:
        conteudo = QWidget()
        coluna = QVBoxLayout(conteudo)
        coluna.setContentsMargins(0, 0, 8, 8)
        coluna.setSpacing(12)

        fiscal, fiscal_col = painel("Fiscal", direita=Selo("NF parcial", "attention"), esquerda=ChipIcone("receipt-text", "attention"))
        fiscal_col.addLayout(
            grade_blocos(
                [
                    ("Entrada fiscal", dia(-5)), ("Última emissão", dia(-1)), ("Quantidade de itens", "148"),
                    ("Itens faturados", "64"), ("Itens pendentes", "84"), ("Peso total", "3.812,40 kg"),
                    ("Peso faturado", "1.465,00 kg"), ("Peso pendente", "2.347,40 kg"),
                ],
                4,
            )
        )
        progresso = QVBoxLayout()
        progresso.setSpacing(5)
        progresso.addWidget(rotulo("64 de 148 itens faturados (43%)", "Chave"))
        progresso.addWidget(Barra(0.43))
        fiscal_col.addLayout(progresso)
        fiscal_col.addSpacing(4)
        fiscal_col.addWidget(rotulo("Notas fiscais emitidas", "PainelTitulo"))
        notas = TabelaSimples(
            [("Número/Controle", 0, "forte"), ("Série", 90, "centro"), ("Emissão", 140, "centro"), ("Qtd. emitida", 140, "num"), ("Peso emitido", 160, "num")],
            NOTAS,
        )
        fiscal_col.addWidget(moldura_tabela(notas, altura_fixa=True))
        coluna.addWidget(fiscal)

        entrega, entrega_col = painel("Entrega", direita=Selo("Entregue parcial", "location_expedition"), esquerda=ChipIcone("truck", "location_expedition"))
        entrega_col.addLayout(
            grade_blocos(
                [("Quantidade entregue", "52"), ("Saldo pendente", "96"), ("Última movimentação de entrega", f"{dia(-1, '14:12')} (marcos.s)")],
                4,
            )
        )
        nota = QFrame()
        nota.setObjectName("Nota")
        nota_linha = QHBoxLayout(nota)
        nota_linha.setContentsMargins(12, 9, 12, 9)
        nota_linha.setSpacing(10)
        nota_linha.addWidget(ChipIcone("info", "waiting"), 0, Qt.AlignTop)
        texto = rotulo(
            "Transportadora, motorista e placa não são registrados para a entrega ao cliente neste sistema. "
            "Esses dados existem apenas para o transporte de envio e retorno de galvanização (aba \"Cargas\").",
            "Sub",
        )
        texto.setWordWrap(True)
        nota_linha.addWidget(texto, 1)
        entrega_col.addWidget(nota)
        coluna.addWidget(entrega)
        coluna.addStretch(1)
        return rolagem(conteudo)

    # ---- Historico -------------------------------------------------------
    def _historico(self) -> QWidget:
        pagina = QWidget()
        coluna = QVBoxLayout(pagina)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(8)
        coluna.addWidget(rotulo(f"{len(HISTORICO)} movimentações registradas, da mais recente para a mais antiga", "Legenda"))
        tabela = TabelaSimples(
            [("Área", 160, "area"), ("Anterior", 210, "mudo"), ("Novo", 230, "selo"), ("Quando", 150, "centro"), ("Usuário", 120, "texto"), ("Observação", 0, "texto")],
            HISTORICO,
        )
        coluna.addWidget(moldura_tabela(tabela), 1)
        return pagina


class Veu(QWidget):
    """Escurece a tela de tras e segura os detalhes por cima, como um dialogo modal."""

    def __init__(self, pagina: QWidget):
        super().__init__(pagina)
        self._a = 0.0
        self.dialogo: Detalhes | None = None
        self.setFocusPolicy(Qt.StrongFocus)
        self.hide()
        pagina.installEventFilter(self)

    def eventFilter(self, objeto, evento):
        if evento.type() == QEvent.Resize and objeto is self.parent():
            self._posicionar()
        return False

    def _posicionar(self) -> None:
        self.setGeometry(self.parent().rect())
        if self.dialogo:
            self.dialogo.setGeometry(self.rect().adjusted(42, 26, -42, -26))

    def abrir(self, dialogo: Detalhes) -> None:
        if self.dialogo:
            self.dialogo.deleteLater()
        self.dialogo = dialogo
        dialogo.fechar.connect(self.fechar)
        self._posicionar()
        self.show()
        self.raise_()
        dialogo.show()
        self.setFocus()
        self._a = 0.0
        animar(self, "_a", 1.0, 200)
        aparecer(dialogo, 220)

    def fechar(self) -> None:
        self.hide()
        if self.dialogo:
            self.dialogo.deleteLater()
            self.dialogo = None

    def mousePressEvent(self, e):
        self.fechar()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.fechar()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(8, 15, 30, int((150 if TEMA.nome == "escuro" else 105) * self._a)))
        if self.dialogo:
            alvo = QRectF(self.dialogo.geometry())
            p.setPen(Qt.NoPen)
            for i in range(1, 9):
                p.setBrush(QColor(8, 15, 30, int(7 * self._a)))
                p.drawRoundedRect(alvo.adjusted(-i * 2, -i * 2 + 4, i * 2, i * 2 + 4), 16 + i * 2, 16 + i * 2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tema", choices=("claro", "escuro"), default="claro")
    parser.add_argument("--aba", type=int, choices=range(6), default=0)
    parser.add_argument("--sem-animacao", action="store_true")
    parser.add_argument("--shot", metavar="ARQUIVO.png")
    args = parser.parse_args()

    app = QApplication(sys.argv[:1])
    base.ANIMAR = not (args.sem_animacao or args.shot)
    base.FAMILIA = base.carregar_fonte()
    TEMA.nome = args.tema
    pagina = base.Pagina()
    pagina.setWindowTitle("Protótipo - Detalhes da proposta (dados fictícios)")
    pagina.resize(1366, 740)
    pagina.tabela.selectRow(3)
    pagina.show()
    veu = Veu(pagina)

    def abrir(aba: int = 0) -> None:
        veu.abrir(Detalhes(veu, aba))

    pagina.tabela.doubleClicked.connect(lambda *_: abrir())
    QTimer.singleShot(0 if args.shot else 300, lambda: abrir(args.aba))
    if args.shot:
        def fotografar():
            pagina.grab().save(args.shot)
            print(f"fonte={base.FAMILIA} salvo={args.shot}")
            app.quit()

        QTimer.singleShot(600, fotografar)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
