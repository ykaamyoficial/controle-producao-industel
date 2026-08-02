from __future__ import annotations

import html
from datetime import datetime, timedelta

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.ui.animations import fade_in
from app.ui.background_worker import start_worker
from app.ui.components.mention_compose_bar import MentionComposeBar
from app.ui.components.modern_button import ModernButton
from app.ui.components.toast_notification import ToastNotification
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.icons import make_icon
from app.ui.styles import status_color


FILTER_OPTIONS = [
    ("TODAS", "Todas"),
    ("MENSAGEM", "Mensagens"),
    ("OBSERVACAO", "Observacoes"),
    ("PERGUNTA", "Perguntas"),
    ("EVENTO_SISTEMA", "Eventos do sistema"),
]


def _messages_to_entries(messages: list[dict]) -> list[dict]:
    return [
        {
            "id": message.get("id"),
            "source": "chat",
            "entry_kind": message.get("message_type"),
            "author_user_id": message.get("author_user_id"),
            "author_name": message.get("author_name"),
            "mentioned_user_id": message.get("mentioned_user_id"),
            "mentioned_user_name": message.get("mentioned_user_name"),
            "question_status": message.get("question_status"),
            "body": message.get("body"),
            "area": None,
            "event_type": None,
            "from_status": None,
            "to_status": None,
            "created_at": message.get("created_at"),
        }
        for message in messages
    ]


def _format_datetime(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    return parsed.strftime("%d/%m/%Y %H:%M")


def _parse_day(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _day_label(day) -> str:
    today = datetime.now().date()
    if day == today:
        return "Hoje"
    if day == today - timedelta(days=1):
        return "Ontem"
    return day.strftime("%d/%m/%Y")


class ChatConversationPanel(QWidget):
    """Timeline + composicao de uma conversa (proposta ou Chat Geral).
    Widget reaproveitavel: usado tanto dentro do dialogo modal quanto
    embutido na coluna central da tela "Chats". Mensagens do time chegam
    misturadas com observacoes das areas e eventos automaticos, que o
    backend ja registra a cada mudanca de status — aqui so mostramos
    tudo junto, sem duplicar nada."""

    entries_loaded = Signal()

    def __init__(self, service, proposal_id: int | None = None, conversation_id: int | None = None, parent=None):
        super().__init__(parent)
        self.service = service
        self.proposal_id = proposal_id
        self.conversation_id = conversation_id
        self.entries: list[dict] = []
        self._refresh_thread = None
        self._active_filter = "TODAS"
        self._filter_buttons: dict[str, QPushButton] = {}
        self._area_chip_values: list[str] = []
        self._rendered_entry_keys: set[tuple] = set()
        self._scroll_animation: QPropertyAnimation | None = None
        self._mentionable_names: list[str] = []
        self.proposal: dict | None = None

        if proposal_id is not None:
            try:
                self.proposal = self.service.get_process_dict(proposal_id)
            except Exception:
                self.proposal = None

        self._build()
        self.refresh()

    def title(self) -> str:
        if self.proposal_id is None:
            return "Chat Geral"
        if self.proposal:
            return f"Chat — {self.proposal.get('proposta') or self.proposal_id} — {self.proposal.get('cliente') or ''}"
        return "Chat da proposta"

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        if self.proposal_id is not None:
            root.addWidget(self._build_proposal_header())

        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)
        filter_row.addWidget(QLabel("Mostrar:"))
        self._filter_row_layout = filter_row
        for value, label in FILTER_OPTIONS:
            self._add_filter_pill(value, label)
        filter_row.addStretch()
        refresh_btn = ModernButton("Atualizar", "search")
        refresh_btn.clicked.connect(self.refresh)
        filter_row.addWidget(refresh_btn)
        root.addLayout(filter_row)

        self.loading = QLabel("Carregando...")
        self.loading.setObjectName("Caption")
        self.loading.setVisible(False)
        root.addWidget(self.loading)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.feed = QWidget()
        self.feed_layout = QVBoxLayout(self.feed)
        self.feed_layout.setContentsMargins(4, 4, 4, 4)
        self.feed_layout.setSpacing(4)
        self.feed_layout.addStretch()
        self.scroll.setWidget(self.feed)
        root.addWidget(self.scroll, 1)

        self.compose_bar = MentionComposeBar(self.service)
        self.compose_bar.send_requested.connect(self.send_message)
        self.compose_bar.action_unavailable.connect(self._show_action_unavailable)
        root.addWidget(self.compose_bar)

        self._load_mentionable_users()

    def _build_proposal_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("KpiCard")
        outer = QVBoxLayout(header)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)

        proposal = self.proposal or {}
        area, _label, status = self.service.current_location(proposal) if proposal else ("", "", "")

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        proposal_label = QLabel(proposal.get("proposta") or str(self.proposal_id))
        proposal_label.setStyleSheet("font-size: 20px; font-weight: 800;")
        title_row.addWidget(proposal_label)
        if status:
            bg, fg = status_color(status, self.service.palette, area or "")
            status_badge = QLabel(self.service.status_label(status))
            status_badge.setStyleSheet(
                f"background: {bg}; color: {fg}; border-radius: 10px; padding: 3px 12px; font-weight: 700;"
            )
            title_row.addWidget(status_badge)
        title_row.addStretch()
        outer.addLayout(title_row)

        details_grid = QGridLayout()
        details_grid.setHorizontalSpacing(24)
        details_grid.setVerticalSpacing(2)
        fields = [
            ("Cliente", proposal.get("cliente") or "-"),
            ("Obra/Site", proposal.get("obra_site") or "-"),
            ("Area atual", str(area or "-").replace("_", " ").title()),
            ("Prazo", proposal.get("prazo_entrega") or "-"),
            ("Peso", f"{proposal.get('peso') or '0'} kg"),
        ]
        for index, (label, value) in enumerate(fields):
            caption = QLabel(label)
            caption.setObjectName("Caption")
            content = QLabel(str(value))
            content.setStyleSheet("font-weight: 700;")
            cell = QVBoxLayout()
            cell.setSpacing(0)
            cell.addWidget(caption)
            cell.addWidget(content)
            details_grid.addLayout(cell, 0, index)
        outer.addLayout(details_grid)
        return header

    def _add_filter_pill(self, value: str, label: str):
        button = ModernButton(label, accent=(value == "TODAS"))
        button.setObjectName("AccentButton" if value == "TODAS" else "GhostButton")
        button.clicked.connect(lambda _checked=False, v=value: self._set_filter(v))
        self._filter_buttons[value] = button
        self._filter_row_layout.addWidget(button)

    def _set_filter(self, value: str):
        self._active_filter = value
        for key, button in self._filter_buttons.items():
            button.setObjectName("AccentButton" if key == value else "GhostButton")
            button.style().unpolish(button)
            button.style().polish(button)
        self._render_entries()

    def _update_area_chips(self):
        areas = sorted({entry.get("area") for entry in self.entries if entry.get("area")})
        if areas == self._area_chip_values:
            return
        for value in self._area_chip_values:
            button = self._filter_buttons.pop(f"AREA:{value}", None)
            if button:
                self._filter_row_layout.removeWidget(button)
                button.deleteLater()
        self._area_chip_values = areas
        for area in areas:
            label = str(area).replace("_", " ").title()
            self._add_filter_pill(f"AREA:{area}", label)
        if self._active_filter not in self._filter_buttons:
            self._active_filter = "TODAS"
            self._filter_buttons["TODAS"].setObjectName("AccentButton")

    def _load_mentionable_users(self):
        try:
            users = self.service.chat_mentionable_users()
        except Exception:
            users = []
        current_user_id = (self.service.user or {}).get("id")
        others = [user for user in users if user.get("id") != current_user_id]
        self.compose_bar.set_mentionable_users(others)
        self._mentionable_names = [user.get("display_name") for user in users if user.get("display_name")]

    def _show_action_unavailable(self, action: str):
        messages = {
            "attach": "Anexos ainda nao estao disponiveis nesta versao.",
            "mic": "Gravacao de audio ainda nao esta disponivel nesta versao.",
        }
        ToastNotification(self.window(), messages.get(action, "Ainda nao disponivel nesta versao."), "error")

    def refresh(self):
        self._set_loading(True)
        if self.proposal_id is not None:
            loader = lambda: self.service.chat_proposal_timeline(self.proposal_id)
        else:
            loader = lambda: {
                "conversation_id": self.conversation_id,
                "items": _messages_to_entries(self.service.chat_messages(self.conversation_id)),
            }
        self._refresh_thread = start_worker(self, loader, self._refresh_success, self._refresh_error)

    def _refresh_success(self, timeline: dict):
        self.conversation_id = timeline.get("conversation_id")
        self.entries = timeline.get("items") or []
        self._update_area_chips()
        self._render_entries()
        self._set_loading(False)
        self._mark_read()
        self.entries_loaded.emit()

    def _refresh_error(self, exc):
        self._set_loading(False)
        ToastNotification(self.window(), str(exc), "error")

    def _set_loading(self, loading: bool):
        self.loading.setVisible(loading)

    def participants(self) -> list[dict]:
        seen: dict[int, dict] = {}
        for entry in self.entries:
            author_id = entry.get("author_user_id")
            if not author_id or author_id in seen:
                continue
            seen[author_id] = {"id": author_id, "name": entry.get("author_name") or "-", "area": entry.get("area")}
        return list(seen.values())

    def focus_question_mode(self, mentioned_user: dict | None = None):
        self.compose_bar.focus_with_mention(mentioned_user)

    def _mark_read(self):
        if not self.conversation_id:
            return
        chat_entries = [entry for entry in self.entries if entry.get("source") == "chat"]
        if not chat_entries:
            return
        last_id = max(int(entry["id"]) for entry in chat_entries)
        try:
            self.service.chat_mark_read(self.conversation_id, last_id)
        except Exception:
            pass

    def _entry_style(self, kind: str) -> tuple[str, str]:
        palette = self.service.palette
        if kind == "MENSAGEM":
            return "chat", palette.get("accent", "#0078d4")
        if kind == "PERGUNTA":
            return "question", palette.get("warning", "#d97706")
        if kind == "OBSERVACAO":
            return "doc", palette.get("success", "#16a34a")
        return "gear", palette.get("muted", "#94a3b8")

    def _entry_matches_filter(self, entry: dict) -> bool:
        if self._active_filter == "TODAS":
            return True
        if self._active_filter.startswith("AREA:"):
            return entry.get("area") == self._active_filter[5:]
        return entry.get("entry_kind") == self._active_filter

    def _render_entries(self):
        while self.feed_layout.count() > 1:
            item = self.feed_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        current_user_id = (self.service.user or {}).get("id")
        newly_seen_keys = []
        last_day = None
        for entry in self.entries:
            if not self._entry_matches_filter(entry):
                continue
            entry_day = _parse_day(entry.get("created_at"))
            if entry_day is not None and entry_day != last_day:
                self.feed_layout.insertWidget(self.feed_layout.count() - 1, self._build_day_separator(entry_day))
                last_day = entry_day
            key = (entry.get("source"), entry.get("id"))
            is_new = key not in self._rendered_entry_keys
            card = self._build_entry_widget(entry, current_user_id)
            self.feed_layout.insertWidget(self.feed_layout.count() - 1, card)
            if is_new:
                newly_seen_keys.append(key)
                fade_in(card, duration=220)
        self._rendered_entry_keys.update(newly_seen_keys)
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _build_day_separator(self, day) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 4)
        label = QLabel(_day_label(day))
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(
            f"background: {self.service.palette.get('surface_alt', '#e2e8f0')}; "
            f"color: {self.service.palette.get('muted', '#64748b')}; "
            "border-radius: 10px; padding: 2px 14px; font-weight: 700; font-size: 11px;"
        )
        layout.addStretch()
        layout.addWidget(label)
        layout.addStretch()
        return container

    def _scroll_to_bottom(self):
        bar = self.scroll.verticalScrollBar()
        target = bar.maximum()
        if bar.value() == target:
            return
        self._scroll_animation = QPropertyAnimation(bar, b"value", self)
        self._scroll_animation.setDuration(280)
        self._scroll_animation.setStartValue(bar.value())
        self._scroll_animation.setEndValue(target)
        self._scroll_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._scroll_animation.start()

    def _highlight_mentions(self, text: str) -> str:
        escaped = html.escape(text).replace("\n", "<br>")
        color = self.service.palette.get("accent", "#0078d4")
        for name in sorted(self._mentionable_names, key=len, reverse=True):
            token = f"@{html.escape(name)}"
            if token in escaped:
                escaped = escaped.replace(token, f'<span style="color:{color}; font-weight:700;">{token}</span>')
        return escaped

    def _build_entry_widget(self, entry: dict, current_user_id) -> QWidget:
        card = QFrame()
        card.setObjectName("Panel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(2)

        kind = entry.get("entry_kind") or "EVENTO_SISTEMA"
        icon_name, color = self._entry_style(kind)
        palette = self.service.palette
        card.setStyleSheet(
            f"QFrame#Panel {{ background: {palette.get('surface', '#ffffff')}; "
            f"border: 1px solid {palette.get('border', '#cbd5e1')}; "
            f"border-left: 3px solid {color}; border-radius: 6px; }}"
            f"QFrame#Panel:hover {{ background: {palette.get('surface_alt', palette.get('surface', '#ffffff'))}; "
            f"border-color: {palette.get('border', '#cbd5e1')}; border-left: 3px solid {color}; }}"
        )

        header = QHBoxLayout()
        header.setSpacing(5)
        icon_label = QLabel()
        icon_label.setPixmap(make_icon(icon_name, color, 13).pixmap(13, 13))
        header.addWidget(icon_label)
        subtitle = entry.get("author_name") or ("Sistema" if kind == "EVENTO_SISTEMA" else "-")
        if entry.get("area") and kind in {"OBSERVACAO", "EVENTO_SISTEMA"}:
            area_label = str(entry["area"]).replace("_", " ").title()
            subtitle = f"{area_label} - {subtitle}" if subtitle != "-" else area_label
        if entry.get("mentioned_user_name"):
            subtitle = f"{subtitle} -> {entry['mentioned_user_name']}"
        title_label = QLabel(subtitle)
        title_label.setStyleSheet(f"font-weight: 600; font-size: 11px; color: {palette.get('muted', '#64748b')};")
        header.addWidget(title_label)
        header.addStretch()
        time_label = QLabel(_format_datetime(entry.get("created_at")))
        time_label.setStyleSheet(f"font-size: 10px; color: {palette.get('muted', '#94a3b8')};")
        header.addWidget(time_label)
        layout.addLayout(header)

        body_text = entry.get("body") or ""
        if not body_text and kind == "EVENTO_SISTEMA":
            to_status = entry.get("to_status")
            body_text = self.service.status_label(to_status) if to_status else (entry.get("event_type") or "-")
        body_label = QLabel()
        body_label.setTextFormat(Qt.RichText)
        body_label.setText(self._highlight_mentions(body_text) if body_text else "-")
        body_label.setStyleSheet("font-size: 13px;")
        body_label.setWordWrap(True)
        layout.addWidget(body_label)

        if kind == "PERGUNTA":
            answered = entry.get("question_status") == "RESPONDIDA"
            status_label = QLabel("Respondida" if answered else "Aguardando resposta")
            status_label.setStyleSheet(f"font-size: 10px; color: {palette.get('muted', '#94a3b8')};")
            layout.addWidget(status_label)
            if not answered and entry.get("mentioned_user_id") == current_user_id:
                answer_btn = ModernButton("Responder", "status")
                answer_btn.clicked.connect(lambda _checked=False, message_id=entry["id"]: self._answer_question(message_id))
                answer_row = QHBoxLayout()
                answer_row.addWidget(answer_btn)
                answer_row.addStretch()
                layout.addLayout(answer_row)

        if kind in {"MENSAGEM", "PERGUNTA"} and entry.get("source") == "chat" and entry.get("author_user_id") == current_user_id:
            seen_by = int(entry.get("seen_by_count") or 0)
            if seen_by <= 0:
                receipt_text = "Entregue"
            elif seen_by == 1:
                receipt_text = "Lida"
            else:
                receipt_text = f"Visualizada por {seen_by} usuarios"
            receipt_label = QLabel(receipt_text)
            receipt_label.setStyleSheet(f"font-size: 10px; color: {palette.get('muted', '#94a3b8')};")
            receipt_row = QHBoxLayout()
            receipt_row.addStretch()
            receipt_row.addWidget(receipt_label)
            layout.addLayout(receipt_row)

        return card

    def _answer_question(self, message_id: int):
        text, ok = QInputDialog.getMultiLineText(self, "Responder pergunta", "Resposta:")
        if not ok or not text.strip():
            return
        try:
            self.service.chat_answer_question(message_id, text.strip())
        except Exception as exc:
            ToastNotification(self.window(), str(exc), "error")
            return
        ToastNotification(self.window(), "Resposta enviada.", "success")
        self.refresh()

    def send_message(self):
        body = self.compose_bar.body()
        if not body:
            ToastNotification(self.window(), "Escreva uma mensagem antes de enviar.", "error")
            return
        if not self.conversation_id:
            ToastNotification(self.window(), "Conversa ainda nao carregada, tente novamente.", "error")
            return
        message_type = self.compose_bar.message_type()
        mentioned_user_id = self.compose_bar.mentioned_user_id()
        try:
            self.service.chat_send_message(self.conversation_id, body, message_type, mentioned_user_id)
        except Exception as exc:
            ToastNotification(self.window(), str(exc), "error")
            return
        self.compose_bar.clear()
        self.refresh()


class ProposalChatDialog(QDialog):
    """Casca fina em cima de ChatConversationPanel — mesmo comportamento de
    sempre, so que o feed/timeline/composicao agora vive num QWidget
    reaproveitavel (tambem usado embutido na tela "Chats")."""

    def __init__(self, service, proposal_id: int | None = None, conversation_id: int | None = None, parent=None):
        super().__init__(parent)
        self.service = service
        apply_large_dialog_geometry(self, parent, width_ratio=0.62, height_ratio=0.82, minimum_width=760, minimum_height=580)
        style_dialog_from_parent(self, parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)
        self.panel = ChatConversationPanel(service, proposal_id=proposal_id, conversation_id=conversation_id, parent=self)
        root.addWidget(self.panel, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        close_btn = ModernButton("Fechar", "clear")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        root.addLayout(footer)

        self.setWindowTitle(self.panel.title())

    @property
    def conversation_id(self):
        return self.panel.conversation_id

    @property
    def entries(self):
        return self.panel.entries

    def refresh(self):
        self.panel.refresh()
