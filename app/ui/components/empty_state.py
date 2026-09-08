from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.ui.icons import make_icon


class EmptyState(QWidget):
    def __init__(
        self,
        title: str,
        description: str = "",
        palette: dict | None = None,
        *,
        icon: str = "search",
        action: QWidget | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._palette = palette or {}
        self.setObjectName("OperationalEmptyState")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(8)
        layout.addStretch(1)

        block = QWidget()
        block.setObjectName("EmptyStateContent")
        block.setMaximumWidth(420)
        block_layout = QVBoxLayout(block)
        block_layout.setContentsMargins(18, 18, 18, 18)
        block_layout.setAlignment(Qt.AlignCenter)
        block_layout.setSpacing(7)

        icon_label = QLabel()
        icon_label.setObjectName("EmptyStateIcon")
        muted = self._palette.get("muted", "#64748b")
        icon_label.setPixmap(make_icon(icon, muted, 32).pixmap(32, 32))
        icon_label.setAlignment(Qt.AlignCenter)

        heading = QLabel(title)
        heading.setObjectName("EmptyStateTitle")
        heading.setAlignment(Qt.AlignCenter)
        heading.setWordWrap(True)

        caption = QLabel(description)
        caption.setObjectName("EmptyStateDescription")
        caption.setAlignment(Qt.AlignCenter)
        caption.setWordWrap(True)

        block_layout.addWidget(icon_label)
        block_layout.addWidget(heading)
        if description:
            block_layout.addWidget(caption)
        if action is not None:
            block_layout.addSpacing(5)
            block_layout.addWidget(action, alignment=Qt.AlignCenter)

        layout.addWidget(block, 0, Qt.AlignCenter)
        layout.addStretch(1)

    def set_text(self, title: str, description: str = "") -> None:
        heading = self.findChild(QLabel, "EmptyStateTitle")
        caption = self.findChild(QLabel, "EmptyStateDescription")
        if heading is not None:
            heading.setText(title)
        if caption is not None:
            caption.setText(description)
            caption.setVisible(bool(description))
