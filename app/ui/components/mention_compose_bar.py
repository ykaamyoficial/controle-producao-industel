from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

from app.ui.components.avatar import make_avatar_label

from PySide6.QtCore import QDateTime, QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QIcon, QPixmap, QTextCursor, QTextOption
from PySide6.QtWidgets import (
    QCheckBox,
    QDateTimeEdit,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from app.ui.icons import make_icon
from app.ui.components.chat_pending_attachments import (
    AttachmentState,
    AttachmentsQueueWidget,
    MAX_ATTACHMENTS_PER_MESSAGE,
    PendingChatAttachment,
    validate_local_attachment,
)


COMMON_EMOJI = [
    "😀", "😁", "😂", "🤣", "😊", "🙂",
    "😉", "😍", "🤔", "😅", "😢", "😡",
    "👍", "👎", "🙏", "👏", "💪", "🙌",
    "🎉", "🔥", "✅", "❌", "⚠️", "💡",
    "📌", "📎", "📅", "⏰", "💬", "👀",
]


def _initials(name: str | None) -> str:
    parts = (name or "").split()
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


class _ComposeTextEdit(QTextEdit):
    """QTextEdit com Enter-para-enviar / Shift+Enter-para-quebrar-linha e
    deteccao de @mencao (mesmo pra inserções programaticas, via textChanged)."""

    send_requested = Signal()
    mention_query_changed = Signal(object)
    navigate_mention = Signal(int)
    confirm_mention = Signal()
    cancel_mention = Signal()
    image_paste_requested = Signal(object)
    file_paste_requested = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mention_active = False
        self.textChanged.connect(self._detect_mention_query)

    def keyPressEvent(self, event):
        if self._mention_active and event.key() in (Qt.Key_Up, Qt.Key_Down):
            self.navigate_mention.emit(-1 if event.key() == Qt.Key_Up else 1)
            return
        if self._mention_active and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.confirm_mention.emit()
            return
        if self._mention_active and event.key() == Qt.Key_Escape:
            self.cancel_mention.emit()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
            self.send_requested.emit()
            return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source) -> None:
        if source.hasText():
            super().insertFromMimeData(source)
            return
        if source.hasImage():
            self.image_paste_requested.emit(source.imageData())
            return
        if source.hasUrls():
            paths = [url.toLocalFile() for url in source.urls() if url.isLocalFile()]
            if paths:
                self.file_paste_requested.emit(paths)
                return
        super().insertFromMimeData(source)

    def _detect_mention_query(self):
        cursor = self.textCursor()
        text_before = self.toPlainText()[: cursor.position()]
        at_index = text_before.rfind("@")
        if at_index == -1:
            self._set_mention_active(False)
            return
        if at_index > 0 and text_before[at_index - 1] not in (" ", "\n"):
            self._set_mention_active(False)
            return
        fragment = text_before[at_index + 1 :]
        if " " in fragment or "\n" in fragment:
            self._set_mention_active(False)
            return
        self._set_mention_active(True)
        self.mention_query_changed.emit(fragment)

    def _set_mention_active(self, active: bool):
        if active == self._mention_active:
            return
        self._mention_active = active
        if not active:
            self.mention_query_changed.emit(None)


class _MentionPopup(QFrame):
    user_selected = Signal(dict)

    def __init__(self, service, parent=None):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.service = service
        self.setObjectName("Panel")
        self.setFixedWidth(280)
        self._all_users: list[dict] = []
        self._filtered: list[dict] = []
        self._selected_index = 0
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(6, 6, 6, 6)
        self.layout_.setSpacing(2)

    def set_users(self, users: list[dict]):
        self._all_users = users

    def filter(self, query: str):
        normalized = query.lower()
        self._filtered = [user for user in self._all_users if normalized in (user.get("display_name") or "").lower()][:8]
        self._selected_index = 0
        self._render()

    def _render(self):
        while self.layout_.count():
            item = self.layout_.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        if not self._filtered:
            empty = QLabel("Nenhum usuario encontrado.")
            empty.setObjectName("Caption")
            self.layout_.addWidget(empty)
            self.adjustSize()
            return
        for index, user in enumerate(self._filtered):
            self.layout_.addWidget(self._build_row(user, index == self._selected_index))
        self.adjustSize()

    def _build_row(self, user: dict, selected: bool) -> QFrame:
        row = QFrame()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(6, 4, 6, 4)
        row_layout.setSpacing(8)

        avatar = make_avatar_label(user.get("display_name"), self.service, 26, user.get("id"))
        row_layout.addWidget(avatar)

        text_col = QVBoxLayout()
        text_col.setSpacing(0)
        name_label = QLabel(user.get("display_name") or "-")
        name_label.setStyleSheet("font-weight: 700;")
        text_col.addWidget(name_label)
        if user.get("sector"):
            sector_label = QLabel(user["sector"])
            sector_label.setObjectName("Caption")
            text_col.addWidget(sector_label)
        row_layout.addLayout(text_col, 1)

        is_online = bool(user.get("is_online"))
        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot_color = self.service.palette.get("success", "#16a34a") if is_online else self.service.palette.get("muted", "#94a3b8")
        dot.setStyleSheet(f"background: {dot_color}; border-radius: 4px;")
        dot.setToolTip("Online" if is_online else "Offline")
        row_layout.addWidget(dot)

        if selected:
            row.setStyleSheet(f"background: {self.service.palette.get('surface_alt', '#e2e8f0')}; border-radius: 8px;")
        row.setCursor(Qt.PointingHandCursor)
        row.mousePressEvent = lambda _event, u=user: self.user_selected.emit(u)
        return row

    def move_selection(self, delta: int):
        if not self._filtered:
            return
        self._selected_index = (self._selected_index + delta) % len(self._filtered)
        self._render()

    def confirm_selection(self):
        if self._filtered:
            self.user_selected.emit(self._filtered[self._selected_index])


class _EmojiPopup(QFrame):
    emoji_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("Panel")
        layout = QGridLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(2)
        for index, emoji in enumerate(COMMON_EMOJI):
            button = QPushButton(emoji)
            button.setObjectName("GhostButton")
            button.setFixedSize(32, 32)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, value=emoji: self._select(value))
            layout.addWidget(button, index // 6, index % 6)

    def _select(self, emoji: str):
        self.emoji_selected.emit(emoji)
        self.close()


class MentionComposeBar(QFrame):
    """Barra de envio unica: anexar/emoji/@mencionar, campo que cresce ate
    ~6 linhas, microfone (estrutura preparada) e botao circular de enviar.
    Enter envia, Shift+Enter quebra linha. @ abre um menu de mencao; quando
    o texto contem uma mencao valida, mostra a opcao 'Marcar como Pergunta'."""

    send_requested = Signal()
    action_unavailable = Signal(str)
    internal_note_requested = Signal()
    height_changed = Signal()
    attachment_warning = Signal(str)
    attachment_cancel_requested = Signal(str)

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._last_mentioned_user_id: int | None = None
        self._last_mentioned_name: str | None = None
        self._mentionable_users: list[dict] = []
        self._reply_to_message_id: int | None = None
        self._pending_attachments: list[PendingChatAttachment] = []
        self._sending = False
        self._drag_active = False
        self._base_style = ""
        self._build()

    def _build(self):
        palette = self.service.palette
        self.setObjectName("ComposeBar")
        self.setAcceptDrops(True)
        self._base_style = (
            f"QFrame#ComposeBar {{ background: {palette.get('surface', '#ffffff')}; "
            f"border: 1px solid {palette.get('border', '#cbd5e1')}; border-radius: 10px; }}"
        )
        self.setStyleSheet(self._base_style)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(2)

        self._reply_preview = QFrame()
        self._reply_preview.setObjectName("ReplyPreviewBar")
        self._reply_preview.setStyleSheet(
            f"QFrame#ReplyPreviewBar {{ background: {palette.get('surface_alt', '#e2e8f0')}; "
            f"border-left: 3px solid {palette.get('accent', '#0078d4')}; border-radius: 4px; }}"
        )
        reply_layout = QHBoxLayout(self._reply_preview)
        reply_layout.setContentsMargins(8, 4, 6, 4)
        reply_layout.setSpacing(6)
        self._reply_preview_label = QLabel()
        self._reply_preview_label.setWordWrap(True)
        self._reply_preview_label.setMinimumHeight(QFontMetrics(self.font()).lineSpacing() * 2)
        self._reply_preview_label.setStyleSheet("font-size: 11px;")
        reply_layout.addWidget(self._reply_preview_label, 1)
        cancel_reply_btn = QPushButton("x")
        cancel_reply_btn.setObjectName("GhostButton")
        cancel_reply_btn.setFixedSize(20, 20)
        cancel_reply_btn.setCursor(Qt.PointingHandCursor)
        cancel_reply_btn.clicked.connect(self.clear_reply_preview)
        reply_layout.addWidget(cancel_reply_btn)
        self._reply_preview.setVisible(False)
        outer.addWidget(self._reply_preview)

        self.attachments_queue = AttachmentsQueueWidget(palette)
        self.attachments_queue.remove_requested.connect(self.remove_attachment)
        self.attachments_queue.retry_requested.connect(lambda local_id: self.attachment_warning.emit("O reenvio sera feito ao clicar em Enviar novamente."))
        self.attachments_queue.cancel_requested.connect(self.cancel_attachment)
        self.attachments_queue.changed.connect(self.height_changed.emit)
        outer.addWidget(self.attachments_queue)

        row = QHBoxLayout()
        row.setSpacing(4)

        self.attach_btn = QPushButton()
        self.attach_btn.setObjectName("GhostButton")
        self.attach_btn.setIcon(make_icon("attach", self.service.palette["accent"], 20))
        self.attach_btn.setIconSize(QSize(20, 20))
        self.attach_btn.setFixedSize(36, 36)
        self.attach_btn.setCursor(Qt.PointingHandCursor)
        self.attach_btn.setToolTip("Anexar arquivo")
        self.attach_btn.clicked.connect(self.open_attachment_dialog)
        row.addWidget(self.attach_btn)
        row.setAlignment(self.attach_btn, Qt.AlignBottom)

        self.note_btn = self._icon_button("doc", "Registrar nota interna")
        self.note_btn.clicked.connect(self.internal_note_requested.emit)
        row.addWidget(self.note_btn)
        row.setAlignment(self.note_btn, Qt.AlignBottom)

        self.emoji_btn = self._icon_button("emoji", "Emojis")
        self.emoji_btn.clicked.connect(self._open_emoji_popup)
        row.addWidget(self.emoji_btn)
        row.setAlignment(self.emoji_btn, Qt.AlignBottom)

        self.mention_btn = self._icon_button("at", "Mencionar usuario")
        self.mention_btn.clicked.connect(self._insert_at_symbol)
        row.addWidget(self.mention_btn)
        row.setAlignment(self.mention_btn, Qt.AlignBottom)

        self.text_edit = _ComposeTextEdit()
        self.text_edit.setObjectName("ComposeTextEdit")
        self.text_edit.setStyleSheet("QTextEdit#ComposeTextEdit { border: none; background: transparent; }")
        self.text_edit.setPlaceholderText("Digite uma mensagem ou utilize @ para mencionar alguem...")
        self.text_edit.setAcceptRichText(False)
        self.text_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        self.text_edit.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._line_height = QFontMetrics(self.text_edit.font()).lineSpacing()
        self._height_animation: QParallelAnimationGroup | None = None
        self.text_edit.textChanged.connect(self._on_text_changed)
        self.text_edit.send_requested.connect(self.send_requested.emit)
        self.text_edit.image_paste_requested.connect(self.add_clipboard_image)
        self.text_edit.file_paste_requested.connect(self.add_attachment_paths)
        self.text_edit.mention_query_changed.connect(self._on_mention_query_changed)
        self.text_edit.navigate_mention.connect(lambda delta: self._mention_popup.move_selection(delta))
        self.text_edit.confirm_mention.connect(lambda: self._mention_popup.confirm_selection())
        self.text_edit.cancel_mention.connect(self._close_mention_popup)
        row.addWidget(self.text_edit, 1)

        self.mic_btn = self._icon_button("mic", "Gravar audio (em breve)")
        self.mic_btn.clicked.connect(lambda: self.action_unavailable.emit("mic"))
        row.addWidget(self.mic_btn)
        row.setAlignment(self.mic_btn, Qt.AlignBottom)

        self.send_btn = QPushButton()
        self.send_btn.setObjectName("ChatSendButton")
        send_icon = QIcon()
        send_icon.addPixmap(make_icon("send", palette.get("accent_text", "#ffffff"), 18).pixmap(18, 18), QIcon.Mode.Normal)
        send_icon.addPixmap(make_icon("send", palette.get("disabled", palette.get("muted", "#94a3b8")), 18).pixmap(18, 18), QIcon.Mode.Disabled)
        self.send_btn.setIcon(send_icon)
        self.send_btn.setIconSize(QSize(18, 18))
        self.send_btn.setFixedSize(36, 36)
        self.send_btn.setToolTip("Enviar mensagem")
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setStyleSheet(f"""
            QPushButton#ChatSendButton {{
                background: {palette.get('accent', '#0078d4')};
                border: none;
                border-radius: 18px;
            }}
            QPushButton#ChatSendButton:hover:enabled {{
                background: {palette.get('accent_hover', '#005a9e')};
            }}
            QPushButton#ChatSendButton:disabled {{
                background: {palette.get('surface_alt', '#e2e8f0')};
            }}
        """)
        self.send_btn.setEnabled(False)
        self.send_btn.clicked.connect(self.send_requested.emit)
        row.addWidget(self.send_btn)
        row.setAlignment(self.send_btn, Qt.AlignBottom)
        outer.addLayout(row)

        self.question_checkbox = QCheckBox("Solicitar resposta")
        self.question_checkbox.setVisible(False)
        self.question_checkbox.toggled.connect(self._update_due_controls_visibility)
        checkbox_row = QHBoxLayout()
        checkbox_row.addStretch()
        checkbox_row.addWidget(self.question_checkbox)
        outer.addLayout(checkbox_row)

        self.due_checkbox = QCheckBox("Definir prazo")
        self.due_checkbox.setVisible(False)
        self.due_checkbox.toggled.connect(self._update_due_controls_visibility)
        self.due_edit = QDateTimeEdit()
        self.due_edit.setCalendarPopup(True)
        self.due_edit.setDisplayFormat("dd/MM/yyyy HH:mm")
        self.due_edit.setDateTime(QDateTime.currentDateTime().addDays(1))
        self.due_edit.setVisible(False)
        due_row = QHBoxLayout()
        due_row.addStretch()
        due_row.addWidget(self.due_checkbox)
        due_row.addWidget(self.due_edit)
        outer.addLayout(due_row)

        self._mention_popup = _MentionPopup(self.service, parent=self)
        self._mention_popup.user_selected.connect(self._on_mention_selected)
        self._mention_popup.hide()

        self._resize_text_edit(animate=False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_text_edit(animate=False)

    def dragEnterEvent(self, event) -> None:
        if self._drop_paths(event.mimeData()):
            event.acceptProposedAction()
            self._set_drag_active(True)
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        if self._drop_paths(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._set_drag_active(False)
        paths = self._drop_paths(event.mimeData())
        if not paths:
            event.ignore()
            return
        self.add_attachment_paths(paths)
        self.text_edit.setFocus()
        event.acceptProposedAction()

    def _set_drag_active(self, active: bool) -> None:
        if active == self._drag_active:
            return
        self._drag_active = active
        if active:
            palette = self.service.palette
            self.setStyleSheet(
                f"QFrame#ComposeBar {{ background: {palette.get('surface', '#ffffff')}; "
                f"border: 2px dashed {palette.get('accent', '#0078d4')}; border-radius: 10px; }}"
            )
            self.setToolTip("Solte os arquivos para anexar")
            return
        self.setStyleSheet(self._base_style)
        self.setToolTip("")

    @staticmethod
    def _drop_paths(mime_data) -> list[str]:
        if not mime_data or not mime_data.hasUrls():
            return []
        return [url.toLocalFile() for url in mime_data.urls() if url.isLocalFile()]

    def _icon_button(self, icon_name: str, tooltip: str) -> QPushButton:
        button = QPushButton()
        button.setObjectName("GhostButton")
        button.setIcon(make_icon(icon_name, self.service.palette["accent"], 20))
        button.setIconSize(QSize(20, 20))
        button.setFixedSize(36, 36)
        button.setToolTip(tooltip)
        button.setCursor(Qt.PointingHandCursor)
        return button

    def set_mentionable_users(self, users: list[dict]):
        self._mentionable_users = users

    def _on_text_changed(self):
        self._resize_text_edit()
        self._update_question_checkbox()
        self._update_send_enabled()

    def _update_send_enabled(self):
        can_send = bool(self.text_edit.toPlainText().strip()) or bool(self._pending_attachments)
        self.send_btn.setEnabled(can_send and not self._sending)

    def _resize_text_edit(self, animate: bool = True):
        viewport_width = max(40, self.text_edit.viewport().width())
        document = self.text_edit.document()
        if abs(document.textWidth() - viewport_width) > 1:
            document.setTextWidth(viewport_width)

        doc_height = self.text_edit.document().size().height()
        padding = 14
        min_height = self._line_height + padding
        max_height = self._line_height * 6 + padding
        target = int(max(min_height, min(doc_height + padding, max_height)))
        overflow = doc_height + padding > max_height
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded if overflow else Qt.ScrollBarAlwaysOff)

        current = self.text_edit.height()
        if current == target:
            self.updateGeometry()
            self.height_changed.emit()
            return
        if not animate:
            self.text_edit.setFixedHeight(target)
            self.updateGeometry()
            self.height_changed.emit()
            return
        if self._height_animation is not None:
            self._height_animation.stop()
        min_anim = QPropertyAnimation(self.text_edit, b"minimumHeight", self.text_edit)
        min_anim.setDuration(160)
        min_anim.setStartValue(current)
        min_anim.setEndValue(target)
        min_anim.setEasingCurve(QEasingCurve.OutCubic)
        min_anim.valueChanged.connect(lambda _value: self.height_changed.emit())
        max_anim = QPropertyAnimation(self.text_edit, b"maximumHeight", self.text_edit)
        max_anim.setDuration(160)
        max_anim.setStartValue(current)
        max_anim.setEndValue(target)
        max_anim.setEasingCurve(QEasingCurve.OutCubic)
        max_anim.valueChanged.connect(lambda _value: self.height_changed.emit())
        group = QParallelAnimationGroup(self.text_edit)
        group.addAnimation(min_anim)
        group.addAnimation(max_anim)
        group.finished.connect(self._finish_height_change)
        self._height_animation = group
        group.start()

    def _finish_height_change(self):
        self.updateGeometry()
        self.height_changed.emit()

    def _update_question_checkbox(self):
        text = self.text_edit.toPlainText()
        valid_mention = bool(self._last_mentioned_name) and f"@{self._last_mentioned_name}" in text
        if not valid_mention:
            self._last_mentioned_user_id = None
            self._last_mentioned_name = None
            self.question_checkbox.setChecked(False)
        self.question_checkbox.setVisible(valid_mention)
        self._update_due_controls_visibility()

    def _update_due_controls_visibility(self):
        requesting_response = self.question_checkbox.isVisible() and self.question_checkbox.isChecked()
        self.due_checkbox.setVisible(requesting_response)
        if not requesting_response:
            self.due_checkbox.setChecked(False)
        self.due_edit.setVisible(requesting_response and self.due_checkbox.isChecked())

    def _on_mention_query_changed(self, query):
        if query is None:
            self._close_mention_popup()
            return
        self._mention_popup.set_users(self._mentionable_users)
        self._mention_popup.filter(query)
        point = self.text_edit.mapToGlobal(self.text_edit.rect().topLeft())
        self._mention_popup.move(point.x(), point.y() - self._mention_popup.sizeHint().height() - 6)
        self._mention_popup.show()

    def _close_mention_popup(self):
        self._mention_popup.hide()

    def _on_mention_selected(self, user: dict):
        cursor = self.text_edit.textCursor()
        text = self.text_edit.toPlainText()
        cursor_pos = cursor.position()
        at_index = text[:cursor_pos].rfind("@")
        if at_index == -1:
            self._close_mention_popup()
            return
        # marca a mencao ANTES de inserir o texto: insertText ja dispara
        # textChanged -> _update_question_checkbox de forma sincrona, entao
        # precisa achar o nome certo ja atualizado nesse momento. Tambem
        # troca a selecao num unico insertText (nao remove e insere em dois
        # passos) pra nao passar por um estado intermediario sem a mencao,
        # que faria essa mesma checagem achar que a mencao sumiu.
        self._last_mentioned_user_id = user["id"]
        self._last_mentioned_name = user["display_name"]
        cursor.setPosition(at_index)
        cursor.setPosition(cursor_pos, QTextCursor.KeepAnchor)
        cursor.insertText(f"@{user['display_name']} ")
        self.text_edit.setTextCursor(cursor)
        self._close_mention_popup()
        self.text_edit.setFocus()

    def _insert_at_symbol(self):
        self.text_edit.insertPlainText("@")
        self.text_edit.setFocus()

    def _open_emoji_popup(self):
        popup = _EmojiPopup(self)
        popup.emoji_selected.connect(self._insert_emoji)
        point = self.emoji_btn.mapToGlobal(self.emoji_btn.rect().topLeft())
        popup.move(point.x(), point.y() - popup.sizeHint().height() - 6)
        popup.show()

    def _insert_emoji(self, emoji: str):
        self.text_edit.insertPlainText(emoji)
        self.text_edit.setFocus()

    def body(self) -> str:
        return self.text_edit.toPlainText().strip()

    def pending_attachments(self) -> list[PendingChatAttachment]:
        return list(self._pending_attachments)

    def has_pending_attachments(self) -> bool:
        return bool(self._pending_attachments)

    def has_sendable_content(self) -> bool:
        return bool(self.body()) or bool(self._pending_attachments)

    def open_attachment_dialog(self):
        paths, _selected_filter = QFileDialog.getOpenFileNames(
            self,
            "Selecionar anexos",
            "",
            "Todos permitidos (*.jpg *.jpeg *.png *.webp *.mp4 *.mov *.avi *.pdf *.doc *.docx *.txt *.xls *.xlsx *.csv *.zip *.7z *.dwg *.dxf);;"
            "Imagens (*.jpg *.jpeg *.png *.webp);;"
            "Videos (*.mp4 *.mov *.avi);;"
            "PDF e documentos (*.pdf *.doc *.docx *.txt);;"
            "Planilhas (*.xls *.xlsx *.csv);;"
            "Arquivos CAD (*.dwg *.dxf);;"
            "Compactados (*.zip *.7z)",
        )
        self.add_attachment_paths(paths)

    def add_attachment_paths(self, paths: list[str], *, temporary: bool = False) -> None:
        if not paths:
            return
        existing = {str(item.local_path.resolve()).lower() for item in self._pending_attachments if item.local_path.exists()}
        added = False
        for raw_path in paths:
            if len(self._pending_attachments) >= MAX_ATTACHMENTS_PER_MESSAGE:
                self.attachment_warning.emit(f"Limite de {MAX_ATTACHMENTS_PER_MESSAGE} anexos por mensagem.")
                break
            if Path(raw_path).is_dir():
                self.attachment_warning.emit("Pastas nao podem ser anexadas diretamente. Compacte a pasta ou selecione os arquivos.")
                continue
            validation_error = validate_local_attachment(raw_path)
            if validation_error:
                self.attachment_warning.emit(validation_error)
                continue
            attachment = PendingChatAttachment.from_path(raw_path, temporary=temporary)
            key = str(attachment.local_path.resolve()).lower()
            if key in existing:
                self.attachment_warning.emit("Este arquivo ja foi adicionado.")
                continue
            existing.add(key)
            self._pending_attachments.append(attachment)
            added = True
        if added:
            self._render_attachments()
            self.text_edit.setFocus()

    def add_clipboard_image(self, image_data) -> None:
        image = image_data.toImage() if isinstance(image_data, QPixmap) else image_data
        if image is None or image.isNull():
            self.attachment_warning.emit("Nao foi possivel ler a imagem copiada.")
            return
        temp_dir = Path(tempfile.gettempdir()) / "industel_chat_clipboard"
        temp_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")[:-3]
        path = temp_dir / f"captura_{stamp}.png"
        if not image.save(str(path), "PNG"):
            self.attachment_warning.emit("Nao foi possivel preparar a imagem copiada.")
            return
        self.add_attachment_paths([str(path)], temporary=True)

    def remove_attachment(self, local_id: str) -> None:
        removed = [item for item in self._pending_attachments if item.local_id == local_id]
        self._pending_attachments = [item for item in self._pending_attachments if item.local_id != local_id]
        for item in removed:
            self._cleanup_temporary_attachment(item)
        self._render_attachments()

    def cancel_attachment(self, local_id: str) -> None:
        self.attachment_cancel_requested.emit(local_id)
        for item in self._pending_attachments:
            if item.local_id == local_id:
                item.state = AttachmentState.CANCELLED
                item.error = "Cancelado"
                self.attachments_queue.refresh_attachment(local_id)
                break

    def clear_attachments(self) -> None:
        for item in self._pending_attachments:
            self._cleanup_temporary_attachment(item)
        self._pending_attachments.clear()
        self._render_attachments()

    @staticmethod
    def _cleanup_temporary_attachment(attachment: PendingChatAttachment) -> None:
        if not attachment.temporary:
            return
        try:
            temp_dir = (Path(tempfile.gettempdir()) / "industel_chat_clipboard").resolve()
            local_path = attachment.local_path.resolve()
            if temp_dir in local_path.parents and local_path.exists():
                local_path.unlink()
        except OSError:
            pass

    def _render_attachments(self) -> None:
        self.attachments_queue.set_attachments(self._pending_attachments)
        self._update_send_enabled()
        self.updateGeometry()
        self.height_changed.emit()

    def set_sending(self, sending: bool) -> None:
        self._sending = sending
        self.attach_btn.setEnabled(not sending)
        self.note_btn.setEnabled(not sending)
        self.emoji_btn.setEnabled(not sending)
        self.mention_btn.setEnabled(not sending)
        self.mic_btn.setEnabled(not sending)
        self.text_edit.setEnabled(not sending)
        self._update_send_enabled()

    def message_type(self) -> str:
        return "PERGUNTA" if (self.question_checkbox.isVisible() and self.question_checkbox.isChecked()) else "MENSAGEM"

    def mentioned_user_id(self) -> int | None:
        # a mencao vale para qualquer mensagem (nao so Pergunta): o texto ja
        # foi casado contra um usuario real em _on_mention_selected, entao o
        # ID persiste enquanto o token "@Nome" continuar presente no texto.
        text = self.text_edit.toPlainText()
        if self._last_mentioned_user_id and self._last_mentioned_name and f"@{self._last_mentioned_name}" in text:
            return self._last_mentioned_user_id
        return None

    def due_at(self) -> datetime | None:
        if not (self.due_checkbox.isVisible() and self.due_checkbox.isChecked()):
            return None
        # QDateTimeEdit trabalha em hora local "ingenua" (sem fuso); anexa o
        # fuso local antes de mandar pro backend, senao o servidor armazena
        # como se fosse UTC e o prazo escolhido fica errado por horas.
        return self.due_edit.dateTime().toPython().astimezone()

    def reply_to_message_id(self) -> int | None:
        return self._reply_to_message_id

    def set_reply_preview(self, author_name: str | None, snippet: str | None, message_id: int) -> None:
        self._reply_to_message_id = message_id
        label_author = author_name or "-"
        label_snippet = (snippet or "").strip().replace("\n", " ")
        if len(label_snippet) > 90:
            label_snippet = label_snippet[:87] + "..."
        self._reply_preview_label.setText(f"Respondendo a {label_author}: “{label_snippet}”")
        self._reply_preview.setVisible(True)
        self.updateGeometry()
        self.height_changed.emit()
        self.text_edit.setFocus()

    def clear_reply_preview(self) -> None:
        self._reply_to_message_id = None
        self._reply_preview.setVisible(False)
        self.updateGeometry()
        self.height_changed.emit()

    def clear(self):
        self.text_edit.clear()
        self._last_mentioned_user_id = None
        self._last_mentioned_name = None
        self.question_checkbox.setChecked(False)
        self.question_checkbox.setVisible(False)
        self.due_checkbox.setChecked(False)
        self.due_edit.setDateTime(QDateTime.currentDateTime().addDays(1))
        self._update_due_controls_visibility()
        self.clear_reply_preview()
        self.clear_attachments()
        self._resize_text_edit()
        self.set_sending(False)

    def focus_with_mention(self, user: dict | None = None):
        self.text_edit.setFocus()
        if user is not None:
            self._on_mention_selected(user)
            self.question_checkbox.setChecked(True)
