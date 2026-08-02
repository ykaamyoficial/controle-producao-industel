from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from app.ui.animations import fade_in
from app.ui.components.modern_button import ModernButton
from app.ui.icons import make_icon
from app.ui.proposal_chat_dialog import ProposalChatDialog, _format_datetime


class NotificationPopup(QFrame):
    def __init__(self, service, parent=None):
        super().__init__(parent, Qt.Popup)
        self.service = service
        self.setObjectName("Panel")
        self.setMinimumWidth(360)
        self.setMaximumHeight(420)
        self._build()
        self.refresh()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("Notificacoes")
        title.setStyleSheet("font-weight: 800;")
        header.addWidget(title)
        header.addStretch()
        mark_all_btn = ModernButton("Marcar todas como lidas", "status")
        mark_all_btn.clicked.connect(self._mark_all_read)
        header.addWidget(mark_all_btn)
        layout.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.list_widget = QWidget()
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(6)
        self.list_layout.addStretch()
        self.scroll.setWidget(self.list_widget)
        layout.addWidget(self.scroll, 1)

    def refresh(self):
        try:
            notifications = self.service.chat_notifications(limit=30)
        except Exception:
            notifications = []
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        if not notifications:
            empty = QLabel("Sem notificacoes.")
            empty.setObjectName("Caption")
            self.list_layout.insertWidget(0, empty)
            return
        for notification in notifications:
            self.list_layout.insertWidget(self.list_layout.count() - 1, self._build_row(notification))

    def _build_row(self, notification: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("Panel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        header = QHBoxLayout()
        icon_label = QLabel()
        icon_name = {"MENSAGEM": "chat", "OBSERVACAO": "doc", "MENCAO": "chat"}.get(notification.get("notification_type"), "chat")
        unread = notification.get("read_at") is None
        color = self.service.palette.get("accent", "#0078d4") if unread else self.service.palette.get("muted", "#94a3b8")
        icon_label.setPixmap(make_icon(icon_name, color, 16).pixmap(16, 16))
        header.addWidget(icon_label)
        title_text = notification.get("proposal_number") or ("Chat Geral" if notification.get("kind") == "GERAL" else "Chat")
        title_label = QLabel(title_text)
        title_label.setStyleSheet("font-weight: 700;")
        header.addWidget(title_label)
        header.addStretch()
        time_label = QLabel(_format_datetime(notification.get("created_at")))
        time_label.setObjectName("Caption")
        header.addWidget(time_label)
        layout.addLayout(header)

        author = notification.get("author_name") or ""
        body = notification.get("message_body") or ""
        snippet = f"{author}: {body}" if author else body
        body_label = QLabel(snippet)
        body_label.setWordWrap(True)
        layout.addWidget(body_label)

        card.setCursor(Qt.PointingHandCursor)
        card.mousePressEvent = lambda _event, n=notification: self._open_notification(n)
        return card

    def _open_notification(self, notification: dict):
        self.close()
        proposal_id = notification.get("proposal_id")
        conversation_id = None if proposal_id else notification.get("conversation_id")
        dialog = ProposalChatDialog(self.service, proposal_id=proposal_id, conversation_id=conversation_id, parent=self.parentWidget())
        dialog.exec()

    def _mark_all_read(self):
        try:
            self.service.chat_mark_all_notifications_read()
        except Exception:
            pass
        self.refresh()


class NotificationBell(QPushButton):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.setObjectName("GhostButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(20, 20))
        self.setMinimumHeight(34)
        self._popup: NotificationPopup | None = None
        self.set_unread_count(0)
        self.clicked.connect(self.toggle_popup)

    def set_unread_count(self, count: int):
        self.setIcon(make_icon("bell", self.service.palette["accent"]))
        self.setText(("99+" if count >= 100 else str(count)) if count else "")
        self.setToolTip(f"{count} notificacao(oes) nao lida(s)" if count else "Notificacoes")

    def toggle_popup(self):
        if self._popup is not None and self._popup.isVisible():
            self._popup.close()
            return
        self._popup = NotificationPopup(self.service, parent=self)
        point = self.mapToGlobal(self.rect().bottomRight())
        point.setX(point.x() - self._popup.minimumWidth())
        self._popup.move(point)
        self._popup.show()
        self._popup_fade = fade_in(self._popup, duration=160)
