from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.ui.animations import fade_in
from app.ui.background_worker import start_worker
from app.ui.components.modern_button import ModernButton
from app.ui.components.toast_notification import ToastNotification
from app.ui.resilience import show_operation_error
from app.ui.proposal_chat_dialog import ChatConversationPanel
from app.ui.styles import status_color


CONVERSATION_LIST_WIDTH = 310
CONVERSATION_CARD_HEIGHT = 72


def _relative_time(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    now = datetime.now(parsed.tzinfo)
    delta_days = (now.date() - parsed.date()).days
    if delta_days == 0:
        return parsed.strftime("%H:%M")
    if delta_days == 1:
        return "Ontem"
    return parsed.strftime("%d/%m/%Y")


class ChatCenterPage(QWidget):
    """Tela "Chats": lista de conversas a esquerda, timeline da conversa
    selecionada ao centro (ChatConversationPanel embutido, com seu proprio
    painel lateral recolhivel de detalhes da proposta)."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._refresh_thread = None
        self._refresh_in_flight = False
        self._refresh_pending = False
        self._targeted_thread = None
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(350)
        self._search_timer.timeout.connect(self.refresh)
        self._status_filter = "ATIVA"
        self.conversations: list[dict] = []
        self.selected_conversation: dict | None = None
        self.panel: ChatConversationPanel | None = None
        self._build()
        self.refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 2, 4, 4)
        root.setSpacing(6)

        title = QLabel("\U0001F4AC Chats")
        title.setStyleSheet("font-size: 15px; font-weight: 800;")
        root.addWidget(title)

        self.left_column = self._build_left_column()
        self.center_column = self._build_center_column()
        self.left_column.setFixedWidth(CONVERSATION_LIST_WIDTH)
        self.center_column.setMinimumWidth(360)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)
        self.splitter.addWidget(self.left_column)
        self.splitter.addWidget(self.center_column)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 7)
        self.splitter.setSizes([CONVERSATION_LIST_WIDTH, max(360, self.width() - CONVERSATION_LIST_WIDTH)])
        root.addWidget(self.splitter, 1)

    def _build_left_column(self) -> QFrame:
        container = QFrame()
        container.setObjectName("Panel")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Pesquisar conversas...")
        self.search.returnPressed.connect(self.refresh)
        self.search.textChanged.connect(lambda _text: self._search_timer.start())
        layout.addWidget(self.search)

        tab_row = QHBoxLayout()
        tab_row.setSpacing(4)
        self.active_tab_btn = ModernButton("Ativas", accent=True)
        self.finalized_tab_btn = ModernButton("Finalizadas")
        self.finalized_tab_btn.setObjectName("GhostButton")
        self.active_tab_btn.clicked.connect(lambda: self._set_status_tab("ATIVA"))
        self.finalized_tab_btn.clicked.connect(lambda: self._set_status_tab("FINALIZADA"))
        tab_row.addWidget(self.active_tab_btn)
        tab_row.addWidget(self.finalized_tab_btn)
        layout.addLayout(tab_row)

        self.loading = QLabel("Carregando...")
        self.loading.setObjectName("Caption")
        self.loading.setVisible(False)
        layout.addWidget(self.loading)

        self.conversation_list = QListWidget()
        self.conversation_list.setObjectName("ConversationList")
        self.conversation_list.setSpacing(3)
        self.conversation_list.setFrameShape(QFrame.NoFrame)
        self.conversation_list.setStyleSheet(
            "QListWidget#ConversationList { border: none; background: transparent; }"
            "QListWidget#ConversationList QScrollBar:vertical { width: 5px; margin: 0px; }"
            "QListWidget#ConversationList QScrollBar::handle:vertical { min-height: 24px; }"
        )
        self.conversation_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.conversation_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.conversation_list.setUniformItemSizes(True)
        self.conversation_list.setViewportMargins(0, 0, 0, 0)
        self.conversation_list.verticalScrollBar().rangeChanged.connect(lambda _minimum, _maximum: self._sync_card_widths())
        self.conversation_list.itemClicked.connect(self._on_conversation_clicked)
        layout.addWidget(self.conversation_list, 1)
        return container

    def _build_center_column(self) -> QFrame:
        self.center_container = QFrame()
        self.center_container.setObjectName("Panel")
        self.center_layout = QVBoxLayout(self.center_container)
        self.center_layout.setContentsMargins(12, 12, 12, 12)
        self.empty_center_label = QLabel("Selecione uma conversa a esquerda para comecar.")
        self.empty_center_label.setAlignment(Qt.AlignCenter)
        self.empty_center_label.setObjectName("Caption")
        self.center_layout.addWidget(self.empty_center_label)
        return self.center_container

    def _set_status_tab(self, status: str):
        self._status_filter = status
        self.active_tab_btn.setObjectName("AccentButton" if status == "ATIVA" else "GhostButton")
        self.finalized_tab_btn.setObjectName("AccentButton" if status == "FINALIZADA" else "GhostButton")
        for button in (self.active_tab_btn, self.finalized_tab_btn):
            button.style().unpolish(button)
            button.style().polish(button)
        self.refresh()

    def refresh(self):
        if self._refresh_in_flight:
            self._refresh_pending = True
            return
        self._refresh_in_flight = True
        self._set_loading(True)
        status = self._status_filter
        other_status = "FINALIZADA" if status == "ATIVA" else "ATIVA"
        search = self.search.text().strip()
        self._refresh_thread = start_worker(
            self,
            lambda: self._fetch(status, other_status, search),
            self._refresh_success,
            self._refresh_error,
            operation_name="chat_center_page.refresh",
        )

    def _fetch(self, status: str, other_status: str, search: str) -> tuple[list[dict], int]:
        active_page = self.service.chat_conversations_page({"status": status, "search": search or None, "limit": 50})
        active = active_page.get("items") or []
        try:
            other_page = self.service.chat_conversations_page({"status": other_status, "search": search or None, "limit": 1})
            other = int(other_page.get("total") or 0)
        except Exception:
            other = 0
        return active, other

    def _refresh_success(self, result: tuple[list[dict], int]):
        conversations, other_count = result
        if self._status_filter == "ATIVA":
            self.active_tab_btn.setText(f"Ativas ({len(conversations)})")
            self.finalized_tab_btn.setText(f"Finalizadas ({other_count})")
        else:
            self.finalized_tab_btn.setText(f"Finalizadas ({len(conversations)})")
            self.active_tab_btn.setText(f"Ativas ({other_count})")
        self.active_tab_btn.setToolTip(f"Conversas Ativas ({len(conversations) if self._status_filter == 'ATIVA' else other_count})")
        self.finalized_tab_btn.setToolTip(f"Conversas Finalizadas ({other_count if self._status_filter == 'ATIVA' else len(conversations)})")
        self.conversations = conversations
        self.conversation_list.clear()
        selected_id = self.selected_conversation.get("id") if self.selected_conversation else None
        selected_item = None
        for conversation in conversations:
            item = QListWidgetItem()
            card = self._build_conversation_card(conversation)
            card.setFixedWidth(max(0, self.conversation_list.viewport().width() - 4))
            self._fit_card_labels(card)
            item.setSizeHint(QSize(0, CONVERSATION_CARD_HEIGHT))
            item.setData(Qt.UserRole, conversation)
            self.conversation_list.addItem(item)
            self.conversation_list.setItemWidget(item, card)
            if selected_id is not None and conversation.get("id") == selected_id:
                selected_item = item
        if selected_item is not None:
            self.conversation_list.setCurrentItem(selected_item)
        self._set_loading(False)
        self._refresh_in_flight = False
        if self._refresh_pending:
            self._refresh_pending = False
            QTimer.singleShot(0, self.refresh)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_card_widths()

    def _sync_card_widths(self):
        if not hasattr(self, "conversation_list"):
            return
        width = max(0, self.conversation_list.viewport().width() - 4)
        for index in range(self.conversation_list.count()):
            card = self.conversation_list.itemWidget(self.conversation_list.item(index))
            if card is not None:
                card.setFixedWidth(width)
                self._fit_card_labels(card)

    @staticmethod
    def _fit_card_labels(card: QFrame):
        width = max(0, card.width())
        proposal = card.findChild(QLabel, "ConversationProposal")
        client = card.findChild(QLabel, "ConversationClient")
        preview = card.findChild(QLabel, "ConversationPreview")
        if proposal is not None:
            proposal.setText(proposal.property("full_text") or "")
            proposal.setText(proposal.fontMetrics().elidedText(proposal.text(), Qt.ElideRight, max(90, width - 90)))
        if client is not None:
            client.setText(client.property("full_text") or "")
            client.setText(client.fontMetrics().elidedText(client.text(), Qt.ElideRight, max(120, width - 26)))
        if preview is not None:
            preview.setText(preview.property("full_text") or "")
            preview.setText(preview.fontMetrics().elidedText(preview.text(), Qt.ElideRight, max(130, width - 46)))

    def _refresh_error(self, exc):
        self._set_loading(False)
        self._refresh_in_flight = False
        show_operation_error(self, exc, self.refresh, title="Chat")
        if self._refresh_pending:
            self._refresh_pending = False
            QTimer.singleShot(0, self.refresh)

    def _set_loading(self, loading: bool):
        self.loading.setVisible(loading)

    def _build_conversation_card(self, conversation: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("Panel")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        card.setMinimumWidth(0)
        card.setFixedHeight(CONVERSATION_CARD_HEIGHT)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(1)

        is_general = conversation.get("kind") == "GERAL"
        name = "Chat Geral" if is_general else (conversation.get("proposal_number") or f"Proposta {conversation.get('proposal_id')}")

        top_row = QHBoxLayout()
        top_row.setSpacing(5)
        if not is_general and conversation.get("proposal_status"):
            dot_color, _fg = status_color(conversation["proposal_status"], self.service.palette, conversation.get("proposal_area") or "")
            status_dot = QLabel()
            status_dot.setFixedSize(8, 8)
            status_dot.setStyleSheet(f"background: {dot_color}; border-radius: 4px;")
            top_row.addWidget(status_dot)
        name_label = QLabel(name)
        name_label.setObjectName("ConversationProposal")
        name_label.setProperty("full_text", name)
        name_label.setStyleSheet("font-weight: 700; font-size: 11px;")
        name_label.setMinimumWidth(0)
        name_label.setWordWrap(False)
        name_label.setText(name_label.fontMetrics().elidedText(name, Qt.ElideRight, max(90, card.width() - 90)))
        top_row.addWidget(name_label)
        top_row.addStretch()
        time_label = QLabel(_relative_time(conversation.get("last_activity_at")))
        time_label.setStyleSheet("font-size: 9px;")
        time_label.setObjectName("Caption")
        top_row.addWidget(time_label)
        layout.addLayout(top_row)

        subtitle_text = "Conversa geral entre todos" if is_general else (conversation.get("customer_name") or "-")
        subtitle = QLabel(subtitle_text)
        subtitle.setObjectName("ConversationClient")
        subtitle.setProperty("full_text", subtitle_text)
        subtitle.setObjectName("Caption")
        subtitle.setStyleSheet("font-size: 10px;")
        subtitle.setMinimumWidth(0)
        subtitle.setWordWrap(False)
        subtitle.setText(subtitle.fontMetrics().elidedText(subtitle_text, Qt.ElideRight, max(120, card.width() - 26)))
        layout.addWidget(subtitle)

        bottom_row = QHBoxLayout()
        preview_text = conversation.get("last_message_preview")
        if preview_text:
            author = conversation.get("last_message_author")
            preview_text = f"{author}: {preview_text}" if author else preview_text
        else:
            preview_text = "Sem mensagens ainda."
        preview_text = str(preview_text)
        preview_label = QLabel(preview_text)
        preview_label.setObjectName("ConversationPreview")
        preview_label.setProperty("full_text", preview_text)
        preview_label.setObjectName("Caption")
        preview_label.setStyleSheet("font-size: 10px;")
        preview_label.setWordWrap(False)
        preview_label.setMinimumWidth(0)
        metrics = preview_label.fontMetrics()
        preview_label.setText(metrics.elidedText(preview_text, Qt.ElideRight, max(130, card.width() - 46)))
        bottom_row.addWidget(preview_label, 1)
        unread = int(conversation.get("unread_count") or 0)
        if unread:
            badge = QLabel(str(unread) if unread < 100 else "99+")
            badge.setAlignment(Qt.AlignCenter)
            badge.setFixedSize(19, 18)
            badge.setStyleSheet(
                f"background: {self.service.palette.get('danger', '#dc2626')}; color: #ffffff; "
                "border-radius: 9px; font-weight: 800; font-size: 9px;"
            )
            bottom_row.addWidget(badge)
        layout.addLayout(bottom_row)
        return card

    def _on_conversation_clicked(self, item: QListWidgetItem):
        conversation = item.data(Qt.UserRole)
        if not conversation:
            return
        self.selected_conversation = conversation
        if int(conversation.get("unread_count") or 0) > 0:
            self._clear_local_unread(int(conversation.get("id") or 0))
        self._open_conversation(conversation)

    def _clear_local_unread(self, conversation_id: int):
        """Remove o contador visual assim que a conversa e aberta."""
        if not conversation_id:
            return
        for index, conversation in enumerate(self.conversations):
            if int(conversation.get("id") or 0) != conversation_id:
                continue
            conversation["unread_count"] = 0
            item = self.conversation_list.item(index)
            if item is None:
                return
            card = self._build_conversation_card(conversation)
            card.setFixedWidth(max(0, self.conversation_list.viewport().width() - 4))
            self._fit_card_labels(card)
            item.setData(Qt.UserRole, conversation)
            item.setSizeHint(QSize(0, CONVERSATION_CARD_HEIGHT))
            self.conversation_list.setItemWidget(item, card)
            return

    def _open_conversation(self, conversation: dict):
        while self.center_layout.count():
            child = self.center_layout.takeAt(0)
            widget = child.widget()
            if widget:
                widget.deleteLater()
        if conversation.get("kind") == "GERAL":
            self.panel = ChatConversationPanel(self.service, conversation_id=conversation["id"], parent=self.center_container)
        else:
            self.panel = ChatConversationPanel(self.service, proposal_id=conversation.get("proposal_id"), parent=self.center_container)
        self.center_layout.addWidget(self.panel, 1)
        self._panel_fade = fade_in(self.panel, duration=220)

    def on_conversation_updated(self, conversation_id: int) -> None:
        """Atualiza somente o card alterado; refresh completo fica reservado
        para uma conversa nova ou para mudança de status/aba."""
        if not conversation_id:
            return
        index = next((i for i, row in enumerate(self.conversations) if int(row.get("id") or 0) == conversation_id), None)
        if index is None:
            self.refresh()
            return
        current = self.conversations[index]
        status = current.get("status") or self._status_filter
        if self._targeted_thread is not None and self._targeted_thread.isRunning():
            return
        self._targeted_thread = start_worker(
            self,
            lambda: (self.service.chat_conversations_page({"status": status, "conversation_id": conversation_id, "limit": 1}).get("items") or []),
            lambda rows: self._apply_targeted_conversation(conversation_id, rows),
            lambda _exc: None,
            operation_name="chat_center_page.update_conversation",
        )

    def _apply_targeted_conversation(self, conversation_id: int, rows: list[dict]) -> None:
        updated = next((row for row in rows if int(row.get("id") or 0) == conversation_id), None)
        if updated is None:
            self.refresh()
            return
        index = next((i for i, row in enumerate(self.conversations) if int(row.get("id") or 0) == conversation_id), None)
        if index is None:
            self.refresh()
            return
        self.conversations[index] = updated
        item = self.conversation_list.item(index)
        if item is None:
            return
        card = self._build_conversation_card(updated)
        card.setFixedWidth(max(0, self.conversation_list.viewport().width() - 4))
        self._fit_card_labels(card)
        item.setData(Qt.UserRole, updated)
        self.conversation_list.setItemWidget(item, card)
        if self.selected_conversation and int(self.selected_conversation.get("id") or 0) == conversation_id:
            self.selected_conversation = updated
