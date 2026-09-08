"""Gera o icone de usuario (avatar padrao) usado em app/assets/icons.

Recria em vetor (QPainter) o icone de avatar padrao pedido pelo usuario:
circulo azul-marinho de fundo com a silhueta de uma pessoa (cabeca + ombros)
em cinza bem claro, nos mesmos tamanhos ja usados pelo app (16..512), e
grava tanto a variante "premium" por tamanho quanto o arquivo achatado usado
como fallback (app/assets/icons/sistema_usuarios.png).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "app" / "assets" / "icons"
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)

BG_COLOR = QColor("#5B6482")
FG_COLOR = QColor("#E7ECEC")

HEAD_W = 0.34
HEAD_H = 0.42
HEAD_TOP = 0.14

SHOULDER_RX = 0.34
SHOULDER_RY = 0.32
SHOULDER_CY = 0.86


def render(size: int) -> "QPixmap":
    from PySide6.QtGui import QPixmap

    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)

    cx = cy = size / 2.0
    # Raio levemente menor que size/2 pra evitar uma costura de antialiasing
    # visivel na borda do circulo quando o icone e composto sobre fundos claros.
    radius = size * 0.5 - max(0.5, size * 0.004)

    circle = QPainterPath()
    circle.addEllipse(QPointF(cx, cy), radius, radius)
    painter.setClipPath(circle)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(BG_COLOR))
    painter.drawPath(circle)

    silhouette = QPainterPath()
    head_rect = QRectF(
        cx - HEAD_W * size / 2.0,
        HEAD_TOP * size,
        HEAD_W * size,
        HEAD_H * size,
    )
    silhouette.addRoundedRect(head_rect, HEAD_W * size / 2.0, HEAD_W * size / 2.0)

    shoulders = QPainterPath()
    shoulders.addEllipse(
        QPointF(cx, SHOULDER_CY * size), SHOULDER_RX * size, SHOULDER_RY * size
    )
    silhouette = silhouette.united(shoulders)

    painter.setBrush(QBrush(FG_COLOR))
    painter.drawPath(silhouette)

    painter.end()
    return pix


def main() -> None:
    app = QApplication.instance() or QApplication([])
    for size in SIZES:
        pix = render(size)
        target_dir = ICON_DIR / "premium" / str(size)
        target_dir.mkdir(parents=True, exist_ok=True)
        out_path = target_dir / "sistema_usuarios.png"
        pix.save(str(out_path), "PNG")
        print(f"gravado {out_path}")

    flat = render(512)
    flat_path = ICON_DIR / "sistema_usuarios.png"
    flat.save(str(flat_path), "PNG")
    print(f"gravado {flat_path}")
    del app


if __name__ == "__main__":
    main()
