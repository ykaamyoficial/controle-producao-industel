"""Prototipo ISOLADO da tela "Acoes da proposta" com as melhorias propostas
para toda tela que abre por cima do programa:

1. Canto suavizado. Hoje o canto e recortado com mascara de janela
   (`setMask`), que so liga ou desliga o pixel inteiro e deixa a curva
   serrilhada. Aqui a janela tem fundo transparente e a moldura e pintada com
   suavizacao.
2. Borda com um pouco de volume: aro fino, filete de luz no alto, sombreado
   embaixo e duas sombras (uma larga, uma colada na borda).
3. Abrir e fechar no jeito do macOS/iOS: a janela salta para o lugar com uma
   mola (chega rapido, passa um pouco do tamanho e assenta) e sai encolhendo
   enquanto some; o veu acompanha.

A janela continua sendo um `QDialog` de nivel superior aberto por `open()` /
`exec()`, como no sistema: e isso que permite levar a mesma casca (`Janela`)
para as telas reais sem mudar o fluxo delas.

Nao importa nada de `app/` nem fala com a API: os dados sao ficticios e
nenhuma acao grava nada. Reaproveita os componentes dos prototipos do
Controle Geral e de Detalhes da proposta.

Uso:
    python prototipos/acoes_proposta/acoes.py
    python prototipos/acoes_proposta/acoes.py --raio 20          # 16, 20 ou 24 (padrao)
    python prototipos/acoes_proposta/acoes.py --lento            # camera lenta
    python prototipos/acoes_proposta/acoes.py --hoje             # como e hoje, para comparar
    python prototipos/acoes_proposta/acoes.py --tema escuro
    python prototipos/acoes_proposta/acoes.py --shot saida.png --confirmar

Com a janela aberta: Esc fecha, o topo arrasta, "Pausar producao" abre uma
confirmacao pequena com a mesma casca. Com ela fechada, o painel "PROTOTIPO"
no rodape troca canto e velocidade; duplo clique numa linha reabre.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

PROTOTIPOS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROTOTIPOS / "controle_geral"))
sys.path.insert(0, str(PROTOTIPOS / "detalhes_proposta"))

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QBrush,
    QColor,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QRegion,
)
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import preview as base  # noqa: E402
from detalhes import Selo, rotulo  # noqa: E402
from preview import TEMA, Botao, Seletor, animar, fonte, mix, pintar_icone  # noqa: E402

# --------------------------------------------------------------------------
# Dados ficticios
# --------------------------------------------------------------------------
PROPOSTA = {
    "numero": "CP 05672",
    "cliente": "Torres Norte Telecom",
    "area": ("Produção", "location_production"),
    "status": "Em produção",
}
# (id, titulo, descricao, icone, tipo), na ordem em que a API devolve.
ACOES = [
    ("PAUSAR", "Pausar produção", "Suspende temporariamente a produção desta proposta.", "circle-pause", "atencao"),
    ("FLUXO", "Definir fluxo dos itens", "Escolha quais itens serão produzidos e galvanizados.", "workflow", "normal"),
    ("PESOS", "Editar pesos dos itens", "Cadastre ou atualize os pesos dos itens.", "scale", "normal"),
    ("REGISTRAR", "Registrar produção", "Informe as quantidades produzidas de cada item.", "circle-check", "principal"),
]

# --------------------------------------------------------------------------
# Medidas e movimento
# --------------------------------------------------------------------------
SOMBRA = 48  # faixa transparente em volta da janela, onde a sombra e pintada
ESCALA_ENTRADA = 0.88  # a janela nasce com este tamanho e salta para 100%
ESCALA_SAIDA = 0.94  # e encolhe ate este enquanto some
MOLA_MS = 550  # ate a mola assentar; a janela ja parece no lugar em ~200 ms
MOLA_RESPOSTA = 0.40  # segundos de um ciclo da mola: menor = mais rapida
MOLA_AMORTECIMENTO = 0.68  # 1 = sem quique; 0.68 passa ~5% do ponto
APARECER_MS = 160
SAIDA_MS = 180
VEU_MS = 260


class Ajuste:
    """O que o painel do prototipo deixa trocar entre uma abertura e outra."""

    raio = 24  # aprovado em 13/10/2026
    hoje = False  # True: recorte por mascara e sem animacao, como no sistema atual
    lentidao = 1  # 5 = camera lenta


def ms(valor: int) -> int:
    return valor * Ajuste.lentidao if base.ANIMAR else 0


def raio_painel(raio: int) -> int:
    """Raios internos acompanham o da janela sem igualar: 16 -> 14, 20 -> 16, 24 -> 18."""
    return 14 + (raio - 16) // 2


def raio_campo(raio: int) -> int:
    return 10 + (raio - 16) // 4


def curto(valor: int) -> int:
    """Duracao de realce e clique: nao entra na camera lenta."""
    return valor if base.ANIMAR else 0


# Curva padrao do Core Animation, cubic-bezier(.25, .1, .25, 1): usada em tudo
# que nao e mola (aparecer, sumir, veu).
_PADRAO = QEasingCurve(QEasingCurve.BezierSpline)
_PADRAO.addCubicBezierSegment(QPointF(0.25, 0.1), QPointF(0.25, 1.0), QPointF(1.0, 1.0))


def padrao(progresso: float) -> float:
    return _PADRAO.valueForProgress(progresso)


def mola(progresso: float) -> float:
    """Mola pouco amortecida, como as do macOS/iOS: devolve quanto do caminho ja
    foi andado e passa de 1 no quique antes de assentar."""
    t = progresso * MOLA_MS / 1000
    natural = 2 * math.pi / MOLA_RESPOSTA
    queda = MOLA_AMORTECIMENTO * natural
    oscila = natural * math.sqrt(1 - MOLA_AMORTECIMENTO**2)
    return 1 - math.exp(-queda * t) * (math.cos(oscila * t) + queda / oscila * math.sin(oscila * t))


def transicao(widget: QWidget, atributo: str, fim: float, duracao: int, curva=padrao, ao_terminar=None) -> None:
    """Anima um atributo pintado; uma animacao por atributo, e avisa no fim.
    `curva` recebe o progresso (0 a 1) e devolve quanto do caminho ja andou."""
    animacoes = widget.__dict__.setdefault("_transicoes", {})
    anterior = animacoes.pop(atributo, None)
    if anterior is not None:
        anterior.stop()
        anterior.deleteLater()
    inicio = float(getattr(widget, atributo))
    fim = float(fim)

    def chegou():
        setattr(widget, atributo, fim)
        widget.update()
        if ao_terminar:
            ao_terminar()

    if duracao <= 0:
        chegou()
        return
    anim = QVariantAnimation(widget)
    anim.setDuration(duracao)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)

    def aplica(progresso):
        setattr(widget, atributo, inicio + (fim - inicio) * curva(progresso))
        widget.update()

    anim.valueChanged.connect(aplica)
    anim.finished.connect(chegou)
    animacoes[atributo] = anim
    anim.start()


def depois(widget: QWidget, atraso: int, funcao) -> None:
    """Chama `funcao` daqui a `atraso` ms; se o widget morrer antes, nao chama."""
    relogio = QTimer(widget)
    relogio.setSingleShot(True)
    relogio.timeout.connect(funcao)
    relogio.timeout.connect(relogio.deleteLater)
    relogio.start(atraso)


def recorte_de_hoje(largura: int, altura: int, raio: int) -> QRegion:
    """O mesmo recorte de `app/ui/components/frameless_dialog.py`."""
    caminho = QPainterPath()
    caminho.addRoundedRect(0, 0, largura, altura, raio, raio)
    return QRegion(caminho.toFillPolygon().toPolygon())


TINTA = (8, 15, 30)  # azul quase preto do veu e das sombras


def pintar_sombra(p: QPainter, area: QRectF, raio: float) -> None:
    """Duas sombras em camadas, como nas janelas do macOS: uma larga e fraca,
    que afasta a janela do fundo, e uma curta e mais escura colada na borda."""
    escuro = TEMA.nome == "escuro"
    p.setPen(Qt.NoPen)
    for camadas, passo, desce, pico in ((30, 0.95, 14, 11 if escuro else 7), (6, 1.0, 2, 16 if escuro else 11)):
        for i in range(camadas):
            peso = 1 - i / camadas
            folga = 1 + i * passo
            p.setBrush(QColor(*TINTA, round(pico * peso * peso)))
            p.drawRoundedRect(area.adjusted(-folga, -folga + desce, folga, folga + desce), raio + folga, raio + folga)


def pintar_corpo(p: QPainter, area: QRectF, raio: float) -> None:
    """Corpo da janela com um pouco de volume, como uma placa iluminada de
    cima: aro fino por fora, filete de luz logo por dentro (forte no alto) e
    sombreado na borda de baixo. O miolo e a cor de fundo chapada, como na
    casca real (app/ui/components/window_shell.py): um degrade ali deixaria
    aparente qualquer area de rolagem ou painel pintado com essa mesma cor."""
    escuro = TEMA.nome == "escuro"
    p.setPen(Qt.NoPen)
    p.setBrush(TEMA.cor("bg"))
    p.drawRoundedRect(area, raio, raio)

    # Chanfro: aneis concentricos cada vez mais fracos para dentro; a luz vem
    # de cima, entao o alto clareia e a base escurece.
    p.setBrush(Qt.NoBrush)
    aneis = 5
    for i in range(aneis):
        forca = (1 - i / aneis) ** 2
        luz = QLinearGradient(area.topLeft(), area.bottomLeft())
        luz.setColorAt(0.0, QColor(255, 255, 255, round((80 if escuro else 255) * forca)))
        luz.setColorAt(0.3, QColor(255, 255, 255, round((14 if escuro else 90) * forca)))
        luz.setColorAt(0.7, QColor(*TINTA, round((30 if escuro else 6) * forca)))
        luz.setColorAt(1.0, QColor(*TINTA, round((150 if escuro else 44) * forca)))
        recuo = 1.5 + i
        p.setPen(QPen(QBrush(luz), 1))
        p.drawRoundedRect(area.adjusted(recuo, recuo, -recuo, -recuo), raio - recuo, raio - recuo)

    # Aro externo: da o recorte nitido contra qualquer fundo.
    p.setPen(QPen(QColor(*TINTA, 200 if escuro else 60), 1))
    p.drawRoundedRect(area.adjusted(0.5, 0.5, -0.5, -0.5), raio - 0.5, raio - 0.5)


def estilo_janela(raio: int) -> str:
    t = TEMA.t
    return f"""
    QFrame#Painel {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: {raio_painel(raio)}px; }}
    QFrame#Divisor {{ background: {t['border']}; border: 0; }}
    QLabel#DTitulo {{ font-size: 18px; font-weight: 800; }}
    QLabel#CTitulo {{ font-size: 16px; font-weight: 700; }}
    QLabel#PainelTitulo {{ font-size: 14px; font-weight: 700; }}
    QLabel#Texto {{ color: {t['muted']}; }}
    QScrollArea {{ background: transparent; border: 0; }}
    QWidget#Rolagem {{ background: transparent; }}
    QTextEdit {{
        background: {t['surface']}; border: 1px solid {t['input_border']}; border-radius: {raio_campo(raio)}px;
        padding: 5px 9px; selection-background-color: {t['accent']}; selection-color: {t['accent_text']};
    }}
    QTextEdit:focus {{ border: 2px solid {t['ring']}; padding: 4px 8px; }}
    QTextEdit:disabled {{ color: {t['subtle']}; }}
    """


# --------------------------------------------------------------------------
# Casca de janela sobreposta
# --------------------------------------------------------------------------
class Veu(QWidget):
    """Escurece a janela de tras. Filho da janela dona, como o `DialogScrim` do
    sistema; a diferenca e que tambem some com fade.

    Enquanto escurece ou clareia ele pinta uma foto da janela de tras, em vez
    de deixa-la repintar por baixo a cada quadro: repintar a pagina inteira
    custa dezenas de ms (medido: ~50 ms aqui) e a animacao da janela perdia
    quadros. Parado ele volta a ser transparente e a pagina de tras segue viva.
    """

    def __init__(self, dono: QWidget, congela: bool):
        super().__init__(dono)
        self._a = 0.0
        self._congela = congela
        self._fundo: QPixmap | None = None
        self._capturando = False
        self._ocioso = QTimer(self)
        self._ocioso.setSingleShot(True)
        self._ocioso.setInterval(700)
        self._ocioso.timeout.connect(self._descongelar)
        self.hide()
        dono.installEventFilter(self)

    def eventFilter(self, objeto, evento):
        if objeto is self.parent() and evento.type() == QEvent.Resize and self.isVisible():
            self._descongelar()
            self.setGeometry(objeto.rect())
        return False

    def _congelar(self) -> None:
        dono = self.parent()
        # Dona que tambem e uma `Janela` e pequena: repintar sai barato.
        if not self._congela or not base.ANIMAR or isinstance(dono, Janela):
            return
        self._capturando = True  # a foto e da pagina limpa, sem este veu por cima
        self._fundo = dono.grab()
        self._capturando = False
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def _descongelar(self) -> None:
        if self._fundo is None:
            return
        self._fundo = None
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.update()

    def mostrar(self) -> None:
        """Entra em cena ainda transparente; quem escurece e `escurecer()`."""
        self._congelar()
        self._a = 0.0
        self.setGeometry(self.parent().rect())
        self.show()
        self.raise_()

    def escurecer(self) -> None:
        transicao(self, "_a", 1.0, ms(VEU_MS), ao_terminar=lambda: self._ocioso.start())

    def clarear(self) -> None:
        self._ocioso.stop()
        if self._fundo is None:
            self._congelar()
        transicao(self, "_a", 0.0, ms(SAIDA_MS))

    def paintEvent(self, _e):
        if self._capturando:
            return
        p = QPainter(self)
        if self._fundo is not None:
            p.drawPixmap(0, 0, self._fundo)
        dono = self.parent()
        if isinstance(dono, Janela):
            # Dona com canto transparente: o veu nao pode pintar fora dela.
            p.setRenderHint(QPainter.Antialiasing)
            p.setClipPath(dono.contorno())
        p.fillRect(self.rect(), QColor(*TINTA, int((150 if TEMA.nome == "escuro" else 105) * self._a)))


class Cortina(QWidget):
    """Fica por cima da janela enquanto ela abre ou fecha e pinta, no lugar do
    conteudo, a foto dela mudando de tamanho e de opacidade.

    O conteudo de verdade continua embaixo, ja no lugar definitivo: na entrada
    a cortina deixa o mouse passar, entao a janela aceita clique e teclado
    desde o primeiro quadro, sem esperar a mola assentar. Ela se declara opaca
    (repinta todos os seus pixels, apagando antes o que havia), assim o Qt nao
    redesenha tabela nem area de rolagem a cada quadro.
    """

    def __init__(self, janela: QWidget, foto: QPixmap, escala: float, opacidade: float, deixa_clicar: bool):
        super().__init__(janela)
        self._foto = foto
        self._escala = escala
        self._opacidade = opacidade
        self.ao_pintar = None
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, deixa_clicar)
        self.setGeometry(janela.rect())
        self.show()
        self.raise_()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        centro = QRectF(self.rect()).center()
        p.setOpacity(max(0.0, min(1.0, self._opacidade)))
        p.translate(centro)
        p.scale(self._escala, self._escala)
        p.translate(-centro)
        p.drawPixmap(0, 0, self._foto)
        if self.ao_pintar is not None:
            chamada, self.ao_pintar = self.ao_pintar, None
            depois(self, 0, chamada)


class Janela(QDialog):
    """Casca de toda tela que abre por cima do programa.

    Canto e borda: fundo transparente + moldura pintada com suavizacao, volume
    e sombra, em vez do recorte por mascara. Abrir/fechar: a janela tira uma
    foto de si mesma e uma `Cortina` pinta essa foto saltando para o lugar (ou
    encolhendo e sumindo). Nada de `QGraphicsEffect`.

    `done()` so fecha de fato quando a saida termina, entao `exec()` e o sinal
    `finished` continuam valendo como hoje.
    """

    def __init__(self, dono: QWidget, largura: int):
        super().__init__(dono)
        self._hoje = Ajuste.hoje
        self._raio = 16 if self._hoje else Ajuste.raio
        self._borda = 0 if self._hoje else SOMBRA
        self._largura = largura
        self._cortina: Cortina | None = None
        self._moldura: QPixmap | None = None
        self._abriu = False
        self._entrada_iniciada = False
        self._saindo = False
        self._sem_saida = False
        self._arrasto: QPoint | None = None
        self._veu = Veu(dono.window(), congela=not self._hoje)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        if not self._hoje:
            self.setAttribute(Qt.WA_TranslucentBackground)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(self._borda, self._borda, self._borda, self._borda)
        self.cartao = QFrame()
        raiz.addWidget(self.cartao)
        self.corpo = QVBoxLayout(self.cartao)
        self.corpo.setContentsMargins(16, 14, 16, 14)
        self.corpo.setSpacing(10)
        self.setStyleSheet(estilo_janela(self._raio))

    # ---- geometria -------------------------------------------------------
    def assentar(self) -> None:
        """Fixa o tamanho pelo conteudo e centraliza na janela dona."""
        self.cartao.setFixedWidth(self._largura)
        self.adjustSize()
        self.setFixedSize(self.size())
        dono = self.parentWidget().window()
        self.move(dono.mapToGlobal(dono.rect().center()) - self.rect().center())

    def area(self) -> QRectF:
        """A parte visivel da janela (sem a faixa da sombra)."""
        return QRectF(self.rect()).adjusted(self._borda, self._borda, -self._borda, -self._borda)

    def contorno(self) -> QPainterPath:
        caminho = QPainterPath()
        caminho.addRoundedRect(self.area(), self._raio, self._raio)
        return caminho

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._moldura = None
        if self._hoje:
            self.setMask(recorte_de_hoje(self.width(), self.height(), self._raio))

    # ---- pintura ---------------------------------------------------------
    def _pintar_moldura(self) -> QPixmap:
        escala = self.devicePixelRatioF()
        moldura = QPixmap(self.size() * escala)
        moldura.setDevicePixelRatio(escala)
        moldura.fill(Qt.transparent)
        p = QPainter(moldura)
        p.setRenderHint(QPainter.Antialiasing)
        area = self.area()
        if self._hoje:
            p.fillRect(self.rect(), TEMA.cor("bg"))
            p.setPen(QPen(TEMA.cor("border"), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(area.adjusted(0.5, 0.5, -0.5, -0.5), self._raio - 0.5, self._raio - 0.5)
        else:
            pintar_sombra(p, area, self._raio)
            pintar_corpo(p, area, self._raio)
        p.end()
        return moldura

    def paintEvent(self, _e):
        if self._moldura is None:
            self._moldura = self._pintar_moldura()
        QPainter(self).drawPixmap(0, 0, self._moldura)

    # ---- abrir e fechar --------------------------------------------------
    def pronta(self) -> None:
        """A janela ja recebe teclado e mouse: hora do foco inicial."""

    def showEvent(self, e):
        super().showEvent(e)
        if e.spontaneous():
            return
        self._veu.mostrar()
        if self._abriu or self._hoje or not base.ANIMAR:
            self._veu.escurecer()
            if not self._abriu:
                self._abriu = True
                depois(self, 0, self.pronta)
            return
        self._abriu = True
        # Os filhos ja foram exibidos e a janela ainda nao esta na tela: o
        # primeiro quadro que o usuario ve ja e o da animacao. O relogio so
        # parte quando esse quadro e pintado; se partisse aqui, o tempo de o
        # Windows criar a janela comia o comeco do salto.
        self._cortina = Cortina(self, self.grab(), ESCALA_ENTRADA, 0.0, deixa_clicar=True)
        self._cortina.ao_pintar = self._comecar_entrada

    def _comecar_entrada(self) -> None:
        if self._saindo:
            return
        self._entrada_iniciada = True
        self._veu.escurecer()
        transicao(self._cortina, "_opacidade", 1.0, ms(APARECER_MS))
        transicao(self._cortina, "_escala", 1.0, ms(MOLA_MS), mola, self._tirar_cortina)
        self.pronta()

    def _tirar_cortina(self) -> None:
        cortina, self._cortina = self._cortina, None
        if cortina is not None:
            cortina.hide()
            cortina.deleteLater()

    def done(self, resultado: int) -> None:
        if self._saindo:
            return
        esperando_quadro = self._cortina is not None and not self._entrada_iniciada
        if self._hoje or not base.ANIMAR or not self.isVisible() or self._sem_saida or esperando_quadro:
            self._encerrar(resultado)
            return
        self._saindo = True
        if self._cortina is None:
            self._cortina = Cortina(self, self.grab(), 1.0, 1.0, deixa_clicar=False)
        else:  # fechou no meio da entrada: sai do tamanho em que a foto estava
            self._cortina.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.cartao.setEnabled(False)
        self._veu.clarear()
        transicao(self._cortina, "_escala", ESCALA_SAIDA, ms(SAIDA_MS))
        transicao(self._cortina, "_opacidade", 0.0, ms(SAIDA_MS), ao_terminar=lambda: self._encerrar(resultado))

    def _encerrar(self, resultado: int) -> None:
        self._saindo = True
        self._veu.hide()
        self._veu.deleteLater()
        super().done(resultado)

    def closeEvent(self, e):
        # Fechamento pedido de fora (Alt+F4, programa encerrando) nao espera a
        # saida: o QDialog recusa o fechamento se a janela ainda estiver visivel
        # depois do reject(), e isso cancelaria ate o encerramento do programa.
        self._sem_saida = True
        super().closeEvent(e)

    # ---- teclado e arrasto -----------------------------------------------
    def keyPressEvent(self, e):
        foco = self.focusWidget()
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and isinstance(foco, QAbstractButton):
            foco.click()
            return
        super().keyPressEvent(e)

    def mousePressEvent(self, e):
        area = self.area()
        topo = QRectF(area.left(), area.top(), area.width(), 64)
        if e.button() == Qt.LeftButton and topo.contains(e.position()):
            self._arrasto = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._arrasto is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._arrasto)

    def mouseReleaseEvent(self, e):
        self._arrasto = None


# --------------------------------------------------------------------------
# Componentes desta tela
# --------------------------------------------------------------------------
class CartaoAcao(QAbstractButton):
    """Cartao de acao: icone, titulo, descricao e seta. Mesma hierarquia do
    `ActionCardButton` do sistema (principal / normal / atencao / destrutiva),
    mas pintado, para o realce e o clique serem animados."""

    def __init__(self, titulo: str, descricao: str, icone_nome: str, tipo: str, raio: int, parent=None):
        super().__init__(parent)
        self.setText(titulo)
        self._descricao = descricao
        self._icone = icone_nome
        self._tipo = tipo
        self._raio = raio
        self._h = 0.0
        self._p = 0.0
        self._anel = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(96 if descricao else 64)
        self.setAccessibleName(titulo)
        self.setAccessibleDescription(descricao)
        TEMA.mudou.connect(self.update)

    def sizeHint(self) -> QSize:
        return QSize(320, self.minimumHeight())

    def enterEvent(self, e):
        animar(self, "_h", 1.0, 140)
        super().enterEvent(e)

    def leaveEvent(self, e):
        animar(self, "_h", 0.0, 180)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        transicao(self, "_p", 1.0, curto(90))
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        # Solta com a mesma mola da janela: volta ao tamanho e assenta.
        transicao(self, "_p", 0.0, curto(400), mola)
        super().mouseReleaseEvent(e)

    def focusInEvent(self, e):
        self._anel = base.foco_por_teclado(e)
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self._anel = False
        super().focusOutEvent(e)

    def _cores(self) -> dict:
        h = self._h if self.isEnabled() else 0.0
        if self._tipo == "normal":
            return {
                "fundo": mix(TEMA.cor("surface"), TEMA.cor("surface_alt"), h),
                "borda": mix(TEMA.cor("border"), TEMA.cor("input_border"), h),
                "chip": mix(TEMA.cor("surface_alt"), TEMA.cor("surface"), h),
                "icone": TEMA.cor("text"),
                "titulo": TEMA.cor("text"),
                "peso": 600,
                "seta": TEMA.cor("muted"),
            }
        token = {"principal": "accent", "atencao": "warning", "destrutiva": "danger"}[self._tipo]
        principal = self._tipo == "principal"
        return {
            "fundo": TEMA.cor(token, (18 + 14 * h + 10 * self._p) / 255),
            "borda": TEMA.cor(token, (140 + 115 * h) / 255),
            "chip": TEMA.cor(token) if principal else TEMA.cor(token, 32 / 255),
            "icone": TEMA.cor("accent_text") if principal else TEMA.cor(token),
            # accent_hover no titulo: sobre o fundo azulado o accent puro nao chega a 4.5:1.
            "titulo": TEMA.cor("accent_hover") if principal else TEMA.cor("text" if self._tipo == "atencao" else token),
            "peso": 600 if self._tipo == "atencao" else 700,
            "seta": TEMA.cor(token),
        }

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.5)
        centro = QRectF(self.rect()).center()
        escala = 1.0 - 0.03 * self._p
        p.translate(centro)
        p.scale(escala, escala)
        p.translate(-centro)

        cores = self._cores()
        if self._anel:
            p.setPen(QPen(TEMA.cor("ring"), 2))
            moldura = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        else:
            p.setPen(QPen(cores["borda"], 1))
            moldura = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(cores["fundo"])
        p.drawRoundedRect(moldura, self._raio, self._raio)

        cy = self.height() / 2
        p.setPen(Qt.NoPen)
        p.setBrush(cores["chip"])
        p.drawRoundedRect(QRectF(16, cy - 23, 46, 46), self._raio - 2, self._raio - 2)
        pintar_icone(p, self._icone, QRectF(16 + 9, cy - 14, 28, 28), cores["icone"])

        x = 16 + 46 + 14
        largura = self.width() - x - 14 - 20 - 16
        fonte_titulo = fonte(14, cores["peso"])
        fonte_descricao = fonte(12, 400)
        quebra = int(Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop)
        altura_titulo = QFontMetrics(fonte_titulo).boundingRect(0, 0, largura, 400, quebra, self.text()).height()
        altura_descricao = 0
        if self._descricao:
            altura_descricao = QFontMetrics(fonte_descricao).boundingRect(0, 0, largura, 400, quebra, self._descricao).height()
        y = cy - (altura_titulo + (3 + altura_descricao if self._descricao else 0)) / 2
        p.setFont(fonte_titulo)
        p.setPen(cores["titulo"])
        p.drawText(QRectF(x, y, largura, altura_titulo), quebra, self.text())
        if self._descricao:
            p.setFont(fonte_descricao)
            p.setPen(TEMA.cor("muted"))
            p.drawText(QRectF(x, y + altura_titulo + 3, largura, altura_descricao), quebra, self._descricao)

        # A seta anda 3 px no realce: e a pista de que o cartao leva a algum lugar.
        pintar_icone(p, "chevron-right", QRectF(self.width() - 16 - 18 + 3 * self._h, cy - 7.5, 15, 15), cores["seta"])


class Emblema(QWidget):
    """Icone dentro de um circulo na cor do aviso."""

    def __init__(self, icone_nome: str, token: str, parent=None):
        super().__init__(parent)
        self._icone = icone_nome
        self._token = token
        self.setFixedSize(40, 40)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(TEMA.cor(self._token, 0.14))
        p.drawEllipse(QRectF(self.rect()))
        pintar_icone(p, self._icone, QRectF(10, 10, 20, 20), TEMA.cor(self._token))


class Aviso(QWidget):
    """Aviso no pe da pagina: sobe com a mola, fica um pouco e some."""

    def __init__(self, pagina: QWidget, texto: str):
        super().__init__(pagina)
        self._texto = texto
        self._a = 0.0
        self._desce = 1.0  # 1 = ainda 16 px abaixo do lugar
        largura = QFontMetrics(fonte(13, 600)).horizontalAdvance(texto) + 16 + 20 + 10 + 18
        self.setGeometry((pagina.width() - largura) // 2, pagina.height() - 180, largura, 64)
        self.show()
        self.raise_()
        transicao(self, "_a", 1.0, ms(APARECER_MS))
        transicao(self, "_desce", 0.0, ms(MOLA_MS), mola)
        depois(self, 2600 + ms(MOLA_MS), self._sair)

    def _sair(self) -> None:
        transicao(self, "_desce", 1.0, ms(SAIDA_MS))
        transicao(self, "_a", 0.0, ms(SAIDA_MS), ao_terminar=self.deleteLater)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(max(0.0, min(1.0, self._a)))
        p.translate(0, 4 + self._desce * 16)
        corpo = QRectF(0, 0, self.width(), 44)
        p.setPen(Qt.NoPen)
        p.setBrush(TEMA.cor("text"))
        p.drawRoundedRect(corpo, 12, 12)
        pintar_icone(p, "info", QRectF(16, corpo.center().y() - 10, 20, 20), TEMA.cor("bg"))
        p.setFont(fonte(13, 600))
        p.setPen(TEMA.cor("bg"))
        p.drawText(corpo.adjusted(46, 0, -18, 0), Qt.AlignVCenter | Qt.AlignLeft, self._texto)


# --------------------------------------------------------------------------
# As telas
# --------------------------------------------------------------------------
class Confirmacao(Janela):
    """Janela pequena com a mesma casca, aberta por `exec()` por cima de outra."""

    def __init__(self, dono: QWidget):
        super().__init__(dono, largura=460)
        self.corpo.setContentsMargins(20, 18, 20, 16)
        self.corpo.setSpacing(16)
        topo = QHBoxLayout()
        topo.setSpacing(14)
        topo.addWidget(Emblema("circle-pause", "warning"), 0, Qt.AlignTop)
        textos = QVBoxLayout()
        textos.setSpacing(4)
        textos.addWidget(rotulo("Pausar a produção?", "CTitulo"))
        texto = rotulo(
            f"A proposta {PROPOSTA['numero']} fica parada até alguém retomar. "
            "Nenhum registro de produção é apagado.",
            "Texto",
        )
        texto.setWordWrap(True)
        textos.addWidget(texto)
        topo.addLayout(textos, 1)
        self.corpo.addLayout(topo)

        rodape = QHBoxLayout()
        rodape.setSpacing(8)
        rodape.addStretch(1)
        voltar = Botao("Voltar", None, "fantasma")
        voltar.clicked.connect(self.reject)
        self.confirmar = Botao("Pausar produção", "circle-pause", "primario")
        self.confirmar.clicked.connect(self.accept)
        rodape.addWidget(voltar)
        rodape.addWidget(self.confirmar)
        self.corpo.addLayout(rodape)
        self.assentar()

    def pronta(self) -> None:
        self.confirmar.setFocus(Qt.OtherFocusReason)


class AcoesProposta(Janela):
    """A Central de Acoes da proposta, com a mesma montagem de
    `app/ui/action_center/proposal_action_center.py`: cabecalho-cartao, grade
    de acoes (a principal por ultimo, de ponta a ponta), observacao e rodape."""

    def __init__(self, dono: QWidget):
        super().__init__(dono, largura=760)
        self.escolhida = ""
        self._cartoes: list[CartaoAcao] = []
        self._principal: CartaoAcao | None = None
        self.corpo.addWidget(self._cabecalho())
        self.corpo.addWidget(rotulo("Ações disponíveis", "PainelTitulo"))
        self.corpo.addWidget(self._grade(), 1)

        self.corpo.addWidget(QLabel("Observação (opcional)"))
        self.observacao = QTextEdit()
        self.observacao.setPlaceholderText("Acrescente uma informação importante sobre esta operação")
        self.observacao.setFixedHeight(68)
        self.observacao.setTabChangesFocus(True)
        paleta = self.observacao.palette()
        paleta.setColor(QPalette.PlaceholderText, TEMA.cor("subtle"))
        self.observacao.setPalette(paleta)
        self.corpo.addWidget(self.observacao)

        divisor = QFrame()
        divisor.setObjectName("Divisor")
        divisor.setFixedHeight(1)
        self.corpo.addWidget(divisor)

        rodape = QHBoxLayout()
        rodape.setSpacing(8)
        correcao = Botao("Correção administrativa", "shield-alert")
        correcao.setToolTip("Não executa nada no protótipo")
        fechar = Botao("Fechar", "x", "fantasma")
        fechar.clicked.connect(self.reject)
        rodape.addWidget(correcao)
        rodape.addStretch(1)
        rodape.addWidget(fechar)
        self.corpo.addLayout(rodape)
        self.assentar()

    def _cabecalho(self) -> QFrame:
        quadro = QFrame()
        quadro.setObjectName("Painel")
        coluna = QVBoxLayout(quadro)
        coluna.setContentsMargins(18, 12, 14, 12)
        coluna.setSpacing(8)
        coluna.addWidget(rotulo(f"{PROPOSTA['numero']} — {PROPOSTA['cliente']}", "DTitulo"))
        selos = QHBoxLayout()
        selos.setSpacing(6)
        selos.addWidget(Selo(*PROPOSTA["area"]))
        selos.addWidget(Selo(PROPOSTA["status"], "neutral"))
        selos.addStretch(1)
        coluna.addLayout(selos)
        return quadro

    def _grade(self) -> QScrollArea:
        conteudo = QWidget()
        conteudo.setObjectName("Rolagem")
        grade = QGridLayout(conteudo)
        grade.setContentsMargins(0, 0, 0, 0)
        grade.setHorizontalSpacing(12)
        grade.setVerticalSpacing(12)
        grade.setColumnStretch(0, 1)
        grade.setColumnStretch(1, 1)
        demais = [acao for acao in ACOES if acao[4] != "principal"]
        principal = next((acao for acao in ACOES if acao[4] == "principal"), None)
        for indice, acao in enumerate(demais):
            grade.addWidget(self._cartao(acao), indice // 2, indice % 2)
        if principal:
            self._principal = self._cartao(principal)
            grade.addWidget(self._principal, (len(demais) + 1) // 2, 0, 1, 2)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.setWidget(conteudo)
        area.setMinimumHeight(min(conteudo.sizeHint().height(), 420))
        return area

    def _cartao(self, acao: tuple) -> CartaoAcao:
        _id, titulo, descricao, icone_nome, tipo = acao
        cartao = CartaoAcao(titulo, descricao, icone_nome, tipo, raio_painel(self._raio) - 2)
        cartao.clicked.connect(lambda _marcado=False, dados=acao: self._executar(dados))
        self._cartoes.append(cartao)
        return cartao

    def pronta(self) -> None:
        if self._principal:
            self._principal.setFocus(Qt.OtherFocusReason)

    def _executar(self, acao: tuple) -> None:
        if acao[0] == "PAUSAR":
            confirmacao = Confirmacao(self)
            aceitou = confirmacao.exec() == QDialog.Accepted
            confirmacao.deleteLater()
            if not aceitou:
                return
        # A acao dispara na hora; a janela so fecha quando a "API" responde.
        self.escolhida = acao[1]
        self.observacao.setEnabled(False)
        for cartao in self._cartoes:
            cartao.setEnabled(False)
        depois(self, 450, self.accept)


# --------------------------------------------------------------------------
# Painel do prototipo
# --------------------------------------------------------------------------
JANELAS = [
    ("Janela nova · canto 24 px", False, 24),
    ("Janela nova · canto 20 px", False, 20),
    ("Janela nova · canto 16 px", False, 16),
    ("Como é hoje (para comparar)", True, 16),
]
VELOCIDADES = [("Velocidade normal", 1), ("Câmera lenta (5x)", 5), ("Sem animação", 0)]


class Controles(QFrame):
    """Troca canto e velocidade entre uma abertura e outra. So existe no prototipo."""

    def __init__(self, pagina: QWidget, abrir):
        super().__init__(pagina)
        self.setObjectName("Controles")
        linha = QHBoxLayout(self)
        linha.setContentsMargins(16, 10, 10, 10)
        linha.setSpacing(10)
        linha.addWidget(rotulo("PROTÓTIPO", "Etiqueta"))
        self.janela = Seletor()
        self.janela.setMinimumWidth(236)
        for texto, _hoje, _raio in JANELAS:
            self.janela.addItem(texto)
        self.velocidade = Seletor()
        for texto, _fator in VELOCIDADES:
            self.velocidade.addItem(texto)
        abrir_botao = Botao("Abrir Ações da proposta", "workflow", "primario")
        abrir_botao.clicked.connect(abrir)
        for widget in (self.janela, self.velocidade, abrir_botao):
            linha.addWidget(widget)
        self.janela.currentIndexChanged.connect(self._aplicar)
        self.velocidade.currentIndexChanged.connect(self._aplicar)
        TEMA.mudou.connect(self._tema)
        self._tema()
        pagina.installEventFilter(self)
        self._posicionar()
        self.show()

    def definir(self, hoje: bool, raio: int, fator: int) -> None:
        self.janela.setCurrentIndex(next(i for i, (_t, h, r) in enumerate(JANELAS) if h == hoje and (hoje or r == raio)))
        self.velocidade.setCurrentIndex(next(i for i, (_t, f) in enumerate(VELOCIDADES) if f == fator))
        self._aplicar()

    def _aplicar(self, *_args) -> None:
        _texto, Ajuste.hoje, Ajuste.raio = JANELAS[self.janela.currentIndex()]
        fator = VELOCIDADES[self.velocidade.currentIndex()][1]
        base.ANIMAR = fator > 0
        Ajuste.lentidao = max(1, fator)

    def _tema(self) -> None:
        t = TEMA.t
        self.setStyleSheet(
            f"QFrame#Controles {{ background: {t['surface']}; border: 1px solid {t['input_border']}; border-radius: 14px; }}"
            f"QLabel#Etiqueta {{ color: {t['muted']}; font-size: 11px; font-weight: 700; }}"
        )

    def eventFilter(self, objeto, evento):
        if objeto is self.parent() and evento.type() == QEvent.Resize:
            self._posicionar()
        return False

    def _posicionar(self) -> None:
        self.adjustSize()
        pagina = self.parent()
        self.move((pagina.width() - self.width()) // 2, pagina.height() - self.height() - 52)
        self.raise_()


def fotografar(pagina: QWidget) -> QPixmap:
    """Pagina e janelas abertas numa imagem so (`grab()` nao enxerga outra janela)."""

    def nivel(janela: QWidget) -> int:
        total = 0
        while janela.parentWidget():
            janela = janela.parentWidget().window()
            total += 1
        return total

    foto = pagina.grab()
    p = QPainter(foto)
    abertas = [w for w in QApplication.topLevelWidgets() if isinstance(w, Janela) and w.isVisible()]
    for janela in sorted(abertas, key=nivel):
        origem = janela.mapToGlobal(QPoint(0, 0)) - pagina.mapToGlobal(QPoint(0, 0))
        p.setClipRegion(janela.mask().translated(origem) if not janela.mask().isEmpty() else QRegion(foto.rect()))
        p.drawPixmap(origem, janela.grab())
    p.end()
    return foto


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tema", choices=("claro", "escuro"), default="claro")
    parser.add_argument("--raio", type=int, choices=(16, 20, 24), default=24)
    parser.add_argument("--hoje", action="store_true", help="recorte e abertura como no sistema atual")
    parser.add_argument("--lento", action="store_true", help="camera lenta (5x)")
    parser.add_argument("--sem-animacao", action="store_true")
    parser.add_argument("--confirmar", action="store_true", help="abre tambem a confirmacao de pausa")
    parser.add_argument("--shot", metavar="ARQUIVO.png")
    args = parser.parse_args()

    app = QApplication(sys.argv[:1])
    base.FAMILIA = base.carregar_fonte()
    TEMA.nome = args.tema
    pagina = base.Pagina()
    pagina.setWindowTitle("Protótipo - Ações da proposta (dados fictícios)")
    pagina.resize(1366, 740)
    pagina.tabela.selectRow(3)
    pagina.show()
    aberta: list[AcoesProposta] = []

    def fechou(janela: AcoesProposta, resultado: int) -> None:
        aberta.clear()
        controles.show()
        if resultado == QDialog.Accepted and janela.escolhida:
            Aviso(pagina, f"Protótipo: “{janela.escolhida}” não grava nada.")
        janela.deleteLater()

    def abrir() -> None:
        if aberta:
            return
        controles.hide()
        janela = AcoesProposta(pagina)
        aberta.append(janela)
        janela.finished.connect(lambda resultado: fechou(janela, resultado))
        janela.open()

    controles = Controles(pagina, abrir)
    sem_animacao = args.sem_animacao or bool(args.shot)
    controles.definir(args.hoje, args.raio, 0 if sem_animacao else 5 if args.lento else 1)
    pagina.tabela.doubleClicked.connect(lambda *_: abrir())
    for botao in pagina.acoes.findChildren(Botao):
        if botao.text() == "Ações":
            botao.clicked.connect(abrir)
    QTimer.singleShot(0 if args.shot else 400, abrir)
    if args.confirmar:
        QTimer.singleShot(100 if args.shot else 1200, lambda: aberta and aberta[0]._executar(ACOES[0]))
    if args.shot:
        def salvar():
            fotografar(pagina).save(args.shot)
            print(f"fonte={base.FAMILIA} salvo={args.shot}")
            app.quit()

        QTimer.singleShot(700, salvar)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
