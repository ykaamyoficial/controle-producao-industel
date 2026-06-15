from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


ICON_SYMBOLS = {
    "dashboard": "bar",
    "control": "target",
    "production": "spark",
    "galvanization": "diamond",
    "expedition": "truck",
    "stock": "box",
    "partial": "split",
    "history": "clock",
    "audit": "doc",
    "reports": "chart",
    "settings": "sliders",
    "search": "search",
    "clear": "x",
    "new": "plus",
    "status": "check",
    "batch": "list",
    "load": "truck",
    "collapse": "menu",
    "next": "next",
    "previous": "prev",
}

ROOT_DIR = Path(__file__).resolve().parents[2]
APP_ICON_DIR = ROOT_DIR / "app" / "assets" / "icons"

ICON_FILES = {
    "dashboard": "area_painel.png",
    "control": "area_controle_geral.png",
    "production": "area_producao.png",
    "galvanization": "area_galvanizacao.png",
    "expedition": "area_expedicao.png",
    "stock": "area_almoxarifado.png",
    "partial": "status_parcial.png",
    "history": "sistema_historico.png",
    "audit": "sistema_auditoria.png",
    "reports": "sistema_relatorios.png",
    "settings": "sistema_configuracoes.png",
    "users": "sistema_usuarios.png",
    "backup": "sistema_backup.png",
    "restore": "sistema_restaurar.png",
    "database": "sistema_banco_sqlite.png",
    "search": "acao_pesquisar.png",
    "clear": "acao_limpar.png",
    "new": "acao_novo.png",
    "edit": "acao_editar.png",
    "status": "acao_salvar.png",
    "batch": "acao_lote.png",
    "load": "acao_cargas.png",
    "next": "acao_proximo.png",
    "previous": "acao_anterior.png",
    "save": "acao_salvar.png",
    "remove": "acao_remover.png",
    "refresh": "acao_atualizar.png",
    "pdf": "acao_pdf.png",
    "excel": "acao_excel.png",
}


def make_icon(name: str, color: str = "#2563eb", size: int = 20) -> QIcon:
    icon_file = ICON_FILES.get(name)
    if not icon_file and name:
        status_file = f"status_{name.lower()}.png"
        if (APP_ICON_DIR / status_file).exists():
            icon_file = status_file
    if icon_file:
        path = APP_ICON_DIR / icon_file
        if path.exists():
            return QIcon(str(path))
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), max(1.8, size / 12))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    shape = ICON_SYMBOLS.get(name, name)
    w = float(size)

    if shape == "search":
        painter.drawEllipse(QRectF(w * .20, w * .20, w * .40, w * .40))
        painter.drawLine(QPointF(w * .55, w * .55), QPointF(w * .82, w * .82))
    elif shape == "plus":
        painter.drawLine(QPointF(w * .50, w * .22), QPointF(w * .50, w * .78))
        painter.drawLine(QPointF(w * .22, w * .50), QPointF(w * .78, w * .50))
    elif shape == "x":
        painter.drawLine(QPointF(w * .28, w * .28), QPointF(w * .72, w * .72))
        painter.drawLine(QPointF(w * .72, w * .28), QPointF(w * .28, w * .72))
    elif shape == "bar":
        painter.drawLine(QPointF(w * .25, w * .75), QPointF(w * .25, w * .48))
        painter.drawLine(QPointF(w * .50, w * .75), QPointF(w * .50, w * .30))
        painter.drawLine(QPointF(w * .75, w * .75), QPointF(w * .75, w * .18))
        painter.drawLine(QPointF(w * .18, w * .78), QPointF(w * .84, w * .78))
    elif shape == "target":
        painter.drawEllipse(QRectF(w * .20, w * .20, w * .60, w * .60))
        painter.drawEllipse(QRectF(w * .38, w * .38, w * .24, w * .24))
    elif shape == "spark":
        for angle in (0, 45, 90, 135):
            painter.save()
            painter.translate(w / 2, w / 2)
            painter.rotate(angle)
            painter.drawLine(QPointF(0, -w * .32), QPointF(0, -w * .12))
            painter.drawLine(QPointF(0, w * .12), QPointF(0, w * .32))
            painter.restore()
    elif shape == "diamond":
        path = QPainterPath(QPointF(w * .50, w * .15))
        path.lineTo(QPointF(w * .82, w * .50))
        path.lineTo(QPointF(w * .50, w * .85))
        path.lineTo(QPointF(w * .18, w * .50))
        path.closeSubpath()
        painter.drawPath(path)
    elif shape == "truck":
        painter.drawRoundedRect(QRectF(w * .14, w * .35, w * .48, w * .26), 2, 2)
        painter.drawPath(QPainterPath(QPointF(w * .62, w * .42)))
        painter.drawRect(QRectF(w * .62, w * .43, w * .20, w * .18))
        painter.drawEllipse(QRectF(w * .25, w * .58, w * .14, w * .14))
        painter.drawEllipse(QRectF(w * .65, w * .58, w * .14, w * .14))
    elif shape == "box":
        painter.drawRoundedRect(QRectF(w * .24, w * .25, w * .52, w * .52), 3, 3)
        painter.drawLine(QPointF(w * .24, w * .42), QPointF(w * .76, w * .42))
        painter.drawLine(QPointF(w * .50, w * .25), QPointF(w * .50, w * .42))
    elif shape == "split":
        painter.drawLine(QPointF(w * .50, w * .18), QPointF(w * .50, w * .45))
        painter.drawLine(QPointF(w * .50, w * .45), QPointF(w * .28, w * .72))
        painter.drawLine(QPointF(w * .50, w * .45), QPointF(w * .72, w * .72))
        painter.drawEllipse(QRectF(w * .43, w * .10, w * .14, w * .14))
        painter.drawEllipse(QRectF(w * .20, w * .68, w * .14, w * .14))
        painter.drawEllipse(QRectF(w * .66, w * .68, w * .14, w * .14))
    elif shape == "clock":
        painter.drawEllipse(QRectF(w * .20, w * .20, w * .60, w * .60))
        painter.drawLine(QPointF(w * .50, w * .50), QPointF(w * .50, w * .32))
        painter.drawLine(QPointF(w * .50, w * .50), QPointF(w * .64, w * .58))
    elif shape == "doc":
        painter.drawRoundedRect(QRectF(w * .28, w * .16, w * .44, w * .68), 3, 3)
        painter.drawLine(QPointF(w * .38, w * .38), QPointF(w * .62, w * .38))
        painter.drawLine(QPointF(w * .38, w * .52), QPointF(w * .62, w * .52))
    elif shape == "chart":
        painter.drawLine(QPointF(w * .22, w * .74), QPointF(w * .78, w * .74))
        painter.drawLine(QPointF(w * .28, w * .70), QPointF(w * .42, w * .48))
        painter.drawLine(QPointF(w * .42, w * .48), QPointF(w * .58, w * .56))
        painter.drawLine(QPointF(w * .58, w * .56), QPointF(w * .76, w * .28))
    elif shape == "sliders":
        for y, x in ((.30, .62), (.50, .38), (.70, .55)):
            painter.drawLine(QPointF(w * .22, w * y), QPointF(w * .78, w * y))
            painter.drawEllipse(QRectF(w * x - 3, w * y - 3, 6, 6))
    elif shape == "menu":
        painter.drawLine(QPointF(w * .22, w * .32), QPointF(w * .78, w * .32))
        painter.drawLine(QPointF(w * .22, w * .50), QPointF(w * .78, w * .50))
        painter.drawLine(QPointF(w * .22, w * .68), QPointF(w * .78, w * .68))
    elif shape == "next":
        painter.drawLine(QPointF(w * .38, w * .25), QPointF(w * .62, w * .50))
        painter.drawLine(QPointF(w * .62, w * .50), QPointF(w * .38, w * .75))
    elif shape == "prev":
        painter.drawLine(QPointF(w * .62, w * .25), QPointF(w * .38, w * .50))
        painter.drawLine(QPointF(w * .38, w * .50), QPointF(w * .62, w * .75))
    else:
        painter.drawEllipse(QRectF(w * .30, w * .30, w * .40, w * .40))

    painter.end()
    return QIcon(pix)
