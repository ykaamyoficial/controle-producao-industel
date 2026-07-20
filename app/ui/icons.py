from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


ICON_SYMBOLS = {
    "dashboard": "bar",
    "control": "target",
    "production": "spark",
    "galvanization": "diamond",
    "expedition": "truck",
    "stock": "box",
    "fiscal": "doc",
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
    "download": "download",
    "moon": "moon",
    "sun": "sun",
    "fiscal_pending": "fiscal_pending",
    "fiscal_partial": "fiscal_partial",
    "fiscal_done": "fiscal_done",
    "fiscal_critical": "fiscal_critical",
    "fiscal_blocked": "fiscal_blocked",
}

ROOT_DIR = Path(__file__).resolve().parents[2]
APP_ICON_DIR = ROOT_DIR / "app" / "assets" / "icons"
PREMIUM_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)

ICON_FILES = {
    "dashboard": "area_painel.png",
    "control": "area_controle_geral.png",
    "production": "area_producao.png",
    "galvanization": "area_galvanizacao.png",
    "expedition": "area_expedicao.png",
    "stock": "area_almoxarifado.png",
    "fiscal": "sistema_fiscal.png",
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
    "fiscal_pending": "status_pendente.png",
    "fiscal_partial": "status_parcial.png",
    "fiscal_done": "status_finalizado.png",
    "fiscal_critical": "status_pendente.png",
    "fiscal_blocked": "status_cancelado.png",
}


def make_icon(name: str, color: str = "#2563eb", size: int = 20) -> QIcon:
    icon_file = ICON_FILES.get(name)
    if not icon_file and name:
        status_file = f"status_{name.lower()}.png"
        if (APP_ICON_DIR / status_file).exists():
            icon_file = status_file
    if icon_file:
        icon = QIcon()
        loaded = False
        for icon_size in PREMIUM_ICON_SIZES:
            path = APP_ICON_DIR / "premium" / str(icon_size) / icon_file
            if path.exists():
                icon.addFile(str(path), QSize(icon_size, icon_size))
                loaded = True
        path = APP_ICON_DIR / icon_file
        if path.exists():
            icon.addFile(str(path), QSize(512, 512))
            loaded = True
        if loaded:
            return icon
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
    elif shape == "fiscal_pending":
        painter.drawRoundedRect(QRectF(w * .24, w * .12, w * .46, w * .70), 3, 3)
        painter.drawLine(QPointF(w * .36, w * .34), QPointF(w * .58, w * .34))
        painter.drawLine(QPointF(w * .36, w * .48), QPointF(w * .58, w * .48))
        painter.drawEllipse(QRectF(w * .62, w * .60, w * .20, w * .20))
    elif shape == "fiscal_partial":
        painter.drawRoundedRect(QRectF(w * .24, w * .12, w * .46, w * .70), 3, 3)
        painter.drawLine(QPointF(w * .36, w * .34), QPointF(w * .58, w * .34))
        painter.drawLine(QPointF(w * .36, w * .48), QPointF(w * .58, w * .48))
        painter.drawLine(QPointF(w * .68, w * .58), QPointF(w * .68, w * .72))
        painter.drawPoint(QPointF(w * .68, w * .80))
    elif shape == "fiscal_done":
        painter.drawRoundedRect(QRectF(w * .24, w * .12, w * .46, w * .70), 3, 3)
        painter.drawLine(QPointF(w * .35, w * .50), QPointF(w * .45, w * .62))
        painter.drawLine(QPointF(w * .45, w * .62), QPointF(w * .72, w * .32))
    elif shape == "fiscal_critical":
        path = QPainterPath(QPointF(w * .50, w * .14))
        path.lineTo(QPointF(w * .84, w * .78))
        path.lineTo(QPointF(w * .16, w * .78))
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(QPointF(w * .50, w * .34), QPointF(w * .50, w * .56))
        painter.drawPoint(QPointF(w * .50, w * .68))
    elif shape == "fiscal_blocked":
        painter.drawRoundedRect(QRectF(w * .24, w * .12, w * .46, w * .70), 3, 3)
        painter.drawEllipse(QRectF(w * .48, w * .48, w * .34, w * .34))
        painter.drawLine(QPointF(w * .54, w * .76), QPointF(w * .76, w * .54))
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
    elif shape == "download":
        painter.drawLine(QPointF(w * .50, w * .18), QPointF(w * .50, w * .62))
        painter.drawLine(QPointF(w * .32, w * .45), QPointF(w * .50, w * .64))
        painter.drawLine(QPointF(w * .68, w * .45), QPointF(w * .50, w * .64))
        painter.drawLine(QPointF(w * .25, w * .78), QPointF(w * .75, w * .78))
    elif shape == "moon":
        path = QPainterPath()
        path.addEllipse(QRectF(w * .22, w * .16, w * .58, w * .68))
        cut = QPainterPath()
        cut.addEllipse(QRectF(w * .42, w * .08, w * .48, w * .62))
        painter.drawPath(path.subtracted(cut))
    elif shape == "sun":
        painter.drawEllipse(QRectF(w * .34, w * .34, w * .32, w * .32))
        for angle in range(0, 360, 45):
            painter.save()
            painter.translate(w / 2, w / 2)
            painter.rotate(angle)
            painter.drawLine(QPointF(0, -w * .42), QPointF(0, -w * .30))
            painter.restore()
    else:
        painter.drawEllipse(QRectF(w * .30, w * .30, w * .40, w * .40))

    painter.end()
    return QIcon(pix)
