from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QLabel


def initials(name: str | None) -> str:
    parts = (name or "").split()
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


class AvatarLabel(QLabel):
    """Circulo com as iniciais (ou a foto) do usuario. Continua sendo um
    QLabel - `text()` devolve as iniciais, vazio quando ha foto - mas e pintado
    a mao: o tamanho muda por chamada, entao nao cabe em regra de QSS."""

    def __init__(self, name: str | None, service, size: int = 28, parent=None):
        super().__init__(initials(name), parent)
        palette = service.palette
        self._background = QColor(palette.get("accent", "#0078d4"))
        self._foreground = QColor(palette.get("accent_text", "#ffffff"))
        self._photo: QPixmap | None = None
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)

    def set_photo(self, pixmap: QPixmap) -> None:
        size = self.width()
        self._photo = pixmap.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        self.setText("")
        self.update()

    def clear_photo(self) -> None:
        self._photo = None
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        if self._photo is not None:
            clip = QPainterPath()
            clip.addEllipse(rect)
            painter.setClipPath(clip)
            painter.drawPixmap(0, 0, self._photo)
            painter.end()
            return
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._background)
        painter.drawEllipse(rect)
        font = QFont(self.font())
        font.setPixelSize(max(9, self.width() // 3))
        font.setWeight(QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(self._foreground)
        painter.drawText(self.rect(), Qt.AlignCenter, self.text())
        painter.end()


def make_avatar_label(name: str | None, service, size: int = 28, user_id: int | None = None) -> QLabel:
    label = AvatarLabel(name, service, size)
    if user_id and hasattr(service, "avatar_bytes_for_user"):
        try:
            content = service.avatar_bytes_for_user(int(user_id))
            if content:
                pixmap = QPixmap()
                if pixmap.loadFromData(content):
                    label.set_photo(pixmap)
        except Exception:
            pass
    return label
