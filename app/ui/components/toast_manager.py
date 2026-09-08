from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.ui.components.modern_button import ModernButton


TOAST_DURATION_MS = 7000
MAX_VISIBLE_TOASTS = 3
TOAST_WIDTH = 320
TOAST_MARGIN = 16
TOAST_SPACING = 8


class InAppToast(QFrame):
    """Um pop-up interno individual — nunca uma notificacao do Windows,
    fica dentro da propria janela do app (PDF secao 9)."""

    closed = Signal(object)
    opened = Signal(object)

    def __init__(self, service, parent: QWidget, title: str, body: str, payload: dict):
        super().__init__(parent)
        self.payload = payload
        self.setObjectName("Panel")
        self.setFixedWidth(TOAST_WIDTH)
        self.setAttribute(Qt.WA_StyledBackground, True)
        palette = service.palette
        self.setStyleSheet(
            f"QFrame#Panel {{ background: {palette.get('surface', '#ffffff')}; "
            f"border: 1px solid {palette.get('border', '#cbd5e1')}; border-radius: 10px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        header = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: 800; font-size: 12px;")
        header.addWidget(title_label, 1)
        close_btn = QPushButton("x")
        close_btn.setObjectName("GhostButton")
        close_btn.setFixedSize(18, 18)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self._dismiss)
        header.addWidget(close_btn)
        layout.addLayout(header)

        if body:
            body_label = QLabel(body)
            body_label.setWordWrap(True)
            body_label.setStyleSheet("font-size: 11px;")
            layout.addWidget(body_label)

        open_btn = ModernButton("Abrir conversa", "chat")
        open_btn.clicked.connect(self._open)
        layout.addWidget(open_btn)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._dismiss)
        self._timer.start(TOAST_DURATION_MS)

    def _dismiss(self):
        # fechar NUNCA marca a notificacao persistida como lida — so tira o
        # pop-up da tela (PDF: "Fechar o pop-up nao descarta a notificacao").
        self.closed.emit(self)
        self.hide()
        self.deleteLater()

    def _open(self):
        self._timer.stop()
        self.opened.emit(self)
        self.closed.emit(self)
        self.hide()
        self.deleteLater()


class InAppToastManager(QObject):
    """Gerenciador centralizado de pop-ups internos: uma tela nunca cria um
    aviso por conta propria, tudo passa por aqui. Regras (PDF secao 9):
    nunca para mensagem propria (garantido rio acima — o backend so notifica
    quem nao e o autor), nunca para a conversa ja aberta, nunca para
    atividade automatica (so reage a ChatNotification, nunca a activities),
    agrupa notificacoes consecutivas da mesma conversa, limita simultaneos."""

    def __init__(self, service, parent_widget: QWidget, on_open_conversation):
        super().__init__(parent_widget)
        self.service = service
        self.parent_widget = parent_widget
        self._on_open_conversation = on_open_conversation
        self._seen_ids: set[int] = set()
        self._initialized = False
        self._current_conversation_id: int | None = None
        self._active_toasts: list[InAppToast] = []
        self._pending_groups: list[list[dict]] = []

    def set_current_conversation(self, conversation_id: int | None) -> None:
        self._current_conversation_id = conversation_id

    def handle_notifications(self, notifications: list[dict]) -> None:
        current_ids = {item["id"] for item in notifications if item.get("id") and item["id"] > 0}
        if not self._initialized:
            # primeira leitura depois de abrir o app: so estabelece a base de
            # comparacao, nunca dispara pop-up retroativo pro que ja existia.
            self._seen_ids = current_ids
            self._initialized = True
            return
        new_ids = current_ids - self._seen_ids
        self._seen_ids = current_ids
        if not new_ids:
            return
        new_items = [item for item in notifications if item.get("id") in new_ids]
        new_items = [item for item in new_items if item.get("conversation_id") != self._current_conversation_id]
        if not new_items:
            return
        for group in self._group_by_conversation(new_items):
            self._pending_groups.append(group)
        self._drain()

    @staticmethod
    def _group_by_conversation(items: list[dict]) -> list[list[dict]]:
        order: list[int] = []
        buckets: dict[int, list[dict]] = {}
        for item in items:
            key = item.get("conversation_id")
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append(item)
        return [buckets[key] for key in order]

    def _drain(self) -> None:
        while self._pending_groups and len(self._active_toasts) < MAX_VISIBLE_TOASTS:
            self._show_toast(self._pending_groups.pop(0))

    def _show_toast(self, group: list[dict]) -> None:
        first = group[0]
        who = first.get("author_name") or "Alguem"
        proposal_number = first.get("proposal_number")
        where = proposal_number or ("Chat Geral" if first.get("kind") == "GERAL" else "")
        title = f"{who} - {where}" if where else who
        if len(group) == 1:
            body = (first.get("message_body") or "").strip()
        else:
            body = f"{len(group)} notificacoes novas nesta conversa"

        toast = InAppToast(self.service, self.parent_widget, title, body, first)
        toast.opened.connect(lambda payload_toast: self._on_toast_opened(payload_toast))
        toast.closed.connect(self._on_toast_closed)
        self._active_toasts.append(toast)
        self._reposition()
        toast.show()

    def _on_toast_opened(self, toast: InAppToast) -> None:
        notification = toast.payload
        if self._on_open_conversation is not None:
            self._on_open_conversation(notification.get("proposal_id"), notification.get("conversation_id"), notification.get("message_id"))

    def _on_toast_closed(self, toast: InAppToast) -> None:
        if toast in self._active_toasts:
            self._active_toasts.remove(toast)
        self._reposition()
        self._drain()

    def _reposition(self) -> None:
        if not self.parent_widget:
            return
        base_x = self.parent_widget.width() - TOAST_WIDTH - TOAST_MARGIN
        y = self.parent_widget.height() - TOAST_MARGIN
        for toast in reversed(self._active_toasts):
            toast.adjustSize()
            y -= toast.height()
            toast.move(max(0, base_x), max(0, y))
            y -= TOAST_SPACING
