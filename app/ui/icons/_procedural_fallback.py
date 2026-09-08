"""Fallback vetorial (QPainter) usado apenas quando um nome de icone nao
resolve nem para um AppIcons/Lucide conhecido nem para um PNG legado em
app/assets/icons/. Preservado tal como estava antes da migracao pra Lucide -
e o ultimo recurso, nunca o caminho normal.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
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
    "chat": "chat",
    "bell": "bell",
    "question": "question",
    "gear": "gear",
    "attach": "attach",
    "pause": "pause",
    "scale": "scale",
    "emoji": "emoji",
    "mic": "mic",
    "send": "send",
    "at": "at",
    "info": "info",
    "minimize": "minimize",
    "maximize": "maximize",
    "restore": "restore",
    "window_close": "x",
    "fiscal_pending": "fiscal_pending",
    "fiscal_partial": "fiscal_partial",
    "fiscal_done": "fiscal_done",
    "fiscal_critical": "fiscal_critical",
    "fiscal_blocked": "fiscal_blocked",
}


def draw_procedural_icon(name: str, color: str = "#2563eb", size: int = 20) -> QIcon:
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
    elif shape == "chat":
        painter.drawRoundedRect(QRectF(w * .16, w * .20, w * .68, w * .46), 8, 8)
        tail = QPainterPath(QPointF(w * .32, w * .66))
        tail.lineTo(QPointF(w * .40, w * .82))
        tail.lineTo(QPointF(w * .46, w * .66))
        tail.closeSubpath()
        painter.drawPath(tail)
    elif shape == "bell":
        path = QPainterPath()
        path.moveTo(w * .30, w * .58)
        path.cubicTo(w * .30, w * .34, w * .38, w * .20, w * .50, w * .20)
        path.cubicTo(w * .62, w * .20, w * .70, w * .34, w * .70, w * .58)
        path.lineTo(w * .78, w * .70)
        path.lineTo(w * .22, w * .70)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(QPointF(w * .42, w * .78), QPointF(w * .58, w * .78))
    elif shape == "question":
        painter.drawEllipse(QRectF(w * .20, w * .20, w * .60, w * .60))
        path = QPainterPath(QPointF(w * .38, w * .40))
        path.cubicTo(QPointF(w * .38, w * .30), QPointF(w * .62, w * .30), QPointF(w * .62, w * .42))
        path.cubicTo(QPointF(w * .62, w * .50), QPointF(w * .50, w * .48), QPointF(w * .50, w * .60))
        painter.drawPath(path)
        painter.drawPoint(QPointF(w * .50, w * .70))
    elif shape == "gear":
        painter.drawEllipse(QRectF(w * .36, w * .36, w * .28, w * .28))
        for angle in range(0, 360, 45):
            painter.save()
            painter.translate(w / 2, w / 2)
            painter.rotate(angle)
            painter.drawLine(QPointF(0, -w * .40), QPointF(0, -w * .30))
            painter.restore()
    elif shape == "pause":
        painter.drawRoundedRect(QRectF(w * .32, w * .20, w * .14, w * .60), 2, 2)
        painter.drawRoundedRect(QRectF(w * .54, w * .20, w * .14, w * .60), 2, 2)
    elif shape == "scale":
        painter.drawLine(QPointF(w * .50, w * .16), QPointF(w * .50, w * .80))
        painter.drawLine(QPointF(w * .50, w * .82), QPointF(w * .32, w * .82))
        painter.drawLine(QPointF(w * .50, w * .82), QPointF(w * .68, w * .82))
        painter.drawLine(QPointF(w * .22, w * .28), QPointF(w * .78, w * .28))
        painter.drawLine(QPointF(w * .22, w * .28), QPointF(w * .14, w * .54))
        painter.drawLine(QPointF(w * .22, w * .28), QPointF(w * .30, w * .54))
        painter.drawArc(QRectF(w * .12, w * .48, w * .20, w * .16), 190 * 16, 160 * 16)
        painter.drawLine(QPointF(w * .78, w * .28), QPointF(w * .70, w * .54))
        painter.drawLine(QPointF(w * .78, w * .28), QPointF(w * .86, w * .54))
        painter.drawArc(QRectF(w * .68, w * .48, w * .20, w * .16), 190 * 16, 160 * 16)
    elif shape == "attach":
        path = QPainterPath()
        path.moveTo(w * .64, w * .24)
        path.lineTo(w * .34, w * .54)
        path.cubicTo(QPointF(w * .20, w * .68), QPointF(w * .20, w * .84), QPointF(w * .34, w * .90))
        path.cubicTo(QPointF(w * .46, w * .95), QPointF(w * .58, w * .90), QPointF(w * .66, w * .82))
        path.lineTo(w * .84, w * .64)
        path.cubicTo(QPointF(w * .92, w * .56), QPointF(w * .92, w * .44), QPointF(w * .84, w * .36))
        path.cubicTo(QPointF(w * .76, w * .28), QPointF(w * .64, w * .28), QPointF(w * .56, w * .36))
        path.lineTo(w * .40, w * .52)
        painter.drawPath(path)
    elif shape == "emoji":
        painter.drawEllipse(QRectF(w * .18, w * .18, w * .64, w * .64))
        painter.drawEllipse(QRectF(w * .36, w * .38, w * .06, w * .06))
        painter.drawEllipse(QRectF(w * .58, w * .38, w * .06, w * .06))
        smile = QPainterPath(QPointF(w * .34, w * .58))
        smile.cubicTo(QPointF(w * .42, w * .70), QPointF(w * .58, w * .70), QPointF(w * .66, w * .58))
        painter.drawPath(smile)
    elif shape == "mic":
        painter.drawRoundedRect(QRectF(w * .38, w * .16, w * .24, w * .42), w * .12, w * .12)
        path = QPainterPath(QPointF(w * .26, w * .46))
        path.cubicTo(QPointF(w * .26, w * .68), QPointF(w * .74, w * .68), QPointF(w * .74, w * .46))
        painter.drawPath(path)
        painter.drawLine(QPointF(w * .50, w * .68), QPointF(w * .50, w * .82))
        painter.drawLine(QPointF(w * .36, w * .82), QPointF(w * .64, w * .82))
    elif shape == "send":
        path = QPainterPath(QPointF(w * .18, w * .50))
        path.lineTo(w * .84, w * .18)
        path.lineTo(w * .60, w * .84)
        path.lineTo(w * .48, w * .56)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(QPointF(w * .48, w * .56), QPointF(w * .84, w * .18))
    elif shape == "at":
        painter.drawEllipse(QRectF(w * .36, w * .36, w * .28, w * .28))
        path = QPainterPath(QPointF(w * .64, w * .50))
        path.lineTo(w * .64, w * .66)
        path.cubicTo(QPointF(w * .64, w * .76), QPointF(w * .82, w * .76), QPointF(w * .82, w * .62))
        path.cubicTo(QPointF(w * .82, w * .34), QPointF(w * .50, w * .18), QPointF(w * .26, w * .38))
        path.cubicTo(QPointF(w * .10, w * .54), QPointF(w * .16, w * .82), QPointF(w * .42, w * .88))
        painter.drawPath(path)
    elif shape == "sun":
        painter.drawEllipse(QRectF(w * .34, w * .34, w * .32, w * .32))
        for angle in range(0, 360, 45):
            painter.save()
            painter.translate(w / 2, w / 2)
            painter.rotate(angle)
            painter.drawLine(QPointF(0, -w * .42), QPointF(0, -w * .30))
            painter.restore()
    elif shape == "info":
        painter.drawEllipse(QRectF(w * .20, w * .20, w * .60, w * .60))
        painter.drawPoint(QPointF(w * .50, w * .36))
        painter.drawLine(QPointF(w * .50, w * .46), QPointF(w * .50, w * .68))
    elif shape == "minimize":
        painter.drawLine(QPointF(w * .24, w * .70), QPointF(w * .76, w * .70))
    elif shape == "maximize":
        painter.drawRect(QRectF(w * .24, w * .24, w * .52, w * .52))
    elif shape == "restore":
        painter.drawRect(QRectF(w * .32, w * .24, w * .44, w * .44))
        path = QPainterPath(QPointF(w * .24, w * .40))
        path.lineTo(QPointF(w * .24, w * .76))
        path.lineTo(QPointF(w * .60, w * .76))
        path.lineTo(QPointF(w * .60, w * .68))
        painter.drawPath(path)
    else:
        painter.drawEllipse(QRectF(w * .30, w * .30, w * .40, w * .40))

    painter.end()
    return QIcon(pix)
