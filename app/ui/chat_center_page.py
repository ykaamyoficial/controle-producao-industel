from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.ui.animations import fade_in
from app.ui.background_worker import start_worker
from app.ui.components.modern_button import ModernButton
from app.ui.components.toast_notification import ToastNotification
from app.ui.process_detail_dialog import ProcessDetailDialog
from app.ui.proposal_chat_dialog import ChatConversationPanel
from app.ui.styles import status_color


RIGHT_COLUMN_MIN_WIDTH = 1100
LEFT_COLUMN_MIN_WIDTH = 860


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
    selecionada ao centro (ChatConversationPanel embutido), participantes
    e acoes rapidas a direita."""

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._refresh_thread = None
        self._status_filter = "ATIVA"
        self.conversations: list[dict] = []
        self.selected_conversation: dict | None = None
        self.panel: ChatConversationPanel | None = None
        self._build()
        self.refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        header = QFrame()
        header.setObjectName("FilterBar")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(14, 10, 14, 10)
        header_layout.setSpacing(2)
        title = QLabel("Chats")
        title.setObjectName("FilterTitle")
        subtitle = QLabel("Comunique-se com sua equipe e acompanhe tudo sobre as propostas.")
        subtitle.setObjectName("FilterSubtitle")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        root.addWidget(header)

        self.left_column = self._build_left_column()
        self.center_column = self._build_center_column()
        self.right_column = self._build_right_column()
        self.left_column.setMinimumWidth(240)
        self.center_column.setMinimumWidth(340)
        self.right_column.setMinimumWidth(220)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)
        self.splitter.addWidget(self.left_column)
        self.splitter.addWidget(self.center_column)
        self.splitter.addWidget(self.right_column)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 5)
        self.splitter.setStretchFactor(2, 2)
        root.addWidget(self.splitter, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = self.width()
        right_visible = width >= RIGHT_COLUMN_MIN_WIDTH
        if self.right_column.isVisible() != right_visible:
            self.right_column.setVisible(right_visible)
        left_visible = width >= LEFT_COLUMN_MIN_WIDTH
        if self.left_column.isVisible() != left_visible:
            self.left_column.setVisible(left_visible)

    def _build_left_column(self) -> QFrame:
        container = QFrame()
        container.setObjectName("Panel")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Pesquisar conversas...")
        self.search.returnPressed.connect(self.refresh)
        layout.addWidget(self.search)

        tab_row = QHBoxLayout()
        self.active_tab_btn = ModernButton("Conversas Ativas", accent=True)
        self.finalized_tab_btn = ModernButton("Conversas Finalizadas")
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
        self.conversation_list.setSpacing(4)
        self.conversation_list.setFrameShape(QListWidget.NoFrame)
        self.conversation_list.itemClicked.connect(self._on_conversation_clicked)
        layout.addWidget(self.conversation_list, 1)
        return container

    def _build_center_column(self) -> QFrame:
        self.center_container = QFrame()
        self.center_container.setObjectName("Panel")
        self.center_layout = QVBoxLayout(self.center_container)
        self.center_layout.setContentsMargins(14, 14, 14, 14)
        self.empty_center_label = QLabel("Selecione uma conversa a esquerda para comecar.")
        self.empty_center_label.setAlignment(Qt.AlignCenter)
        self.empty_center_label.setObjectName("Caption")
        self.center_layout.addWidget(self.empty_center_label)
        return self.center_container

    def _build_right_column(self) -> QFrame:
        container = QFrame()
        container.setObjectName("Panel")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)

        self.summary_title = QLabel("Resumo da Proposta")
        self.summary_title.setStyleSheet("font-weight: 800;")
        self.summary_title.setVisible(False)
        layout.addWidget(self.summary_title)
        self.summary_layout = QVBoxLayout()
        self.summary_layout.setSpacing(4)
        layout.addLayout(self.summary_layout)

        participants_title = QLabel("Participantes")
        participants_title.setStyleSheet("font-weight: 800;")
        layout.addWidget(participants_title)
        self.participants_layout = QVBoxLayout()
        self.participants_layout.setSpacing(4)
        layout.addLayout(self.participants_layout)

        actions_title = QLabel("Acoes rapidas")
        actions_title.setStyleSheet("font-weight: 800;")
        layout.addWidget(actions_title)
        self.question_action_btn = ModernButton("Fazer pergunta", "chat")
        self.question_action_btn.clicked.connect(self._trigger_question_mode)
        layout.addWidget(self.question_action_btn)
        self.details_action_btn = ModernButton("Ver informacoes da proposta", "search")
        self.details_action_btn.clicked.connect(self._open_proposal_details)
        self.details_action_btn.setVisible(False)
        layout.addWidget(self.details_action_btn)
        layout.addStretch()
        return container

    def _set_status_tab(self, status: str):
        self._status_filter = status
        self.active_tab_btn.setObjectName("AccentButton" if status == "ATIVA" else "GhostButton")
        self.finalized_tab_btn.setObjectName("AccentButton" if status == "FINALIZADA" else "GhostButton")
        for button in (self.active_tab_btn, self.finalized_tab_btn):
            button.style().unpolish(button)
            button.style().polish(button)
        self.refresh()

    def refresh(self):
        self._set_loading(True)
        status = self._status_filter
        other_status = "FINALIZADA" if status == "ATIVA" else "ATIVA"
        search = self.search.text().strip()
        self._refresh_thread = start_worker(
            self, lambda: self._fetch(status, other_status, search), self._refresh_success, self._refresh_error
        )

    def _fetch(self, status: str, other_status: str, search: str) -> tuple[list[dict], int]:
        active = self.service.chat_conversations({"status": status, "search": search or None, "limit": 200})
        try:
            other = self.service.chat_conversations({"status": other_status, "search": search or None, "limit": 200})
        except Exception:
            other = []
        return active, len(other)

    def _refresh_success(self, result: tuple[list[dict], int]):
        conversations, other_count = result
        if self._status_filter == "ATIVA":
            self.active_tab_btn.setText(f"Conversas Ativas ({len(conversations)})")
            self.finalized_tab_btn.setText(f"Conversas Finalizadas ({other_count})")
        else:
            self.finalized_tab_btn.setText(f"Conversas Finalizadas ({len(conversations)})")
            self.active_tab_btn.setText(f"Conversas Ativas ({other_count})")
        self.conversations = conversations
        self.conversation_list.clear()
        selected_id = self.selected_conversation.get("id") if self.selected_conversation else None
        selected_item = None
        for conversation in conversations:
            item = QListWidgetItem()
            card = self._build_conversation_card(conversation)
            item.setSizeHint(card.sizeHint())
            item.setData(Qt.UserRole, conversation)
            self.conversation_list.addItem(item)
            self.conversation_list.setItemWidget(item, card)
            if selected_id is not None and conversation.get("id") == selected_id:
                selected_item = item
        if selected_item is not None:
            self.conversation_list.setCurrentItem(selected_item)
        self._set_loading(False)

    def _refresh_error(self, exc):
        self._set_loading(False)
        ToastNotification(self.window(), str(exc), "error")

    def _set_loading(self, loading: bool):
        self.loading.setVisible(loading)

    def _build_conversation_card(self, conversation: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("Panel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        is_general = conversation.get("kind") == "GERAL"
        name = "Chat Geral" if is_general else (conversation.get("proposal_number") or f"Proposta {conversation.get('proposal_id')}")

        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        if not is_general and conversation.get("proposal_status"):
            dot_color, _fg = status_color(conversation["proposal_status"], self.service.palette, conversation.get("proposal_area") or "")
            status_dot = QLabel()
            status_dot.setFixedSize(10, 10)
            status_dot.setStyleSheet(f"background: {dot_color}; border-radius: 5px;")
            top_row.addWidget(status_dot)
        name_label = QLabel(name)
        name_label.setStyleSheet("font-weight: 700;")
        top_row.addWidget(name_label)
        top_row.addStretch()
        time_label = QLabel(_relative_time(conversation.get("last_activity_at")))
        time_label.setObjectName("Caption")
        top_row.addWidget(time_label)
        layout.addLayout(top_row)

        subtitle_text = "Conversa geral entre todos" if is_general else (conversation.get("customer_name") or "-")
        subtitle = QLabel(subtitle_text)
        subtitle.setObjectName("Caption")
        layout.addWidget(subtitle)

        bottom_row = QHBoxLayout()
        preview_text = conversation.get("last_message_preview")
        if preview_text:
            author = conversation.get("last_message_author")
            preview_text = f"{author}: {preview_text}" if author else preview_text
        else:
            preview_text = "Sem mensagens ainda."
        preview_label = QLabel(preview_text)
        preview_label.setObjectName("Caption")
        preview_label.setWordWrap(False)
        metrics = preview_label.fontMetrics()
        preview_label.setText(metrics.elidedText(preview_text, Qt.ElideRight, 260))
        bottom_row.addWidget(preview_label, 1)
        unread = int(conversation.get("unread_count") or 0)
        if unread:
            badge = QLabel(str(unread) if unread < 100 else "99+")
            badge.setAlignment(Qt.AlignCenter)
            badge.setFixedSize(22, 20)
            badge.setStyleSheet(
                f"background: {self.service.palette.get('danger', '#dc2626')}; color: #ffffff; "
                "border-radius: 10px; font-weight: 800;"
            )
            bottom_row.addWidget(badge)
        layout.addLayout(bottom_row)
        return card

    def _on_conversation_clicked(self, item: QListWidgetItem):
        conversation = item.data(Qt.UserRole)
        if not conversation:
            return
        self.selected_conversation = conversation
        self._open_conversation(conversation)

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
        self.panel.entries_loaded.connect(self._refresh_right_column)
        self.center_layout.addWidget(self.panel, 1)
        self._panel_fade = fade_in(self.panel, duration=220)
        self.details_action_btn.setVisible(conversation.get("kind") != "GERAL")
        self._refresh_proposal_summary()
        self._refresh_right_column()

    def _refresh_proposal_summary(self):
        while self.summary_layout.count():
            item = self.summary_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        is_proposal = bool(self.selected_conversation) and self.selected_conversation.get("kind") != "GERAL"
        self.summary_title.setVisible(is_proposal)
        if not is_proposal or not self.panel:
            return
        proposal = self.panel.proposal or {}
        area, _label, status = self.service.current_location(proposal) if proposal else ("", "", "")
        fields = [
            ("Cliente", proposal.get("cliente") or "-"),
            ("Obra/Site", proposal.get("obra_site") or "-"),
            ("Status", self.service.status_label(status) if status else "-"),
            ("Peso", f"{proposal.get('peso') or '0'} kg"),
            ("Prazo", proposal.get("prazo_entrega") or "-"),
            ("Area atual", str(area or "-").replace("_", " ").title()),
        ]
        for label, value in fields:
            row = QHBoxLayout()
            caption = QLabel(label)
            caption.setObjectName("Caption")
            row.addWidget(caption)
            row.addStretch()
            content = QLabel(str(value))
            content.setStyleSheet("font-weight: 700;")
            row.addWidget(content)
            self.summary_layout.addLayout(row)

    def _refresh_right_column(self):
        while self.participants_layout.count():
            item = self.participants_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        if not self.panel:
            return
        participants = self.panel.participants()
        if not participants:
            empty = QLabel("Sem participantes ainda.")
            empty.setObjectName("Caption")
            self.participants_layout.addWidget(empty)
            return
        for person in participants:
            row = QHBoxLayout()
            name_label = QLabel(person.get("name") or "-")
            row.addWidget(name_label)
            row.addStretch()
            self.participants_layout.addLayout(row)

    def _trigger_question_mode(self):
        if self.panel:
            self.panel.focus_question_mode()

    def _open_proposal_details(self):
        if not self.selected_conversation or not self.selected_conversation.get("proposal_id"):
            return
        dialog = ProcessDetailDialog(self.service, self.selected_conversation["proposal_id"], self)
        dialog.exec()
