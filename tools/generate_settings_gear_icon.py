"""Gera o icone de engrenagem (Configuracoes) usado em app/assets/icons.

Recria em vetor (QPainter) o icone de engrenagem azul-claro com miolo branco
pedido pelo usuario, nos mesmos tamanhos ja usados pelo app (16..512), e
grava tanto a variante "premium" por tamanho quanto o arquivo achatado usado
como fallback (app/assets/icons/sistema_configuracoes.png).
"""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "app" / "assets" / "icons"
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)

BODY_COLOR = QColor("#AAD6E0")
SHADE_COLOR = QColor("#8FC0CC")
OUTLINE_COLOR = QColor("#141414")
HOLE_COLOR = QColor("#FFFFFF")

TEETH = 8
OUTER_R = 0.48
ROOT_R = 0.27
TOOTH_HALF_ANGLE_DEG = 12.0
RING_R = 0.235
HOLE_R = 0.145


def _gear_path(cx: float, cy: float, unit: float) -> QPainterPath:
    # Um unico poligono continuo (nunca uniao booleana de formas separadas —
    # isso produzia bordas internas espurias e o contorno preto "engolia" o
    # preenchimento). Vertices alternam entre raio externo (dente) e raio da
    # raiz (vale), ligados por linhas retas; com 8 dentes o vale reto ja fica
    # visualmente equivalente a um arco nesse tamanho de icone.
    path = QPainterPath()
    step_deg = 360.0 / TEETH
    half = TOOTH_HALF_ANGLE_DEG
    outer_r = OUTER_R * unit
    root_r = ROOT_R * unit

    def point(radius: float, angle_deg: float) -> QPointF:
        angle = math.radians(angle_deg)
        return QPointF(cx + radius * math.cos(angle), cy + radius * math.sin(angle))

    first = True
    for i in range(TEETH):
        center_deg = i * step_deg
        a1 = center_deg - half
        a2 = center_deg + half
        p_root_start = point(root_r, a1)
        p_tip_start = point(outer_r, a1)
        p_tip_end = point(outer_r, a2)
        p_root_end = point(root_r, a2)
        if first:
            path.moveTo(p_root_start)
            first = False
        path.lineTo(p_tip_start)
        path.lineTo(p_tip_end)
        path.lineTo(p_root_end)
        next_a1 = (i + 1) * step_deg - half
        path.lineTo(point(root_r, next_a1))
    path.closeSubpath()
    return path


def render(size: int) -> "QPixmap":
    from PySide6.QtGui import QPixmap

    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)

    # Escala do desenho dentro do canvas: a engrenagem original ocupava so
    # ~48% da largura (muito mais "respiro" do que os icones irmaos, que vao
    # quase de ponta a ponta). O usuario pediu 2,5x maior; 2,5x literal
    # estouraria o canvas (os dentes seriam cortados), entao usamos o maior
    # fator que ainda cabe com uma margem minima pro traco/antialiasing.
    GEAR_SCALE = 1.9
    unit = size * 0.5 * GEAR_SCALE
    cx = cy = size / 2.0

    gear = _gear_path(cx, cy, unit)

    outline_w = max(1.0, size * 0.018)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(BODY_COLOR))
    painter.drawPath(gear)

    shade = QPainterPath()
    shade.addRect(QRectF(cx, cy - unit, unit, unit * 2))
    painter.save()
    painter.setClipPath(gear)
    painter.setBrush(QBrush(SHADE_COLOR))
    painter.setOpacity(0.55)
    painter.drawPath(shade)
    painter.restore()

    pen = QPen(OUTLINE_COLOR, outline_w)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(gear)

    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(QPointF(cx, cy), RING_R * unit, RING_R * unit)

    painter.setPen(pen)
    painter.setBrush(QBrush(HOLE_COLOR))
    painter.drawEllipse(QPointF(cx, cy), HOLE_R * unit, HOLE_R * unit)

    painter.end()
    return pix


def main() -> None:
    app = QApplication.instance() or QApplication([])
    for size in SIZES:
        pix = render(size)
        target_dir = ICON_DIR / "premium" / str(size)
        target_dir.mkdir(parents=True, exist_ok=True)
        out_path = target_dir / "sistema_configuracoes.png"
        pix.save(str(out_path), "PNG")
        print(f"gravado {out_path}")

    flat = render(512)
    flat_path = ICON_DIR / "sistema_configuracoes.png"
    flat.save(str(flat_path), "PNG")
    print(f"gravado {flat_path}")
    del app


if __name__ == "__main__":
    main()
