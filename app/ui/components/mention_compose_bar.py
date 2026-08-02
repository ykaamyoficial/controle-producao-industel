from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from app.ui.icons import make_icon


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

        avatar = QLabel(_initials(user.get("display_name")))
        avatar.setFixedSize(26, 26)
        avatar.setAlignment(Qt.AlignCenter)
        avatar.setStyleSheet(
            f"background: {self.service.palette.get('accent', '#0078d4')}; "
            f"color: {self.service.palette.get('accent_text', '#ffffff')}; "
            "border-radius: 13px; font-weight: 700; font-size: 10px;"
        )
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

        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(f"background: {self.service.palette.get('muted', '#94a3b8')}; border-radius: 4px;")
        dot.setToolTip("Status de presenca nao disponivel nesta versao")
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

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._last_mentioned_user_id: int | None = None
        self._last_mentioned_name: str | None = None
        self._mentionable_users: list[dict] = []
        self._build()

    def _build(self):
        palette = self.service.palette
        self.setObjectName("ComposeBar")
        self.setStyleSheet(
            f"QFrame#ComposeBar {{ background: {palette.get('surface', '#ffffff')}; "
            f"border: 1px solid {palette.get('border', '#cbd5e1')}; border-radius: 10px; }}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 4)
        outer.setSpacing(2)

        row = QHBoxLayout()
        row.setSpacing(2)

        self.attach_btn = self._icon_button("attach", "Anexar arquivo (em breve)")
        self.attach_btn.clicked.connect(lambda: self.action_unavailable.emit("attach"))
        row.addWidget(self.attach_btn)

        self.emoji_btn = self._icon_button("emoji", "Emojis")
        self.emoji_btn.clicked.connect(self._open_emoji_popup)
        row.addWidget(self.emoji_btn)

        self.mention_btn = self._icon_button("at", "Mencionar usuario")
        self.mention_btn.clicked.connect(self._insert_at_symbol)
        row.addWidget(self.mention_btn)

        self.text_edit = _ComposeTextEdit()
        self.text_edit.setObjectName("ComposeTextEdit")
        self.text_edit.setStyleSheet("QTextEdit#ComposeTextEdit { border: none; background: transparent; }")
        self.text_edit.setPlaceholderText("Digite uma mensagem ou utilize @ para mencionar alguem...")
        self.text_edit.setAcceptRichText(False)
        self._line_height = QFontMetrics(self.text_edit.font()).lineSpacing()
        self.text_edit.textChanged.connect(self._on_text_changed)
        self.text_edit.send_requested.connect(self.send_requested.emit)
        self.text_edit.mention_query_changed.connect(self._on_mention_query_changed)
        self.text_edit.navigate_mention.connect(lambda delta: self._mention_popup.move_selection(delta))
        self.text_edit.confirm_mention.connect(lambda: self._mention_popup.confirm_selection())
        self.text_edit.cancel_mention.connect(self._close_mention_popup)
        row.addWidget(self.text_edit, 1)

        self.mic_btn = self._icon_button("mic", "Gravar audio (em breve)")
        self.mic_btn.clicked.connect(lambda: self.action_unavailable.emit("mic"))
        row.addWidget(self.mic_btn)

        self.send_btn = QPushButton()
        self.send_btn.setObjectName("AccentButton")
        self.send_btn.setIcon(make_icon("send", "#ffffff", 16))
        self.send_btn.setIconSize(QSize(16, 16))
        self.send_btn.setFixedSize(34, 34)
        self.send_btn.setStyleSheet("border-radius: 17px;")
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.clicked.connect(self.send_requested.emit)
        row.addWidget(self.send_btn)
        outer.addLayout(row)

        self.question_checkbox = QCheckBox("Marcar como Pergunta")
        self.question_checkbox.setVisible(False)
        checkbox_row = QHBoxLayout()
        checkbox_row.addStretch()
        checkbox_row.addWidget(self.question_checkbox)
        outer.addLayout(checkbox_row)

        self._mention_popup = _MentionPopup(self.service, parent=self)
        self._mention_popup.user_selected.connect(self._on_mention_selected)
        self._mention_popup.hide()

        self._resize_text_edit()

    def _icon_button(self, icon_name: str, tooltip: str) -> QPushButton:
        button = QPushButton()
        button.setObjectName("GhostButton")
        button.setIcon(make_icon(icon_name, self.service.palette["accent"], 18))
        button.setIconSize(QSize(18, 18))
        button.setFixedSize(30, 30)
        button.setToolTip(tooltip)
        button.setCursor(Qt.PointingHandCursor)
        return button

    def set_mentionable_users(self, users: list[dict]):
        self._mentionable_users = users

    def _on_text_changed(self):
        self._resize_text_edit()
        self._update_question_checkbox()

    def _resize_text_edit(self):
        doc_height = self.text_edit.document().size().height()
        padding = 14
        min_height = self._line_height + padding
        max_height = self._line_height * 6 + padding
        target = max(min_height, min(doc_height + padding, max_height))
        self.text_edit.setFixedHeight(int(target))
        overflow = doc_height + padding > max_height
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded if overflow else Qt.ScrollBarAlwaysOff)

    def _update_question_checkbox(self):
        text = self.text_edit.toPlainText()
        valid_mention = bool(self._last_mentioned_name) and f"@{self._last_mentioned_name}" in text
        if not valid_mention:
            self._last_mentioned_user_id = None
            self._last_mentioned_name = None
            self.question_checkbox.setChecked(False)
        self.question_checkbox.setVisible(valid_mention)

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

    def message_type(self) -> str:
        return "PERGUNTA" if (self.question_checkbox.isVisible() and self.question_checkbox.isChecked()) else "MENSAGEM"

    def mentioned_user_id(self) -> int | None:
        return self._last_mentioned_user_id if self.message_type() == "PERGUNTA" else None

    def clear(self):
        self.text_edit.clear()
        self._last_mentioned_user_id = None
        self._last_mentioned_name = None
        self.question_checkbox.setChecked(False)
        self.question_checkbox.setVisible(False)
        self._resize_text_edit()

    def focus_with_mention(self, user: dict | None = None):
        self.text_edit.setFocus()
        if user is not None:
            self._on_mention_selected(user)
            self.question_checkbox.setChecked(True)
