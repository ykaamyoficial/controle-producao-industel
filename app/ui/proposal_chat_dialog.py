from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.ui.animations import fade_in
from app.ui.background_worker import start_worker
from app.ui.components.app_icon_button import AppIconButton
from app.ui.components.mention_compose_bar import MentionComposeBar
from app.ui.components.modern_button import ModernButton
from app.ui.components.proposal_activity_panel import ProposalActivityPanel
from app.ui.components.timeline_entries import (
    GROUP_WINDOW_SECONDS,
    CurrentUserMessageWidget,
    DirectedQuestionWidget,
    InternalNoteWidget,
    OtherUserMessageWidget,
    ReplyMessageWidget,
    TimelineDaySeparator,
    TimelineEntryWidget,
    entry_fingerprint,
)
from app.ui.components.toast_notification import ToastNotification
from app.ui.dialog_utils import apply_large_dialog_geometry, style_dialog_from_parent
from app.ui.icons import AppIcons, IconSize, make_icon
from app.ui.process_detail_dialog import ProcessDetailDialog
from app.ui.styles import status_color


NOTE_AREA_OPTIONS = [
    "CONTROLE GERAL",
    "PRODUCAO",
    "GALVANIZACAO",
    "EXPEDICAO",
    "FISCAL",
    "ALMOXARIFADO",
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
            "answered_message_id": message.get("answered_message_id"),
            "body": message.get("body"),
            "area": message.get("area"),
            "created_at": message.get("created_at"),
            "seen_by_count": message.get("seen_by_count"),
        }
        for message in messages
    ]


class InternalNoteDialog(QDialog):
    """Dialogo compacto para registrar uma nota interna manual — nunca
    disparado automaticamente, so quando o usuario escolhe explicitamente
    "Registrar nota interna" no composer."""

    def __init__(self, parent=None, mentionable_users: list[dict] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Registrar nota interna")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        area_label = QLabel("Area de origem")
        layout.addWidget(area_label)
        self.area_combo = QComboBox()
        for area in NOTE_AREA_OPTIONS:
            self.area_combo.addItem(area.title(), area)
        layout.addWidget(self.area_combo)

        recipient_label = QLabel("Destinatario (opcional)")
        layout.addWidget(recipient_label)
        self.recipient_combo = QComboBox()
        self.recipient_combo.addItem("Nenhum — visivel para quem acessa a conversa", None)
        for user in mentionable_users or []:
            self.recipient_combo.addItem(user.get("display_name") or "-", user.get("id"))
        layout.addWidget(self.recipient_combo)

        self.important_checkbox = QCheckBox("Marcar como importante")
        layout.addWidget(self.important_checkbox)

        body_label = QLabel("Nota")
        layout.addWidget(body_label)
        self.body_edit = QTextEdit()
        self.body_edit.setPlaceholderText("Descreva a informacao interna importante...")
        self.body_edit.setMinimumHeight(100)
        layout.addWidget(self.body_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_data(self) -> tuple[str, str, int | None, bool]:
        return (
            self.body_edit.toPlainText().strip(),
            self.area_combo.currentData(),
            self.recipient_combo.currentData(),
            self.important_checkbox.isChecked(),
        )


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


def _parse_datetime(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _day_label(day) -> str:
    today = datetime.now().date()
    if day == today:
        return "Hoje"
    if day == today - timedelta(days=1):
        return "Ontem"
    return day.strftime("%d/%m/%Y")


class ChatTabButton(QPushButton):
    """Item de navegacao com aparencia de aba (texto + indicador inferior),
    usado no cabecalho do chat para Atividade/Participantes/Informacoes.
    Puramente visual: quem chama continua responsavel por conectar o
    `clicked` e por chamar `set_active()` quando o estado que o botao
    representa mudar (painel aberto/fechado) - o widget nao sabe se a acao
    por tras dele e um toggle ou um disparo unico (ex.: abrir um dialogo)."""

    def __init__(self, text: str, icon, palette: dict, parent=None):
        super().__init__(text, parent)
        self._palette = palette
        self.setObjectName("ChatTabButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setIcon(make_icon(icon, palette.get("muted", "#64748b"), 15))
        self.setIconSize(QSize(15, 15))
        self.setFlat(True)
        self.set_active(False)

    def set_active(self, active: bool) -> None:
        palette = self._palette
        accent = palette.get("accent", "#0078d4")
        muted = palette.get("muted", "#64748b")
        text_color = palette.get("text", "#0f172a")
        color = accent if active else muted
        underline = accent if active else "transparent"
        self.setStyleSheet(f"""
            QPushButton#ChatTabButton {{
                background: transparent;
                border: none;
                border-bottom: 2px solid {underline};
                border-radius: 0;
                padding: 6px 2px 7px 2px;
                color: {color};
                font-weight: {700 if active else 600};
                font-size: 12px;
                text-align: left;
            }}
            QPushButton#ChatTabButton:hover {{
                color: {accent if active else text_color};
            }}
        """)


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
        self._entries_by_id: dict[int, dict] = {}
        self._refresh_thread = None
        self._refresh_in_flight = False
        self._refresh_pending = False
        self._last_marked_read_message_id: int | None = None
        self._scroll_animation: QPropertyAnimation | None = None
        self._mentionable_names: list[str] = []
        self._mentionable_users: list[dict] = []
        self._user_sectors: dict[int, str] = {}
        self._entry_widgets: dict[tuple, tuple[QWidget, TimelineEntryWidget]] = {}
        self._day_separator_widgets: dict[object, TimelineDaySeparator] = {}
        self._max_bubble_width = 420
        self._has_more_older = False
        self._oldest_created_at: str | None = None
        self._loading_older = False
        self._older_thread = None
        self.proposal: dict | None = None
        self.activity_panel: ProposalActivityPanel | None = None
        self._activity_open = False
        self._activity_animation: QParallelAnimationGroup | None = None
        self._pending_focus_message_id: int | None = None

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
        root.setSpacing(8)

        self.drawer: QFrame | None = None
        self._drawer_open = False
        self._drawer_animation: QParallelAnimationGroup | None = None
        self._drawer_participants_layout: QVBoxLayout | None = None

        if self.proposal_id is not None:
            root.addWidget(self._build_proposal_header())

            tabs_row = QHBoxLayout()
            tabs_row.setSpacing(18)
            palette = self.service.palette
            self.activity_btn = ChatTabButton("Atividade", AppIcons.HISTORY, palette)
            self.activity_btn.clicked.connect(self._toggle_activity_panel)
            tabs_row.addWidget(self.activity_btn)

            self.participants_btn = ChatTabButton("Participantes", AppIcons.CHAT, palette)
            self.participants_btn.clicked.connect(self._toggle_drawer)
            tabs_row.addWidget(self.participants_btn)

            self.info_header_btn = ChatTabButton("Informacoes", AppIcons.INFO, palette)
            self.info_header_btn.clicked.connect(self._open_full_details)
            tabs_row.addWidget(self.info_header_btn)
            tabs_row.addStretch()
            root.addLayout(tabs_row)
        else:
            refresh_row = QHBoxLayout()
            refresh_row.addStretch()
            refresh_btn = AppIconButton(AppIcons.REFRESH, palette=self.service.palette, size=IconSize.LG, tooltip="Atualizar conversa")
            refresh_btn.setFixedSize(36, 36)
            refresh_btn.clicked.connect(self.refresh)
            refresh_row.addWidget(refresh_btn)
            root.addLayout(refresh_row)

        self.loading = QLabel("Carregando...")
        self.loading.setObjectName("Caption")
        self.loading.setVisible(False)
        root.addWidget(self.loading)

        content_row = QHBoxLayout()
        content_row.setSpacing(0)

        left_col = QVBoxLayout()
        left_col.setSpacing(8)

        self._load_older_btn = ModernButton("Carregar mensagens anteriores", "history")
        self._load_older_btn.clicked.connect(self._load_older_messages)
        self._load_older_btn.setVisible(False)
        left_col.addWidget(self._load_older_btn)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.feed = QWidget()
        self.feed_layout = QVBoxLayout(self.feed)
        self.feed_layout.setContentsMargins(4, 4, 4, 4)
        self.feed_layout.setSpacing(4)
        self.feed_layout.addStretch()
        self.scroll.setWidget(self.feed)
        left_col.addWidget(self.scroll, 1)

        self._empty_state = self._build_empty_state()
        left_col.addWidget(self._empty_state, 1)

        self._new_messages_btn = AppIconButton(
            AppIcons.ARROW_DOWN,
            "Novas mensagens",
            color="#ffffff",
            accent=True,
            size=IconSize.SM,
            parent=self.scroll.viewport(),
        )
        self._new_messages_btn.clicked.connect(self._scroll_to_bottom_and_hide_button)
        self._new_messages_btn.hide()
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_value_changed)

        self.compose_bar = MentionComposeBar(self.service)
        self.compose_bar.send_requested.connect(self.send_message)
        self.compose_bar.action_unavailable.connect(self._show_action_unavailable)
        self.compose_bar.internal_note_requested.connect(self._open_internal_note_dialog)
        left_col.addWidget(self.compose_bar)

        content_row.addLayout(left_col, 1)

        if self.proposal_id is not None:
            content_row.addSpacing(8)
            content_row.addWidget(self._build_drawer())
            self.activity_panel = ProposalActivityPanel(self.service, self.proposal_id)
            content_row.addSpacing(8)
            content_row.addWidget(self.activity_panel)

        root.addLayout(content_row, 1)

        self._load_mentionable_users()

    def _build_empty_state(self) -> QWidget:
        widget = QWidget()
        widget.setVisible(False)
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(6)

        palette = self.service.palette
        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setPixmap(make_icon(AppIcons.CHAT, palette.get("muted", "#94a3b8"), 32).pixmap(32, 32))
        layout.addWidget(icon_label)

        title = QLabel("Nenhuma mensagem nesta proposta")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-weight: 700; font-size: 13px;")
        layout.addWidget(title)

        subtitle = QLabel("Inicie uma conversa com os participantes da proposta.")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setObjectName("Caption")
        layout.addWidget(subtitle)

        return widget

    def _update_empty_state(self) -> None:
        has_entries = bool(self.entries)
        self.scroll.setVisible(has_entries)
        self._empty_state.setVisible(not has_entries)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        new_width = max(240, int(self.scroll.viewport().width() * 0.68))
        if abs(new_width - self._max_bubble_width) > 6:
            self._max_bubble_width = new_width
            for _row, content in self._entry_widgets.values():
                self._apply_bubble_width(content)
            # setMaximumWidth() muda a largura de quebra do texto, o que muda a
            # altura necessaria de cada bolha — forca o QVBoxLayout a recalcular
            # tudo agora em vez de confiar soh na invalidacao implicita do Qt.
            self.feed_layout.invalidate()
            self.feed_layout.activate()
        self._reposition_new_messages_button()

    def _apply_bubble_width(self, content: TimelineEntryWidget):
        if isinstance(content, (CurrentUserMessageWidget, OtherUserMessageWidget, ReplyMessageWidget)):
            content.set_max_bubble_width(self._max_bubble_width)

    def _is_scrolled_to_bottom(self, threshold: int = 48) -> bool:
        bar = self.scroll.verticalScrollBar()
        return bar.value() >= bar.maximum() - threshold

    def _reposition_new_messages_button(self):
        btn = self._new_messages_btn
        btn.adjustSize()
        viewport = self.scroll.viewport()
        x = (viewport.width() - btn.width()) // 2
        y = viewport.height() - btn.height() - 12
        btn.move(max(0, x), max(0, y))

    def _show_new_messages_button(self):
        self._reposition_new_messages_button()
        self._new_messages_btn.show()
        self._new_messages_btn.raise_()

    def _scroll_to_bottom_and_hide_button(self):
        self._new_messages_btn.hide()
        self._scroll_to_bottom()

    def _on_scroll_value_changed(self, _value):
        if self._new_messages_btn.isVisible() and self._is_scrolled_to_bottom():
            self._new_messages_btn.hide()

    def _build_proposal_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("KpiCard")
        outer = QHBoxLayout(header)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(10)

        palette = self.service.palette
        proposal = self.proposal or {}
        area, _label, status = self.service.current_location(proposal) if proposal else ("", "", "")

        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        proposal_label = QLabel(proposal.get("proposta") or str(self.proposal_id))
        proposal_label.setStyleSheet("font-size: 17px; font-weight: 800;")
        title_col.addWidget(proposal_label)
        client_label = QLabel(proposal.get("cliente") or "-")
        client_label.setObjectName("Caption")
        title_col.addWidget(client_label)
        outer.addLayout(title_col)

        outer.addStretch()

        if status:
            bg, fg = status_color(status, palette, area or "")
            status_badge = QLabel(self.service.status_label(status))
            status_badge.setStyleSheet(
                f"background: {bg}; color: {fg}; border-radius: 9px; padding: 2px 10px; font-weight: 700; font-size: 11px;"
            )
            outer.addWidget(status_badge)

        refresh_btn = AppIconButton(AppIcons.REFRESH, palette=palette, size=IconSize.LG, tooltip="Atualizar conversa")
        refresh_btn.setFixedSize(36, 36)
        refresh_btn.clicked.connect(self.refresh)
        outer.addWidget(refresh_btn)

        self.info_btn = AppIconButton(AppIcons.INFO, palette=palette, size=IconSize.LG, tooltip="Ver detalhes da proposta")
        self.info_btn.setFixedSize(36, 36)
        self.info_btn.clicked.connect(self._toggle_drawer)
        outer.addWidget(self.info_btn)

        return header

    def _build_drawer(self) -> QFrame:
        self.drawer = QFrame()
        self.drawer.setObjectName("Panel")
        self.drawer.setMinimumWidth(0)
        self.drawer.setMaximumWidth(0)
        layout = QVBoxLayout(self.drawer)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("Detalhes da proposta")
        title.setStyleSheet("font-weight: 800;")
        layout.addWidget(title)

        proposal = self.proposal or {}
        area, _label, _status = self.service.current_location(proposal) if proposal else ("", "", "")
        fields = [
            ("Cliente", proposal.get("cliente") or "-"),
            ("Obra/Site", proposal.get("obra_site") or "-"),
            ("Prazo", proposal.get("prazo_entrega") or "-"),
            ("Peso", f"{proposal.get('peso') or '0'} kg"),
            ("Area atual", str(area or "-").replace("_", " ").title()),
        ]
        for label, value in fields:
            cell = QVBoxLayout()
            cell.setSpacing(0)
            caption = QLabel(label)
            caption.setObjectName("Caption")
            content = QLabel(str(value))
            content.setStyleSheet("font-weight: 700;")
            content.setWordWrap(True)
            cell.addWidget(caption)
            cell.addWidget(content)
            layout.addLayout(cell)

        participants_title = QLabel("Participantes")
        participants_title.setStyleSheet("font-weight: 800;")
        layout.addWidget(participants_title)
        self._drawer_participants_layout = QVBoxLayout()
        self._drawer_participants_layout.setSpacing(4)
        layout.addLayout(self._drawer_participants_layout)

        layout.addStretch()

        question_btn = ModernButton("Fazer pergunta", "chat")
        question_btn.clicked.connect(lambda: self.focus_question_mode())
        layout.addWidget(question_btn)

        return self.drawer

    def _toggle_drawer(self):
        if self.drawer is None:
            return
        self._drawer_open = not self._drawer_open
        if hasattr(self, "participants_btn"):
            self.participants_btn.set_active(self._drawer_open)
        target = 300 if self._drawer_open else 0
        if self._drawer_animation is not None:
            self._drawer_animation.stop()

        min_anim = QPropertyAnimation(self.drawer, b"minimumWidth", self.drawer)
        min_anim.setDuration(240)
        min_anim.setStartValue(self.drawer.minimumWidth())
        min_anim.setEndValue(target)
        min_anim.setEasingCurve(QEasingCurve.OutCubic)

        max_anim = QPropertyAnimation(self.drawer, b"maximumWidth", self.drawer)
        max_anim.setDuration(240)
        max_anim.setStartValue(self.drawer.maximumWidth())
        max_anim.setEndValue(target)
        max_anim.setEasingCurve(QEasingCurve.OutCubic)

        group = QParallelAnimationGroup(self.drawer)
        group.addAnimation(min_anim)
        group.addAnimation(max_anim)

        if self._drawer_open:
            effect = QGraphicsOpacityEffect(self.drawer)
            self.drawer.setGraphicsEffect(effect)
            opacity_anim = QPropertyAnimation(effect, b"opacity", self.drawer)
            opacity_anim.setDuration(240)
            opacity_anim.setStartValue(0.0)
            opacity_anim.setEndValue(1.0)
            opacity_anim.setEasingCurve(QEasingCurve.OutCubic)
            group.addAnimation(opacity_anim)
            group.finished.connect(lambda: self.drawer.setGraphicsEffect(None))

        self._drawer_animation = group
        group.start()

    def _toggle_activity_panel(self):
        if self.activity_panel is None:
            return
        self._activity_open = not self._activity_open
        if hasattr(self, "activity_btn"):
            self.activity_btn.set_active(self._activity_open)
        target = 340 if self._activity_open else 0
        if self._activity_animation is not None:
            self._activity_animation.stop()

        min_anim = QPropertyAnimation(self.activity_panel, b"minimumWidth", self.activity_panel)
        min_anim.setDuration(240)
        min_anim.setStartValue(self.activity_panel.minimumWidth())
        min_anim.setEndValue(target)
        min_anim.setEasingCurve(QEasingCurve.OutCubic)

        max_anim = QPropertyAnimation(self.activity_panel, b"maximumWidth", self.activity_panel)
        max_anim.setDuration(240)
        max_anim.setStartValue(self.activity_panel.maximumWidth())
        max_anim.setEndValue(target)
        max_anim.setEasingCurve(QEasingCurve.OutCubic)

        group = QParallelAnimationGroup(self.activity_panel)
        group.addAnimation(min_anim)
        group.addAnimation(max_anim)

        if self._activity_open:
            self.activity_panel.refresh()
            effect = QGraphicsOpacityEffect(self.activity_panel)
            self.activity_panel.setGraphicsEffect(effect)
            opacity_anim = QPropertyAnimation(effect, b"opacity", self.activity_panel)
            opacity_anim.setDuration(240)
            opacity_anim.setStartValue(0.0)
            opacity_anim.setEndValue(1.0)
            opacity_anim.setEasingCurve(QEasingCurve.OutCubic)
            group.addAnimation(opacity_anim)
            group.finished.connect(lambda: self.activity_panel.setGraphicsEffect(None))

        self._activity_animation = group
        group.start()

    def _open_full_details(self):
        if self.proposal_id is None:
            return
        dialog = ProcessDetailDialog(self.service, self.proposal_id, self)
        dialog.exec()

    def _refresh_drawer_participants(self):
        layout = self._drawer_participants_layout
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        participants = self.participants()
        if not participants:
            empty = QLabel("Sem participantes ainda.")
            empty.setObjectName("Caption")
            layout.addWidget(empty)
            return
        for person in participants:
            row = QHBoxLayout()
            name_label = QLabel(person.get("name") or "-")
            row.addWidget(name_label)
            row.addStretch()
            layout.addLayout(row)

    def _load_mentionable_users(self):
        try:
            users = self.service.chat_mentionable_users()
        except Exception:
            users = []
        current_user_id = (self.service.user or {}).get("id")
        others = [user for user in users if user.get("id") != current_user_id]
        self.compose_bar.set_mentionable_users(others)
        self._mentionable_users = others
        self._mentionable_names = [user.get("display_name") for user in users if user.get("display_name")]
        self._user_sectors = {user.get("id"): user.get("sector") for user in users if user.get("sector")}

    def _show_action_unavailable(self, action: str):
        messages = {
            "attach": "Anexos ainda nao estao disponiveis nesta versao.",
            "mic": "Gravacao de audio ainda nao esta disponivel nesta versao.",
        }
        ToastNotification(self.window(), messages.get(action, "Ainda nao disponivel nesta versao."), "error")

    def refresh(self):
        if self._refresh_in_flight:
            self._refresh_pending = True
            return
        self._refresh_in_flight = True
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
        self._has_more_older = bool(timeline.get("has_more"))
        self._oldest_created_at = self.entries[0].get("created_at") if self.entries else None
        self._update_load_older_button()
        self._annotate_entries()
        has_new_from_others = self._render_entries()
        self._update_empty_state()
        self._refresh_drawer_participants()
        self._set_loading(False)
        # so avanca o cursor de leitura se o usuario realmente estava no
        # fundo do scroll — se ele estava lendo historico quando este
        # refresh trouxe mensagem nova de outra pessoa, essa mensagem
        # continua nao lida ate ele efetivamente rolar ate ela (vale tanto
        # pro refresh manual quanto pro disparado por evento realtime).
        if not has_new_from_others:
            self._mark_read()
        self._consume_pending_focus()
        self.entries_loaded.emit()
        self._finish_refresh()

    def _update_load_older_button(self):
        self._load_older_btn.setVisible(self.proposal_id is not None and self._has_more_older)

    def _load_older_messages(self):
        if self._loading_older or self.proposal_id is None or not self._oldest_created_at:
            return
        self._loading_older = True
        self._load_older_btn.setEnabled(False)
        self._load_older_btn.setText("Carregando...")
        loader = lambda: self.service.chat_proposal_timeline(self.proposal_id, before=self._oldest_created_at, limit=100)
        self._older_thread = start_worker(self, loader, self._older_loaded, self._older_error)

    def _older_loaded(self, timeline: dict):
        self._loading_older = False
        self._load_older_btn.setEnabled(True)
        self._load_older_btn.setText("Carregar mensagens anteriores")
        older_entries = timeline.get("items") or []
        self._has_more_older = bool(timeline.get("has_more"))
        if older_entries:
            self.entries = older_entries + self.entries
            self._oldest_created_at = older_entries[0].get("created_at")
            self._annotate_entries()
        self._update_load_older_button()

        bar = self.scroll.verticalScrollBar()
        old_max = bar.maximum()
        old_value = bar.value()
        self._render_entries(suppress_autoscroll=True)

        def _restore_scroll():
            bar.setValue(old_value + (bar.maximum() - old_max))

        QTimer.singleShot(0, _restore_scroll)

    def _older_error(self, exc):
        self._loading_older = False
        self._load_older_btn.setEnabled(True)
        self._load_older_btn.setText("Carregar mensagens anteriores")
        ToastNotification(self.window(), str(exc), "error")

    def _annotate_entries(self):
        for entry in self.entries:
            if entry.get("source") == "chat":
                entry["author_sector"] = self._user_sectors.get(entry.get("author_user_id"))
        self._entries_by_id = {entry.get("id"): entry for entry in self.entries if entry.get("source") == "chat"}

    def _refresh_error(self, exc):
        self._set_loading(False)
        ToastNotification(self.window(), str(exc), "error")
        self._finish_refresh()

    def _finish_refresh(self):
        self._refresh_in_flight = False
        if self._refresh_pending:
            self._refresh_pending = False
            QTimer.singleShot(0, self.refresh)

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
        if self._last_marked_read_message_id is not None and last_id <= self._last_marked_read_message_id:
            return
        try:
            self.service.chat_mark_read(self.conversation_id, last_id)
        except Exception:
            return
        self._last_marked_read_message_id = last_id
        # so avisa depois que o backend confirmou — o badge global do
        # cabecalho nao pode adiantar a leitura.
        on_marked_read = getattr(self.service, "on_conversation_marked_read", None)
        if callable(on_marked_read):
            on_marked_read()

    def _compute_grouping(self, filtered: list[dict]) -> list[bool]:
        flags: list[bool] = []
        last_author = None
        last_time = None
        last_groupable = False
        for entry in filtered:
            groupable = (
                entry.get("source") == "chat"
                and entry.get("entry_kind") == "MENSAGEM"
                and not entry.get("answered_message_id")
            )
            author = entry.get("author_user_id")
            created = _parse_datetime(entry.get("created_at"))
            grouped = (
                groupable
                and last_groupable
                and author is not None
                and author == last_author
                and last_time is not None
                and created is not None
                and (created - last_time).total_seconds() <= GROUP_WINDOW_SECONDS
            )
            flags.append(grouped)
            last_author = author
            last_time = created
            last_groupable = groupable
        return flags

    def _dispatch_entry_widget(self, entry: dict, current_user_id, grouped: bool) -> tuple[QWidget, TimelineEntryWidget]:
        kind = entry.get("entry_kind") or "MENSAGEM"

        if entry.get("answered_message_id"):
            enriched = dict(entry)
            enriched["_reply_original"] = self._entries_by_id.get(entry.get("answered_message_id"))
            content = ReplyMessageWidget(enriched, self.service, current_user_id, self._mentionable_names, grouped)
            content.jump_to_message_requested.connect(self._jump_to_message)
            align = "right" if entry.get("author_user_id") == current_user_id else "left"
            return self._wrap_row(content, align), content
        if kind == "PERGUNTA":
            content = DirectedQuestionWidget(entry, self.service, current_user_id, self._mentionable_names, grouped)
            content.answer_requested.connect(self._answer_question)
            content.cancel_requested.connect(self._cancel_question)
            content.reassign_requested.connect(self._reassign_question)
            if entry.get("mentioned_user_id") == current_user_id and not entry.get("viewed_at"):
                try:
                    self.service.chat_mark_question_viewed(entry.get("id"))
                except Exception:
                    pass
            return content, content
        if kind == "NOTA_INTERNA":
            content = InternalNoteWidget(entry, self.service, current_user_id, self._mentionable_names, grouped)
            return content, content
        if entry.get("author_user_id") == current_user_id:
            content = CurrentUserMessageWidget(entry, self.service, current_user_id, self._mentionable_names, grouped)
            content.reply_requested.connect(self._start_reply)
            return self._wrap_row(content, "right"), content
        content = OtherUserMessageWidget(entry, self.service, current_user_id, self._mentionable_names, grouped)
        content.reply_requested.connect(self._start_reply)
        return self._wrap_row(content, "left"), content

    def _start_reply(self, message_id: int):
        original = self._entries_by_id.get(message_id)
        if original is None:
            return
        self.compose_bar.set_reply_preview(original.get("author_name"), original.get("body"), message_id)

    def _jump_to_message(self, message_id: int):
        cached = self._entry_widgets.get(("chat", message_id))
        if cached is None:
            ToastNotification(self.window(), "Mensagem original nao esta carregada nesta pagina.", "error")
            return
        row, _content = cached
        self.scroll.ensureWidgetVisible(row)
        self._flash_highlight(row)

    def focus_message(self, message_id: int):
        """Usado pela Central de Notificacoes: rola ate a mensagem/pergunta
        alvo e destaca. Se o timeline ainda nao carregou (refresh() em voo),
        agenda uma unica tentativa apos o proximo carregamento bem-sucedido."""
        if ("chat", message_id) in self._entry_widgets:
            self._jump_to_message(message_id)
            return
        self._pending_focus_message_id = message_id

    def _consume_pending_focus(self):
        message_id = getattr(self, "_pending_focus_message_id", None)
        if message_id is None:
            return
        self._pending_focus_message_id = None
        if ("chat", message_id) in self._entry_widgets:
            QTimer.singleShot(0, lambda: self._jump_to_message(message_id))

    def _flash_highlight(self, row: QWidget):
        original_style = row.styleSheet()
        row.setStyleSheet(original_style + "background: rgba(0, 120, 212, 60);")
        QTimer.singleShot(700, lambda: row.setStyleSheet(original_style))

    def _wrap_row(self, content: QWidget, align: str) -> QWidget:
        row = QWidget()
        row.setAttribute(Qt.WA_StyledBackground, True)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        if align in ("right", "center"):
            row_layout.addStretch()
        row_layout.addWidget(content)
        if align in ("left", "center"):
            row_layout.addStretch()
        return row

    def _render_entries(self, *, suppress_autoscroll: bool = False) -> bool:
        """Retorna True se chegou entrada nova de outra pessoa enquanto o
        usuario NAO estava no fundo do scroll (ou seja, ele esta lendo
        historico) — quem chama usa isso pra decidir se pode avancar o
        cursor de leitura (ETAPA 7: refresh disparado por evento realtime
        nao pode marcar como lida uma mensagem que o usuario nem chegou a
        ver por estar rolado pra cima)."""
        current_user_id = (self.service.user or {}).get("id")
        filtered = self.entries
        grouped_flags = self._compute_grouping(filtered)

        at_bottom = self._is_scrolled_to_bottom()
        has_new_from_others = False

        seen_keys: set[tuple] = set()
        seen_days: set = set()
        last_day = None
        insert_index = 0
        for entry, grouped in zip(filtered, grouped_flags):
            entry_day = _parse_day(entry.get("created_at"))
            if entry_day is not None and entry_day != last_day:
                separator = self._day_separator_widgets.get(entry_day)
                if separator is None:
                    separator = TimelineDaySeparator(_day_label(entry_day), self.service)
                    self._day_separator_widgets[entry_day] = separator
                else:
                    # reusa o widget existente (nao recria a cada refresh) — so
                    # atualiza o texto, caso "Hoje"/"Ontem" tenham ficado
                    # desatualizados por o app continuar aberto ate virar o dia.
                    separator.update_text(_day_label(entry_day))
                    self.feed_layout.removeWidget(separator)
                self.feed_layout.insertWidget(insert_index, separator)
                seen_days.add(entry_day)
                insert_index += 1
                last_day = entry_day

            key = (entry.get("source"), entry.get("id"))
            seen_keys.add(key)
            cached = self._entry_widgets.get(key)

            if cached is not None:
                row, content = cached
                if content._fingerprint != entry_fingerprint(entry, grouped):
                    content.update_entry(entry, grouped)
                self.feed_layout.removeWidget(row)
                self.feed_layout.insertWidget(insert_index, row)
            else:
                row, content = self._dispatch_entry_widget(entry, current_user_id, grouped)
                self._apply_bubble_width(content)
                self.feed_layout.insertWidget(insert_index, row)
                self._entry_widgets[key] = (row, content)
                is_mine = entry.get("source") == "chat" and entry.get("author_user_id") == current_user_id
                # Fade de opacidade apenas — nunca animar pos()/geometry() de um
                # widget gerenciado por layout (QVBoxLayout reposiciona os itens
                # a cada insercao/remocao, e uma animacao de posicao em voo fica
                # "puxando" o widget de volta para uma coordenada que o layout ja
                # abandonou, causando sobreposicao visual).
                if is_mine:
                    fade_in(row, duration=160)
                else:
                    fade_in(row, duration=220)
                    if not at_bottom:
                        has_new_from_others = True
            insert_index += 1

        for key in list(self._entry_widgets.keys()):
            if key not in seen_keys:
                row, _content = self._entry_widgets.pop(key)
                self.feed_layout.removeWidget(row)
                row.deleteLater()

        for day in list(self._day_separator_widgets.keys()):
            if day not in seen_days:
                separator = self._day_separator_widgets.pop(day)
                self.feed_layout.removeWidget(separator)
                separator.deleteLater()

        if suppress_autoscroll:
            return has_new_from_others
        if at_bottom or not has_new_from_others:
            QTimer.singleShot(0, self._scroll_to_bottom)
        else:
            self._show_new_messages_button()
        return has_new_from_others

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

    def _cancel_question(self, message_id: int):
        reason, ok = QInputDialog.getMultiLineText(self, "Cancelar pergunta", "Motivo do cancelamento:")
        if not ok or not reason.strip():
            return
        try:
            self.service.chat_cancel_question(message_id, reason.strip())
        except Exception as exc:
            ToastNotification(self.window(), str(exc), "error")
            return
        ToastNotification(self.window(), "Pergunta cancelada.", "success")
        self.refresh()

    def _reassign_question(self, message_id: int):
        if not self._mentionable_users:
            ToastNotification(self.window(), "Nenhum usuario disponivel para reatribuicao.", "error")
            return
        names = [user.get("display_name") or "-" for user in self._mentionable_users]
        name, ok = QInputDialog.getItem(self, "Reatribuir pergunta", "Novo responsavel:", names, 0, False)
        if not ok or not name:
            return
        new_assignee = next((user for user in self._mentionable_users if (user.get("display_name") or "-") == name), None)
        if new_assignee is None:
            return
        reason, ok = QInputDialog.getMultiLineText(self, "Reatribuir pergunta", "Motivo da troca de responsavel:")
        if not ok or not reason.strip():
            return
        try:
            self.service.chat_reassign_question(message_id, new_assignee["id"], reason.strip())
        except Exception as exc:
            ToastNotification(self.window(), str(exc), "error")
            return
        ToastNotification(self.window(), "Pergunta reatribuida.", "success")
        self.refresh()

    def _open_internal_note_dialog(self):
        if not self.conversation_id:
            ToastNotification(self.window(), "Conversa ainda nao carregada, tente novamente.", "error")
            return
        dialog = InternalNoteDialog(self, mentionable_users=self._mentionable_users)
        if dialog.exec() != QDialog.Accepted:
            return
        body, area, recipient_id, is_important = dialog.result_data()
        if not body:
            return
        try:
            self.service.chat_send_message(
                self.conversation_id, body, "NOTA_INTERNA", recipient_id, None, area, None, is_important
            )
        except Exception as exc:
            ToastNotification(self.window(), str(exc), "error")
            return
        ToastNotification(self.window(), "Nota interna registrada.", "success")
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
        reply_to_message_id = self.compose_bar.reply_to_message_id()
        due_at = self.compose_bar.due_at() if message_type == "PERGUNTA" else None
        try:
            self.service.chat_send_message(self.conversation_id, body, message_type, mentioned_user_id, reply_to_message_id, None, due_at)
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

        self.setWindowTitle(self.panel.title())

    @property
    def conversation_id(self):
        return self.panel.conversation_id

    @property
    def entries(self):
        return self.panel.entries

    def refresh(self):
        self.panel.refresh()
