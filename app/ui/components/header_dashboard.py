from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QVBoxLayout

from app.ui.icons import make_icon
from app.ui.theme_tokens import dashboard_tokens


class HeaderDashboard(QFrame):
    def __init__(self, palette: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("DashboardHero")
        self.setMinimumHeight(116)
        self.icon = QLabel()
        self.set_palette(palette)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(self.tokens["shadow"]))
        self.setGraphicsEffect(shadow)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(18)
        self.icon.setAlignment(Qt.AlignCenter)
        self.icon.setFixedSize(54, 54)
        copy = QVBoxLayout()
        copy.setSpacing(3)
        title = QLabel("Dashboard Operacional")
        title.setStyleSheet("font-size: 23px; font-weight: 800;")
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("DashboardSubtitle")
        self.subtitle.setWordWrap(True)
        copy.addWidget(title)
        copy.addWidget(self.subtitle)
        layout.addWidget(self.icon)
        layout.addLayout(copy, 1)
        self.updated = QLabel("")
        self.updated.setObjectName("DashboardUpdated")
        self.updated.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.updated)

    def set_palette(self, palette: dict):
        self.tokens = dashboard_tokens(palette)
        self.setStyleSheet(
            f"""
            QFrame#DashboardHero {{
                border: 0;
                border-radius: 18px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {self.tokens['header_start']}, stop:1 {self.tokens['header_end']});
            }}
            QFrame#DashboardHero QLabel {{ color: {self.tokens['header_text']}; background: transparent; }}
            QLabel#DashboardSubtitle {{ color: {self.tokens['header_muted']}; font-size: 11px; }}
            QLabel#DashboardUpdated {{ color: {self.tokens['header_muted']}; font-size: 10px; }}
            """
        )
        self.icon.setPixmap(make_icon("dashboard", self.tokens["header_text"], 34).pixmap(34, 34))
        self.icon.setStyleSheet(f"background: {self.tokens['header_muted']}; border-radius: 14px;")

    def update_content(self, subtitle: str, updated_text: str):
        self.subtitle.setText(subtitle)
        self.updated.setText(updated_text)
