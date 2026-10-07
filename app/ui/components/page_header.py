from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.ui.components.operational_header import configure_operational_header


def setup_page_header(
    frame: QFrame,
    title: str,
    subtitle: str = "",
    *,
    side: Iterable[QWidget] = (),
    actions: Iterable[QWidget] = (),
) -> QFrame:
    """Monta, em `frame`, a faixa de topo das paginas de painel/relatorio:
    titulo na cor de destaque, subtitulo, informacoes de apoio (`side`) e acoes
    a direita. O que mais a pagina precisar (filtros) entra em
    `frame.body_layout`, abaixo da linha."""
    body = QVBoxLayout(frame)
    configure_operational_header(frame, body, margins=(16, 12, 16, 12), spacing=10)

    title_label = QLabel(title)
    title_label.setObjectName("FilterTitle")
    title_label.setProperty("tone", "accent")
    subtitle_label = QLabel(subtitle)
    subtitle_label.setObjectName("FilterSubtitle")
    subtitle_label.setWordWrap(True)
    copy = QVBoxLayout()
    copy.setSpacing(1)
    copy.addWidget(title_label)
    copy.addWidget(subtitle_label)

    top = QHBoxLayout()
    top.setSpacing(8)
    top.addLayout(copy, 1)
    for widget in (*side, *actions):
        top.addWidget(widget, 0, Qt.AlignVCenter)
    body.addLayout(top)

    frame.title_label = title_label
    frame.subtitle_label = subtitle_label
    frame.body_layout = body
    return frame


def page_header(
    title: str,
    subtitle: str = "",
    *,
    side: Iterable[QWidget] = (),
    actions: Iterable[QWidget] = (),
) -> QFrame:
    return setup_page_header(QFrame(), title, subtitle, side=side, actions=actions)
