from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
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
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
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

    def __init__(self, service, parent=None, proposal_id=None, conversation_id=None, message_id=None):
        super().__init__(parent)
        self.service = service
        self._refresh_thread = None
        self._refresh_in_flight = False
        self._refresh_pending = False
        self._targeted_thread = None
        self._closing = False
        self._worker_threads = []
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(350)
        self._search_timer.timeout.connect(self.refresh)
        self._status_filter = "ATIVA"
        self.conversations: list[dict] = []
        self.selected_conversation: dict | None = None
        self.panel: ChatConversationPanel | None = None
        # Alvo pedido na abertura (notificacao, "Ver mensagens", icone de
        # chat na linha da proposta) - abre direto nessa conversa em vez da
        # tela vazia "selecione uma conversa", e some assim que a lista
        # carrega e consegue selecionar o card correspondente sozinha.
        self._pending_target_proposal_id = proposal_id
        self._pending_target_conversation_id = conversation_id
        self._build()
        if proposal_id is not None or conversation_id is not None:
            self._show_panel(proposal_id=proposal_id, conversation_id=conversation_id)
            if message_id:
                self.panel.focus_message(message_id)
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
        # Nao usa "Panel" (borda + cantos arredondados) de proposito: com a
        # margem zerada, um card arredondado ali vazaria por baixo do
        # cabecalho reto da conversa. A unica divisoria agora e o
        # border-bottom do proprio QFrame#ChatHeaderCard.
        self.center_container.setObjectName("ChatCenterColumn")
        self.center_layout = QVBoxLayout(self.center_container)
        # Sem margem: o cabecalho da conversa (QFrame#ChatHeaderCard) e a
        # unica divisoria, o resto preenche a coluna inteira edge-to-edge -
        # ver ChatConversationPanel._build() em proposal_chat_dialog.py.
        self.center_layout.setContentsMargins(0, 0, 0, 0)
        self.center_layout.setSpacing(0)
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
        if self._closing:
            return
        if self._refresh_in_flight:
            self._refresh_pending = True
            return
        self._refresh_in_flight = True
        self._set_loading(True)
        status = self._status_filter
        other_status = "FINALIZADA" if status == "ATIVA" else "ATIVA"
        search = self.search.text().strip()
        self._refresh_thread = self._run_background(
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
        if self._closing:
            self._refresh_in_flight = False
            return
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
        target_conversation_id = self._pending_target_conversation_id
        target_proposal_id = self._pending_target_proposal_id
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
            elif selected_id is None and (
                (target_conversation_id is not None and conversation.get("id") == target_conversation_id)
                or (target_proposal_id is not None and conversation.get("proposal_id") == target_proposal_id)
            ):
                selected_item = item
                self.selected_conversation = conversation
        if selected_item is not None:
            self.conversation_list.setCurrentItem(selected_item)
        self._pending_target_conversation_id = None
        self._pending_target_proposal_id = None
        self._set_loading(False)
        self._refresh_in_flight = False
        if self._refresh_pending and not self._closing:
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
        if self._closing:
            self._refresh_in_flight = False
            return
        self._set_loading(False)
        self._refresh_in_flight = False
        show_operation_error(self, exc, self.refresh, title="Chat")
        if self._refresh_pending and not self._closing:
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
        if conversation.get("kind") == "GERAL":
            self._show_panel(conversation_id=conversation["id"])
        else:
            self._show_panel(proposal_id=conversation.get("proposal_id"))

    def _show_panel(self, *, proposal_id=None, conversation_id=None) -> ChatConversationPanel:
        while self.center_layout.count():
            child = self.center_layout.takeAt(0)
            widget = child.widget()
            if widget:
                cleanup = getattr(widget, "cleanup", None)
                if callable(cleanup):
                    cleanup()
                widget.deleteLater()
        self.panel = ChatConversationPanel(self.service, proposal_id=proposal_id, conversation_id=conversation_id, parent=self.center_container)
        self.center_layout.addWidget(self.panel, 1)
        self._panel_fade = fade_in(self.panel, duration=220)
        return self.panel

    def on_conversation_updated(self, conversation_id: int) -> None:
        """Atualiza o card na lista lateral e, se essa conversa e a que esta
        aberta no momento, tambem o conteudo — sem isso, quem esta com a
        conversa aberta so via a mensagem nova saindo e voltando (ver
        ETAPA realtime: o evento chegava, mas so o card era atualizado)."""
        if not conversation_id:
            return
        if self._closing:
            return
        if self.panel is not None and self.panel.conversation_id == conversation_id:
            self.panel.refresh()
        index = next((i for i, row in enumerate(self.conversations) if int(row.get("id") or 0) == conversation_id), None)
        if index is None:
            self.refresh()
            return
        current = self.conversations[index]
        status = current.get("status") or self._status_filter
        if self._targeted_thread is not None and self._targeted_thread.isRunning():
            return
        self._targeted_thread = self._run_background(
            lambda: (self.service.chat_conversations_page({"status": status, "conversation_id": conversation_id, "limit": 1}).get("items") or []),
            lambda rows: self._apply_targeted_conversation(conversation_id, rows),
            lambda _exc: None,
            operation_name="chat_center_page.update_conversation",
        )

    def on_conversation_event(self, event_type: str, data: dict) -> None:
        conversation_id = data.get("conversation_id") if isinstance(data, dict) else None
        if self.panel is None or self.panel.conversation_id != conversation_id:
            return
        self.panel.apply_realtime_event(event_type, data)

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

    def _run_background(self, operation, on_success, on_error, *, operation_name: str):
        if self._closing:
            return None
        thread = start_worker(self, operation, on_success, on_error, operation_name=operation_name)
        self._worker_threads.append(thread)
        thread.finished.connect(lambda target=thread: self._worker_threads.remove(target) if target in self._worker_threads else None)
        return thread

    def cleanup(self):
        if self._closing:
            return
        self._closing = True
        self._search_timer.stop()
        if self.panel is not None:
            self.panel.cleanup()
        threads = list(self._worker_threads)
        for thread in (self._refresh_thread, self._targeted_thread):
            if thread is not None and thread not in threads:
                threads.append(thread)
        self._worker_threads.clear()
        self._refresh_thread = None
        self._targeted_thread = None
        for thread in threads:
            try:
                if thread.isRunning():
                    thread.quit()
                    thread.wait(2000)
            except RuntimeError:
                pass

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)

    def event(self, event):
        if event.type() == QEvent.DeferredDelete:
            self.cleanup()
        return super().event(event)


class ChatCenterDialog(QDialog):
    """Casca modal em cima de ChatCenterPage — unico ponto de entrada pra
    abrir uma conversa no app: botao de chat, notificacao, "Ver mensagens"
    do banner e o icone de chat na linha da proposta todos abrem esta
    mesma tela (lista de conversas + timeline), so variando qual conversa
    ja vem selecionada via proposal_id/conversation_id/message_id."""

    def __init__(self, service, parent=None, proposal_id=None, conversation_id=None, message_id=None):
        super().__init__(parent)
        self.service = service
        apply_large_dialog_geometry(self, parent, width_ratio=0.94, height_ratio=0.94, minimum_width=1180, minimum_height=690)
        style_dialog_from_parent(self, parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.page = ChatCenterPage(
            service,
            parent=self,
            proposal_id=proposal_id,
            conversation_id=conversation_id,
            message_id=message_id,
        )
        root.addWidget(self.page, 1)

        self.setWindowTitle("Chats")
