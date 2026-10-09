"""SIMULADOR ISOLADO do remanejamento parcial (prototipo para o Henrique testar na pratica).

Nao importa nada de `app/` nem de `api/`, nao fala com a API nem com banco: os dados sao ficticios e
tudo acontece em memoria. O unico arquivo do projeto que ele le (somente leitura) sao os SVGs Lucide em
`app/assets/icons/lucide/` e as fontes Inter em `app/assets/fonts/`.

Serve para comparar, com o MESMO cenario, o remanejamento "como e hoje" (a proposta continua uma so,
misturada) com o "como proposto" (a proposta se divide em P1, P2... pela logica de parciais que o
sistema ja tem). Plano: docs/architecture/REMANEJAMENTO_PARCIAIS_PLANO.md.

Uso:
    python prototipos/remanejamento_parciais/simulador.py
    python prototipos/remanejamento_parciais/simulador.py --cenario 2 --modo hoje
    python prototipos/remanejamento_parciais/simulador.py --tema escuro
    python prototipos/remanejamento_parciais/simulador.py --shot saida.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QIcon, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSpinBox, QSplitter, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import modelo as m  # noqa: E402

LUCIDE = AQUI.parents[1] / "app" / "assets" / "icons" / "lucide"
FONTES = AQUI.parents[1] / "app" / "assets" / "fonts"

TEMAS = {
    "claro": {
        "chrome": "#CBD8EF", "bg": "#F5F7FB", "surface": "#FFFFFF", "surface_alt": "#E8F1FF", "zebra": "#EEF4FE",
        "header": "#DBEAFE", "selected": "#BFDBFE", "text": "#0F172A", "muted": "#475569", "border": "#DCE3EE",
        "input_border": "#8391A6", "accent": "#006FC9", "accent_hover": "#005AA3", "accent_text": "#FFFFFF",
        "danger": "#B91C1C", "ok": "#047857", "warn": "#A2500A", "badge_text": "#FFFFFF",
        "producao": "#047857", "galvanizacao": "#7C3AED", "expedicao": "#C2410C", "entregue": "#0F766E", "referencia": "#64748B",
    },
    "escuro": {
        "chrome": "#0A1020", "bg": "#0F172A", "surface": "#172033", "surface_alt": "#22304A", "zebra": "#1C2740",
        "header": "#24324A", "selected": "#0E5E78", "text": "#F8FAFC", "muted": "#CBD5E1", "border": "#2C3B56",
        "input_border": "#6B7C95", "accent": "#38BDF8", "accent_hover": "#7DD3FC", "accent_text": "#0F172A",
        "danger": "#FB7185", "ok": "#34D399", "warn": "#FACC15", "badge_text": "#0F172A",
        "producao": "#34D399", "galvanizacao": "#A78BFA", "expedicao": "#FB923C", "entregue": "#2DD4BF", "referencia": "#CBD5E1",
    },
}
T: dict = dict(TEMAS["claro"])
FAMILIA = "Segoe UI"

ROLE_ID = Qt.UserRole
ROLE_MARCA = Qt.UserRole + 1
ROLE_SELOS = Qt.UserRole + 2


def fonte(px: int = 13, peso: int = 400) -> QFont:
    f = QFont(FAMILIA)
    f.setPixelSize(px)
    f.setWeight(QFont.Weight(peso))
    return f


def carregar_fontes() -> None:
    global FAMILIA
    if FONTES.exists():
        for arquivo in sorted(FONTES.glob("Inter-*.ttf")):
            QFontDatabase.addApplicationFont(str(arquivo))
        if "Inter" in QFontDatabase.families():
            FAMILIA = "Inter"


def icone_svg(nome: str, cor: str, tamanho: int) -> QPixmap:
    arquivo = LUCIDE / f"{nome}.svg"
    pix = QPixmap(tamanho * 2, tamanho * 2)
    pix.fill(Qt.transparent)
    if arquivo.exists():
        texto = arquivo.read_text(encoding="utf-8").replace("currentColor", cor)
        p = QPainter(pix)
        QSvgRenderer(QByteArray(texto.encode("utf-8"))).render(p, QRectF(0, 0, tamanho * 2, tamanho * 2))
        p.end()
    pix.setDevicePixelRatio(2)
    return pix


def folha() -> str:
    return f"""
    QWidget {{ background: {T['bg']}; color: {T['text']}; font-family: '{FAMILIA}'; font-size: 13px; }}
    QFrame#Cartao {{ background: {T['surface']}; border: 1px solid {T['border']}; border-radius: 14px; }}
    QLabel#Titulo {{ font-size: 18px; font-weight: 800; background: transparent; }}
    QLabel#Sub {{ color: {T['muted']}; background: transparent; }}
    QLabel#Chave {{ color: {T['muted']}; font-size: 12px; background: transparent; }}
    QLabel#Ok {{ color: {T['ok']}; font-weight: 700; background: transparent; }}
    QLabel#Alerta {{ color: {T['danger']}; font-weight: 700; background: transparent; }}
    QTabWidget::pane {{ border: 1px solid {T['border']}; border-radius: 10px; background: {T['surface']}; top: -1px; }}
    QTabBar::tab {{ background: {T['bg']}; color: {T['muted']}; padding: 8px 16px; border: 1px solid {T['border']};
        border-bottom: none; border-top-left-radius: 10px; border-top-right-radius: 10px; margin-right: 3px; }}
    QTabBar::tab:selected {{ background: {T['surface']}; color: {T['text']}; font-weight: 700; }}
    QTreeWidget::item {{ padding: 5px 4px; }}
    QListWidget::item {{ padding: 6px 6px; }}
    QTableWidget, QTreeWidget, QListWidget {{ background: {T['surface']}; alternate-background-color: {T['zebra']};
        border: none; gridline-color: transparent; selection-background-color: {T['selected']}; selection-color: {T['text']}; }}
    QHeaderView::section {{ background: {T['header']}; color: {T['text']}; font-weight: 700; border: none; padding: 7px 8px; }}
    QPushButton {{ background: {T['surface_alt']}; color: {T['text']}; border: 1px solid {T['border']}; border-radius: 10px; padding: 7px 14px; font-weight: 600; }}
    QPushButton:hover {{ border-color: {T['accent']}; }}
    QPushButton:disabled {{ color: {T['muted']}; background: {T['bg']}; }}
    QPushButton#Primario {{ background: {T['accent']}; color: {T['accent_text']}; border: none; }}
    QPushButton#Primario:hover {{ background: {T['accent_hover']}; }}
    QPushButton#Primario:disabled {{ background: {T['border']}; color: {T['muted']}; }}
    QPushButton#Fantasma {{ background: transparent; border: none; }}
    QPushButton#Modo {{ background: {T['surface']}; border: 1px solid {T['input_border']}; padding: 7px 16px; }}
    QPushButton#Modo:checked {{ background: {T['accent']}; color: {T['accent_text']}; border-color: {T['accent']}; }}
    QComboBox, QSpinBox {{ background: {T['surface']}; border: 1px solid {T['input_border']}; border-radius: 10px; padding: 5px 10px; min-height: 22px; }}
    QTextBrowser {{ background: {T['surface']}; border: 1px solid {T['border']}; border-radius: 10px; padding: 6px; }}
    """


# --------------------------------------------------------------------------------------------------
# Tabela com selos e a marca de remanejamento (icone + codigo vermelho, clicavel)
# --------------------------------------------------------------------------------------------------
ICONE_MARCA = 14
FOLGA_MARCA = 6


def geometria_marca(rect: QRectF, texto: str, f: QFont) -> tuple[QRectF, QRectF]:
    metricas = QFontMetricsF(f)
    disponivel = max(0.0, rect.width() - 12 - ICONE_MARCA - FOLGA_MARCA)
    largura = metricas.horizontalAdvance(metricas.elidedText(texto, Qt.ElideRight, disponivel))
    bloco = ICONE_MARCA + FOLGA_MARCA + largura
    x = rect.x() + max(6.0, (rect.width() - bloco) / 2)
    icone = QRectF(x, rect.center().y() - ICONE_MARCA / 2, ICONE_MARCA, ICONE_MARCA)
    return icone, QRectF(icone.right() + FOLGA_MARCA, rect.y(), largura, rect.height())


def area_clicavel(rect: QRectF, texto: str, f: QFont) -> QRectF:
    icone, codigo = geometria_marca(rect, texto, f)
    return icone.united(codigo).adjusted(-4, -rect.height() / 2 + 8, 4, rect.height() / 2 - 8)


class Delegado(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        selos = index.data(ROLE_SELOS)
        marca = index.data(ROLE_MARCA)
        if not selos and not marca:
            super().paint(painter, option, index)
            return
        em_branco = QStyleOptionViewItem(option)
        self.initStyleOption(em_branco, index)
        em_branco.text = ""
        estilo = em_branco.widget.style() if em_branco.widget is not None else QApplication.style()
        estilo.drawControl(QStyle.CE_ItemViewItem, em_branco, painter, em_branco.widget)
        rect = QRectF(option.rect)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setClipRect(rect)
        if marca:
            f = fonte(13, 600)
            texto = str(index.data(Qt.DisplayRole) or "")
            icone, codigo = geometria_marca(rect, texto, f)
            painter.drawPixmap(int(icone.x()), int(icone.y()), icone_svg("refresh-cw", T["accent"], ICONE_MARCA))
            painter.setFont(f)
            painter.setPen(QPen(QColor(T["danger"])))
            visivel = QFontMetricsF(f).elidedText(texto, Qt.ElideRight, codigo.width() + 0.5)
            painter.drawText(codigo, Qt.AlignVCenter | Qt.AlignLeft, visivel)
        else:
            f = fonte(12, 600)
            metricas = QFontMetricsF(f)
            x = rect.x() + 8
            for texto, cor in selos:
                largura = metricas.horizontalAdvance(texto) + 20
                faixa = QRectF(x, rect.center().y() - 10, largura, 20)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(cor))
                painter.drawRoundedRect(faixa, 10, 10)
                painter.setFont(f)
                painter.setPen(QPen(QColor(T["badge_text"])))
                painter.drawText(faixa, Qt.AlignCenter, texto)
                x += largura + 6
        painter.restore()


class Tabela(QTableWidget):
    marca_clicada = Signal(int)

    def __init__(self, colunas: list[str], multi: bool = False, parent=None):
        super().__init__(0, len(colunas), parent)
        self.setHorizontalHeaderLabels(colunas)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(38)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection if multi else QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setItemDelegate(Delegado(self))
        self.setMouseTracking(True)

    def _sobre_marca(self, pos) -> QPointF | None:
        indice = self.indexAt(pos.toPoint())
        if not indice.isValid() or indice.column() != 0 or not indice.data(ROLE_MARCA):
            return None
        rect = QRectF(self.visualRect(indice))
        if area_clicavel(rect, str(indice.data(Qt.DisplayRole) or ""), fonte(13, 600)).contains(QPointF(pos)):
            return QPointF(pos)
        return None

    def mousePressEvent(self, evento):
        if self._sobre_marca(evento.position()) is not None:
            self.marca_clicada.emit(int(self.indexAt(evento.position().toPoint()).data(ROLE_ID)))
            return
        super().mousePressEvent(evento)

    def mouseMoveEvent(self, evento):
        self.setCursor(Qt.PointingHandCursor if self._sobre_marca(evento.position()) is not None else Qt.ArrowCursor)
        super().mouseMoveEvent(evento)

    def limpar(self) -> None:
        self.setRowCount(0)

    def adicionar(self, celulas: list[dict]) -> None:
        linha = self.rowCount()
        self.insertRow(linha)
        for coluna, celula in enumerate(celulas):
            item = QTableWidgetItem(str(celula.get("texto", "")))
            item.setTextAlignment(Qt.AlignCenter)
            if "id" in celula:
                item.setData(ROLE_ID, celula["id"])
            if celula.get("marca"):
                item.setData(ROLE_MARCA, True)
                item.setFont(fonte(13, 600))
            if celula.get("selos"):
                item.setData(ROLE_SELOS, celula["selos"])
            self.setItem(linha, coluna, item)


DICAS = {
    "1": (
        "Teste sugerido: clique em <b>Remanejar…</b>, escolha a <b>CP 05640</b>, o <b>item 3</b> e a origem <b>CP 05493</b>, "
        "adicione à lista e confirme. Depois olhe as abas Controle Geral, Produção, Expedição e Famílias. "
        "Em seguida use <b>Concluir produção</b> na parte que ficou em produção, <b>Enviar para galvanização</b> e "
        "<b>Retornar carga</b> para ver as partes se juntarem. Repita trocando para <b>Como é hoje</b>."
    ),
    "2": (
        "Teste sugerido: remaneje <b>5 un</b> do item 450.400 da <b>CP 05700</b> para a <b>CP 05710</b>. A CP 05710 tem peças em "
        "carga, aguardando carga e a fabricar na mesma linha: veja quais saem primeiro (as mais adiantadas) e como a CP 05700 se divide. "
        "Depois use <b>Retornar carga</b> e veja a parte da carga se juntar às prontas."
    ),
    "3": (
        "Teste sugerido: remaneje <b>os dois itens</b> da CP 05810 de uma vez (adicione os dois à lista). A CP 05800 cedeu tudo: "
        "não há o que dividir, ela inteira volta para a Produção e a CP 05810 vai inteira para a Expedição."
    ),
    "4": (
        "Cenário livre: quatro propostas com fluxos e situações diferentes (galvanizada pronta, simples pronta, em carga, em produção). "
        "Faça os remanejamentos que quiser, mande para a galvanização, retorne as cargas e entregue, nos dois modos."
    ),
}


def selo_lugar(lugar: str) -> tuple[str, str]:
    chave = {"Produção": "producao", "Galvanização": "galvanizacao", "Expedição": "expedicao", "Entregue": "entregue", "Referência": "referencia"}[lugar]
    return lugar, T[chave]


# --------------------------------------------------------------------------------------------------
# Dialogos
# --------------------------------------------------------------------------------------------------
class DialogoMarca(QDialog):
    def __init__(self, estado: m.Estado, proposta_id: int, parent=None):
        super().__init__(parent)
        proposta = estado.propostas[proposta_id]
        self.setWindowTitle(f"Remanejamento — {proposta.numero}")
        self.setMinimumWidth(560)
        camada = QVBoxLayout(self)
        titulo = QLabel(proposta.numero)
        titulo.setObjectName("Titulo")
        camada.addWidget(titulo)
        sub = QLabel(estado.situacao(proposta_id))
        sub.setObjectName("Sub")
        sub.setWordWrap(True)
        camada.addWidget(sub)
        texto = QTextBrowser()
        partes = ["<b>Para onde foram as peças</b><ul>"]
        partes += [f"<li>{linha}</li>" for linha in estado.detalhes_marca(proposta_id)] or ["<li>Sem detalhes.</li>"]
        partes.append("</ul><b>Como a família está agora</b><ul>")
        partes += [f"<li>{frase}</li>" for frase in estado.descrever_familia(estado.raiz_id(proposta_id))]
        partes.append("</ul>")
        texto.setHtml("".join(partes))
        camada.addWidget(texto)
        fechar = QPushButton("Fechar")
        fechar.setObjectName("Fantasma")
        fechar.clicked.connect(self.accept)
        linha = QHBoxLayout()
        linha.addStretch(1)
        linha.addWidget(fechar)
        camada.addLayout(linha)
        self.resize(600, 420)


class DialogoRemanejar(QDialog):
    """Monta a lista de itens a remanejar (como o assistente real) e mostra o resultado previsto."""

    def __init__(self, estado: m.Estado, parent=None):
        super().__init__(parent)
        self.estado = estado
        self.operacoes: list[tuple[int, int, int]] = []
        self.setWindowTitle("Remanejar")
        camada = QVBoxLayout(self)
        titulo = QLabel("Remanejar material pronto da Expedição")
        titulo.setObjectName("Titulo")
        camada.addWidget(titulo)
        modo = "COMO PROPOSTO (a proposta se divide em partes P1, P2...)" if estado.modo == m.PROPOSTO else "COMO É HOJE (a proposta continua uma só)"
        sub = QLabel(f"Modo do simulador: {modo}. Escolha quem recebe, o item e de quem vem o material; depois adicione à lista.")
        sub.setObjectName("Sub")
        sub.setWordWrap(True)
        camada.addWidget(sub)

        colunas = QHBoxLayout()
        self.lista_destino = QListWidget()
        self.tabela_item = Tabela(["Item", "Código", "A caminho", "Prontas"])
        self.tabela_origem = Tabela(["Origem", "Item", "Prontas"])
        for tabela in (self.tabela_item, self.tabela_origem):
            tabela.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for rotulo, widget, largura in (("1. Quem recebe (tem peças em andamento)", self.lista_destino, 260), ("2. Item que ela precisa", self.tabela_item, 360), ("3. De quem vem (prontas, mesmo produto)", self.tabela_origem, 360)):
            bloco = QVBoxLayout()
            nome = QLabel(rotulo)
            nome.setObjectName("Chave")
            bloco.addWidget(nome)
            widget.setMinimumWidth(largura)
            bloco.addWidget(widget)
            colunas.addLayout(bloco)
        camada.addLayout(colunas, 3)

        linha = QHBoxLayout()
        linha.addWidget(QLabel("Quantidade:"))
        self.quantidade = QSpinBox()
        self.quantidade.setMinimum(1)
        linha.addWidget(self.quantidade)
        self.adicionar = QPushButton("Adicionar à lista")
        self.remover = QPushButton("Remover da lista")
        linha.addWidget(self.adicionar)
        linha.addWidget(self.remover)
        linha.addStretch(1)
        camada.addLayout(linha)

        self.lista_ops = QListWidget()
        self.lista_ops.setMaximumHeight(80)
        camada.addWidget(self.lista_ops)
        rotulo = QLabel("Resultado previsto")
        rotulo.setObjectName("Chave")
        camada.addWidget(rotulo)
        self.previa = QTextBrowser()
        camada.addWidget(self.previa, 4)

        rodape = QHBoxLayout()
        rodape.addStretch(1)
        cancelar = QPushButton("Cancelar")
        cancelar.setObjectName("Fantasma")
        self.confirmar = QPushButton("Remanejar")
        self.confirmar.setObjectName("Primario")
        self.confirmar.setEnabled(False)
        rodape.addWidget(cancelar)
        rodape.addWidget(self.confirmar)
        camada.addLayout(rodape)

        cancelar.clicked.connect(self.reject)
        self.confirmar.clicked.connect(self.accept)
        self.adicionar.clicked.connect(self._adicionar)
        self.remover.clicked.connect(self._remover)
        self.lista_destino.currentRowChanged.connect(self._carregar_itens)
        self.tabela_item.itemSelectionChanged.connect(self._carregar_origens)
        self.tabela_origem.itemSelectionChanged.connect(self._limite)
        self._carregar_destinos()
        self.resize(1120, 780)

    def _carregar_destinos(self) -> None:
        self.lista_destino.clear()
        for proposta in self.estado.ativas():
            linhas = [l for l in self.estado.linhas_de(proposta.id) if l.em_andamento() > 0]
            if linhas:
                item = QListWidgetItem(f"{proposta.numero} — {proposta.cliente}")
                item.setData(ROLE_ID, proposta.id)
                self.lista_destino.addItem(item)
        if self.lista_destino.count():
            self.lista_destino.setCurrentRow(0)

    def _carregar_itens(self, _linha: int) -> None:
        self.tabela_item.limpar()
        self.tabela_origem.limpar()
        atual = self.lista_destino.currentItem()
        if atual is None:
            return
        for linha in self.estado.linhas_de(atual.data(ROLE_ID)):
            if linha.em_andamento() > 0:
                self.tabela_item.adicionar([
                    {"texto": linha.numero, "id": linha.id}, {"texto": linha.codigo}, {"texto": linha.em_andamento()}, {"texto": linha.pecas[m.PRONTA]},
                ])
        if self.tabela_item.rowCount():
            self.tabela_item.selectRow(0)

    def _linha_destino(self) -> int | None:
        linhas = self.tabela_item.selectionModel().selectedRows()
        return int(self.tabela_item.item(linhas[0].row(), 0).data(ROLE_ID)) if linhas else None

    def _linha_origem(self) -> int | None:
        linhas = self.tabela_origem.selectionModel().selectedRows()
        return int(self.tabela_origem.item(linhas[0].row(), 0).data(ROLE_ID)) if linhas else None

    def _carregar_origens(self) -> None:
        self.tabela_origem.limpar()
        destino = self._linha_destino()
        if destino is None:
            return
        for linha in self.estado.candidatas_origem(destino):
            self.tabela_origem.adicionar([
                {"texto": self.estado.propostas[linha.proposta_id].numero, "id": linha.id}, {"texto": linha.numero}, {"texto": linha.pecas[m.PRONTA]},
            ])
        if self.tabela_origem.rowCount():
            self.tabela_origem.selectRow(0)
        self._limite()

    def _limite(self) -> None:
        destino, origem = self._linha_destino(), self._linha_origem()
        maximo = 1
        if destino is not None and origem is not None:
            maximo = max(1, min(self.estado.linhas[origem].pecas[m.PRONTA], self.estado.linhas[destino].em_andamento()))
        self.quantidade.setMaximum(maximo)
        self.quantidade.setValue(maximo)

    def _adicionar(self) -> None:
        destino, origem = self._linha_destino(), self._linha_origem()
        if destino is None or origem is None:
            QMessageBox.information(self, "Remanejar", "Escolha o item que recebe e de quem vem o material.")
            return
        self.operacoes.append((destino, origem, self.quantidade.value()))
        self._atualizar_lista()

    def _remover(self) -> None:
        linha = self.lista_ops.currentRow()
        if 0 <= linha < len(self.operacoes):
            del self.operacoes[linha]
            self._atualizar_lista()

    def _atualizar_lista(self) -> None:
        self.lista_ops.clear()
        for destino, origem, qtd in self.operacoes:
            d, o = self.estado.linhas[destino], self.estado.linhas[origem]
            self.lista_ops.addItem(f"{qtd} un de {o.codigo}: {self.estado.propostas[o.proposta_id].numero} (item {o.numero}) → {self.estado.propostas[d.proposta_id].numero} (item {d.numero})")
        self._prever()

    def _prever(self) -> None:
        self.confirmar.setEnabled(False)
        if not self.operacoes:
            self.previa.setHtml("<i>Adicione ao menos um item à lista para ver o resultado previsto.</i>")
            return
        copia = self.estado.copia()
        antes = len(copia.log)
        try:
            copia.remanejar_lote(self.operacoes)
        except m.ErroSimulacao as erro:
            self.previa.setHtml(f"<span style='color:{T['danger']}'><b>Não dá para remanejar assim:</b> {erro}</span>")
            return
        raizes = []
        for destino, origem, _qtd in self.operacoes:
            for linha_id in (origem, destino):
                raiz = self.estado.raiz_id(self.estado.linhas[linha_id].proposta_id)
                if raiz not in raizes:
                    raizes.append(raiz)
        partes = ["<b>O que acontece</b><ul>"] + [f"<li>{texto}</li>" for texto in copia.log[antes:]] + ["</ul><b>Como ficam as propostas</b><ul>"]
        for raiz in raizes:
            partes += [f"<li>{frase}</li>" for frase in copia.descrever_familia(raiz)]
        partes.append("</ul>")
        problemas = copia.conferir()
        partes.append("<span style='color:%s'>✓ Conferência: nenhuma peça nasceu ou sumiu.</span>" % T["ok"] if not problemas else "<span style='color:%s'>⚠ %s</span>" % (T["danger"], "; ".join(problemas)))
        self.previa.setHtml("".join(partes))
        self.confirmar.setEnabled(True)


# --------------------------------------------------------------------------------------------------
# Janela principal
# --------------------------------------------------------------------------------------------------
class Janela(QWidget):
    def __init__(self, cenario: str, modo: str):
        super().__init__()
        self.setWindowTitle("Simulador — remanejamento parcial (protótipo, dados fictícios)")
        self.cenario = cenario
        self.estado = m.montar_cenario(cenario, modo)
        self.historico: list[m.Estado] = []
        self.sel_id: int | None = None
        self._montar()
        self.reiniciar(cenario)

    # ---- montagem -----------------------------------------------------------------------------------
    def _montar(self) -> None:
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(16, 14, 16, 14)
        raiz.setSpacing(10)

        topo = QFrame()
        topo.setObjectName("Cartao")
        linha = QHBoxLayout(topo)
        linha.setContentsMargins(18, 12, 14, 12)
        textos = QVBoxLayout()
        titulo = QLabel("Simulador do remanejamento parcial")
        titulo.setObjectName("Titulo")
        sub = QLabel("Protótipo isolado: nada aqui toca no sistema, na API ou no banco. Compare o mesmo cenário nos dois modos.")
        sub.setObjectName("Sub")
        textos.addWidget(titulo)
        textos.addWidget(sub)
        linha.addLayout(textos, 1)
        self.botao_hoje = QPushButton("Como é hoje")
        self.botao_proposto = QPushButton("Como proposto")
        for botao in (self.botao_hoje, self.botao_proposto):
            botao.setObjectName("Modo")
            botao.setCheckable(True)
        grupo = QButtonGroup(self)
        grupo.setExclusive(True)
        grupo.addButton(self.botao_hoje)
        grupo.addButton(self.botao_proposto)
        (self.botao_proposto if self.estado.modo == m.PROPOSTO else self.botao_hoje).setChecked(True)
        self.botao_hoje.clicked.connect(lambda: self.trocar_modo(m.HOJE))
        self.botao_proposto.clicked.connect(lambda: self.trocar_modo(m.PROPOSTO))
        linha.addWidget(self.botao_hoje)
        linha.addWidget(self.botao_proposto)
        self.combo_cenario = QComboBox()
        for chave, nome in m.CENARIOS.items():
            self.combo_cenario.addItem(f"{chave}. {nome}", chave)
        self.combo_cenario.setCurrentIndex(list(m.CENARIOS).index(self.cenario))
        self.combo_cenario.activated.connect(lambda _i: self.reiniciar(self.combo_cenario.currentData()))
        linha.addWidget(self.combo_cenario)
        self.check_destino = QCheckBox("Destino também por lugar")
        self.check_destino.setToolTip("Variante para testar: o destino também se divide em uma parte por lugar (como a origem), em vez de só o que chegou pronto virar parte e o resto continuar na proposta.")
        self.check_destino.toggled.connect(self._trocar_destino)
        linha.addWidget(self.check_destino)
        self.botao_reiniciar = QPushButton("Reiniciar cenário")
        self.botao_reiniciar.clicked.connect(lambda: self.reiniciar(self.cenario))
        self.botao_desfazer = QPushButton("Desfazer")
        self.botao_desfazer.clicked.connect(self.desfazer)
        linha.addWidget(self.botao_reiniciar)
        linha.addWidget(self.botao_desfazer)
        raiz.addWidget(topo)

        self.conferencia = QLabel()
        raiz.addWidget(self.conferencia)

        acoes = QHBoxLayout()
        self.botao_remanejar = QPushButton("Remanejar…")
        self.botao_remanejar.setObjectName("Primario")
        self.botao_remanejar.clicked.connect(self.acao_remanejar)
        acoes.addWidget(self.botao_remanejar)
        separador = QLabel("  Na proposta selecionada:")
        separador.setObjectName("Chave")
        acoes.addWidget(separador)
        self.botao_concluir = QPushButton("Concluir produção")
        self.botao_concluir.clicked.connect(self.acao_concluir)
        self.botao_enviar = QPushButton("Enviar para galvanização")
        self.botao_enviar.clicked.connect(self.acao_enviar)
        self.combo_carga = QComboBox()
        self.botao_retornar = QPushButton("Retornar carga")
        self.botao_retornar.clicked.connect(self.acao_retornar)
        self.botao_entregar = QPushButton("Entregar")
        self.botao_entregar.clicked.connect(self.acao_entregar)
        self.so_item = QCheckBox("só o item selecionado abaixo")
        for widget in (self.botao_concluir, self.botao_enviar, self.combo_carga, self.botao_retornar, self.botao_entregar, self.so_item):
            acoes.addWidget(widget)
        acoes.addStretch(1)
        raiz.addLayout(acoes)

        divisor = QSplitter(Qt.Horizontal)
        esquerda = QWidget()
        coluna = QVBoxLayout(esquerda)
        coluna.setContentsMargins(0, 0, 0, 0)
        self.abas = QTabWidget()
        self.t_geral = Tabela(["Proposta", "Cliente", "Aparece em", "Situação"])
        self.t_producao = Tabela(["Proposta", "Cliente", "A fabricar (un)", "Itens"])
        self.t_galv = Tabela(["Proposta", "Cliente", "Aguardando carga", "Em carga", "Cargas"], multi=True)
        self.t_exp = Tabela(["Proposta", "Cliente", "Prontas (un)", "Entregues (un)"])
        self.arvore = QTreeWidget()
        self.arvore.setHeaderLabels(["Família", "Onde está", "Itens"])
        self.arvore.setAlternatingRowColors(True)
        self.arvore.setColumnWidth(0, 230)
        self.arvore.setColumnWidth(1, 220)
        for tabela, nome in ((self.t_geral, "Controle Geral"), (self.t_producao, "Produção"), (self.t_galv, "Galvanização"), (self.t_exp, "Expedição")):
            self.abas.addTab(tabela, nome)
            tabela.itemSelectionChanged.connect(self._selecionou)
            tabela.marca_clicada.connect(self.mostrar_marca)
            tabela.horizontalHeader().resizeSection(0, 170)
            tabela.horizontalHeader().resizeSection(1, 190)
        self.t_geral.horizontalHeader().resizeSection(2, 260)
        self.abas.addTab(self.arvore, "Famílias (parciais)")
        self.arvore.itemSelectionChanged.connect(self._selecionou_arvore)
        self.abas.currentChanged.connect(self._ao_trocar_aba)
        coluna.addWidget(self.abas, 3)
        legenda = QLabel("Itens da proposta selecionada")
        legenda.setObjectName("Chave")
        coluna.addWidget(legenda)
        self.t_itens = Tabela(["Parte", "Item", "Código", "Fluxo", "Pedido", "A fabricar", "Aguardando", "Em carga", "Prontas", "Entregues"])
        self.t_itens.horizontalHeader().setStretchLastSection(False)
        coluna.addWidget(self.t_itens, 2)
        divisor.addWidget(esquerda)

        direita = QWidget()
        coluna_direita = QVBoxLayout(direita)
        coluna_direita.setContentsMargins(0, 0, 0, 0)
        rotulo = QLabel("O que aconteceu")
        rotulo.setObjectName("Chave")
        coluna_direita.addWidget(rotulo)
        self.registro = QTextBrowser()
        self.registro.setOpenLinks(False)
        coluna_direita.addWidget(self.registro)
        divisor.addWidget(direita)
        divisor.setStretchFactor(0, 4)
        divisor.setStretchFactor(1, 2)
        raiz.addWidget(divisor, 1)

    # ---- selecao ------------------------------------------------------------------------------------
    def _tabela_atual(self) -> Tabela | None:
        widget = self.abas.currentWidget()
        return widget if isinstance(widget, Tabela) else None

    def propostas_selecionadas(self) -> list[int]:
        tabela = self._tabela_atual()
        if tabela is not None:
            return [int(tabela.item(i.row(), 0).data(ROLE_ID)) for i in tabela.selectionModel().selectedRows()]
        atual = self.arvore.currentItem()
        return [int(atual.data(0, ROLE_ID))] if atual is not None and atual.data(0, ROLE_ID) else []

    def _selecionou(self) -> None:
        ids = self.propostas_selecionadas()
        self.sel_id = ids[0] if ids else None
        self._preencher_itens()
        self._ajustar_botoes()

    def _ao_trocar_aba(self, _indice: int) -> None:
        if self.abas.currentWidget() is self.arvore:
            if self.arvore.topLevelItemCount() and self.arvore.currentItem() is None:
                self.arvore.setCurrentItem(self.arvore.topLevelItem(0))
        else:
            self._reselecionar()
        self._selecionou()

    def _selecionou_arvore(self) -> None:
        if self.abas.currentWidget() is self.arvore:
            self._selecionou()

    def linha_selecionada(self) -> int | None:
        linhas = self.t_itens.selectionModel().selectedRows()
        return int(self.t_itens.item(linhas[0].row(), 1).data(ROLE_ID)) if linhas else None

    # ---- atualizacao --------------------------------------------------------------------------------
    def atualizar(self) -> None:
        e = self.estado
        self._preencher_geral()
        self._preencher_producao()
        self._preencher_galvanizacao()
        self._preencher_expedicao()
        self._preencher_arvore()
        self._reselecionar()
        self._preencher_itens()
        self.combo_carga.clear()
        for carga, qtd in e.cargas_em_transito().items():
            self.combo_carga.addItem(f"Carga {carga} ({qtd} un)", carga)
        problemas = e.conferir()
        if problemas:
            self.conferencia.setObjectName("Alerta")
            self.conferencia.setText("⚠ Conferência: " + " | ".join(problemas))
        else:
            self.conferencia.setObjectName("Ok")
            self.conferencia.setText("✓ Conferência: nenhuma peça nasceu ou sumiu e o pedido de cada item continua igual ao original.")
        self.conferencia.style().unpolish(self.conferencia)
        self.conferencia.style().polish(self.conferencia)
        self.botao_desfazer.setEnabled(bool(self.historico))
        self._ajustar_botoes()

    def _celula_proposta(self, proposta: m.Proposta) -> dict:
        return {"texto": proposta.numero, "id": proposta.id, "marca": self.estado.tem_marca(proposta.id)}

    def _preencher_geral(self) -> None:
        e = self.estado
        self.t_geral.limpar()
        for proposta in e.visiveis_controle_geral():
            if e.eh_mae_referencia(proposta.id):
                selos = [selo_lugar("Entregue" if e.entregue(proposta.id) else "Referência")]
            elif e.entregue(proposta.id):
                selos = [selo_lugar("Entregue")]
            else:
                selos = [selo_lugar(l) for l in e.aparece_em(proposta.id)]
            self.t_geral.adicionar([self._celula_proposta(proposta), {"texto": proposta.cliente}, {"texto": " ", "selos": selos}, {"texto": e.situacao(proposta.id)}])

    def _preencher_producao(self) -> None:
        e = self.estado
        self.t_producao.limpar()
        for proposta in e.ativas():
            qtd = e.soma(proposta.id, m.A_FABRICAR)
            if qtd:
                itens = ", ".join(l.numero for l in e.linhas_de(proposta.id) if l.pecas[m.A_FABRICAR])
                self.t_producao.adicionar([self._celula_proposta(proposta), {"texto": proposta.cliente}, {"texto": qtd}, {"texto": itens}])

    def _preencher_galvanizacao(self) -> None:
        e = self.estado
        self.t_galv.limpar()
        for proposta in e.ativas():
            aguardando, em_carga = e.soma(proposta.id, m.AGUARDANDO), e.soma(proposta.id, m.EM_CARGA)
            if aguardando or em_carga:
                cargas = {}
                for linha in e.linhas_de(proposta.id):
                    for carga, qtd in linha.cargas.items():
                        cargas[carga] = cargas.get(carga, 0) + qtd
                texto = ", ".join(f"Carga {c}: {q}" for c, q in sorted(cargas.items())) or "—"
                self.t_galv.adicionar([self._celula_proposta(proposta), {"texto": proposta.cliente}, {"texto": aguardando}, {"texto": em_carga}, {"texto": texto}])

    def _preencher_expedicao(self) -> None:
        e = self.estado
        self.t_exp.limpar()
        for proposta in e.ativas():
            prontas = e.soma(proposta.id, m.PRONTA)
            if prontas:
                self.t_exp.adicionar([self._celula_proposta(proposta), {"texto": proposta.cliente}, {"texto": prontas}, {"texto": e.soma(proposta.id, m.ENTREGUE)}])

    def _preencher_arvore(self) -> None:
        e = self.estado
        self.arvore.clear()

        def linhas_do_no(no: QTreeWidgetItem, proposta: m.Proposta) -> None:
            for linha in e.linhas_de(proposta.id):
                partes = [f"{linha.pecas[est]} un {m.NOME_ESTAGIO[est]}" for est in (m.PRONTA, m.EM_CARGA, m.AGUARDANDO, m.A_FABRICAR, m.ENTREGUE) if linha.pecas[est]]
                filho = QTreeWidgetItem([f"Item {linha.numero} · {linha.codigo}", "", ", ".join(partes)])
                filho.setForeground(0, QColor(T["muted"]))
                filho.setForeground(2, QColor(T["muted"]))
                no.addChild(filho)

        for proposta in e.visiveis_controle_geral():
            referencia = e.eh_mae_referencia(proposta.id)
            no = QTreeWidgetItem([proposta.numero, "Referência (as partes seguem sozinhas)" if referencia else (" e ".join(e.aparece_em(proposta.id)) or "Entregue"), ""])
            no.setData(0, ROLE_ID, proposta.id)
            negrito = fonte(13, 700)
            no.setFont(0, negrito)
            self.arvore.addTopLevelItem(no)
            if not referencia:
                linhas_do_no(no, proposta)
            for filha in e.filhas(proposta.id):
                no_filha = QTreeWidgetItem([filha.numero, " e ".join(e.aparece_em(filha.id)) or "Entregue", ""])
                no_filha.setData(0, ROLE_ID, filha.id)
                no_filha.setFont(0, fonte(13, 600))
                no.addChild(no_filha)
                linhas_do_no(no_filha, filha)
        self.arvore.expandAll()
        self.arvore.setColumnWidth(0, 260)
        self.arvore.setColumnWidth(1, 250)

    def _reselecionar(self) -> None:
        if self.sel_id is None:
            tabela = self._tabela_atual()
            if tabela is not None and tabela.rowCount():
                tabela.selectRow(0)
            return
        tabela = self._tabela_atual()
        if tabela is not None:
            for linha in range(tabela.rowCount()):
                if tabela.item(linha, 0).data(ROLE_ID) == self.sel_id:
                    tabela.selectRow(linha)
                    return
            if tabela.rowCount():
                tabela.selectRow(0)
            else:
                self.sel_id = None

    def _preencher_itens(self) -> None:
        e = self.estado
        self.t_itens.limpar()
        if self.sel_id is None or self.sel_id not in e.propostas:
            return
        proposta = e.propostas[self.sel_id]
        donos = [proposta] if not e.tem_filhas(proposta.id) else [proposta, *e.filhas(proposta.id)]
        for dono in donos:
            for linha in e.linhas_de(dono.id):
                parte = dono.numero if dono.mae_id or e.tem_filhas(proposta.id) else ""
                self.t_itens.adicionar([
                    {"texto": parte}, {"texto": linha.numero, "id": linha.id}, {"texto": f"{linha.codigo}"}, {"texto": "Galvanizado" if linha.fluxo == "GALVANIZADO" else "Simples"},
                    {"texto": linha.total()}, {"texto": linha.pecas[m.A_FABRICAR]}, {"texto": linha.pecas[m.AGUARDANDO]}, {"texto": linha.pecas[m.EM_CARGA]},
                    {"texto": linha.pecas[m.PRONTA]}, {"texto": linha.pecas[m.ENTREGUE]},
                ])

    def _ajustar_botoes(self) -> None:
        tem = self.sel_id is not None and self.sel_id in self.estado.propostas
        self.botao_concluir.setEnabled(tem)
        self.botao_enviar.setEnabled(bool(self.propostas_selecionadas()))
        self.botao_entregar.setEnabled(tem)
        self.botao_retornar.setEnabled(self.combo_carga.count() > 0)

    # ---- acoes --------------------------------------------------------------------------------------
    def _executar(self, titulo: str, acao) -> None:
        guardado = self.estado.copia()
        antes = len(self.estado.log)
        try:
            acao()
        except m.ErroSimulacao as erro:
            QMessageBox.warning(self, titulo, str(erro))
            return
        self.historico.append(guardado)
        novas = self.estado.log[antes:]
        self.registro.append(f"<p><b style='color:{T['accent']}'>▶ {titulo}</b></p><ul>" + "".join(f"<li>{texto}</li>" for texto in novas) + "</ul>")
        self.atualizar()

    def _linha_do_checkbox(self) -> int | None:
        if not self.so_item.isChecked():
            return None
        linha_id = self.linha_selecionada()
        if linha_id is None:
            return None
        return linha_id

    def acao_remanejar(self) -> None:
        dialogo = DialogoRemanejar(self.estado, self)
        if dialogo.exec() and dialogo.operacoes:
            operacoes = list(dialogo.operacoes)
            self._executar("Remanejar", lambda: self.estado.remanejar_lote(operacoes))

    def acao_concluir(self) -> None:
        proposta_id = self.sel_id
        linha_id = self._linha_do_checkbox()
        self._executar("Concluir produção", lambda: self.estado.concluir_producao(proposta_id, linha_id))

    def acao_enviar(self) -> None:
        ids = self.propostas_selecionadas()
        self._executar("Enviar para galvanização", lambda: self.estado.enviar_carga(ids))

    def acao_retornar(self) -> None:
        carga = self.combo_carga.currentData()
        self._executar("Retornar carga", lambda: self.estado.retornar_carga(carga))

    def acao_entregar(self) -> None:
        proposta_id = self.sel_id
        linha_id = self._linha_do_checkbox()
        self._executar("Entregar", lambda: self.estado.entregar(proposta_id, linha_id))

    def desfazer(self) -> None:
        if not self.historico:
            return
        self.estado = self.historico.pop()
        self.registro.append("<p><i>↩ Última ação desfeita.</i></p>")
        self.atualizar()

    def reiniciar(self, cenario: str) -> None:
        self.cenario = cenario
        modo, variante = self.estado.modo, self.check_destino.isChecked()
        self.estado = m.montar_cenario(cenario, modo)
        self.estado.destino_por_lugar = variante
        self.historico.clear()
        self.sel_id = None
        self.registro.clear()
        self.registro.append(f"<p><b>Cenário {cenario}: {m.CENARIOS[cenario]}</b><br><i>Modo \"{'Como proposto' if self.estado.modo == m.PROPOSTO else 'Como é hoje'}\"</i></p><p>{DICAS[cenario]}</p>")
        self.combo_cenario.setCurrentIndex(list(m.CENARIOS).index(cenario))
        self.atualizar()

    def _trocar_destino(self, ligado: bool) -> None:
        self.estado.destino_por_lugar = ligado

    def trocar_modo(self, modo: str) -> None:
        if modo != self.estado.modo:
            self.estado.modo = modo
            self.reiniciar(self.cenario)

    def mostrar_marca(self, proposta_id: int) -> None:
        DialogoMarca(self.estado, proposta_id, self).exec()


def principal() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tema", choices=tuple(TEMAS), default="claro")
    parser.add_argument("--cenario", choices=tuple(m.CENARIOS), default="1")
    parser.add_argument("--modo", choices=("hoje", "proposto"), default="proposto")
    parser.add_argument("--shot", metavar="ARQUIVO.png")
    args = parser.parse_args()
    T.clear()
    T.update(TEMAS[args.tema])
    app = QApplication(sys.argv[:1])
    carregar_fontes()
    app.setStyleSheet(folha())
    janela = Janela(args.cenario, m.PROPOSTO if args.modo == "proposto" else m.HOJE)
    janela.resize(1440, 860)
    janela.show()
    if args.shot:
        QTimer.singleShot(700, lambda: (janela.grab().save(args.shot), print(f"salvo={args.shot}"), app.quit()))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(principal())
