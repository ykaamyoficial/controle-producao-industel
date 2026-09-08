from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QRegion
from PySide6.QtWidgets import QLabel


def initials(name: str | None) -> str:
    parts = (name or "").split()
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def make_avatar_label(name: str | None, service, size: int = 28, user_id: int | None = None) -> QLabel:
    label = QLabel(initials(name))
    label.setFixedSize(size, size)
    label.setAlignment(Qt.AlignCenter)
    label.setStyleSheet(
        f"background: {service.palette.get('accent', '#0078d4')}; "
        f"color: {service.palette.get('accent_text', '#ffffff')}; "
        f"border-radius: {size // 2}px; font-weight: 700; font-size: {max(9, size // 3)}px;"
    )
    if user_id and hasattr(service, "avatar_bytes_for_user"):
        try:
            content = service.avatar_bytes_for_user(int(user_id))
            if content:
                pixmap = QPixmap()
                if pixmap.loadFromData(content):
                    label.setPixmap(pixmap.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
                    label.setText("")
                    label.setStyleSheet(f"border-radius: {size // 2}px;")
                    label.setMask(QRegion(0, 0, size, size, QRegion.Ellipse))
        except Exception:
            pass
    return label
