from __future__ import annotations

import html
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from app.ui.components.avatar import make_avatar_label
from app.ui.components.chat_message_attachments import ChatAttachmentsView
from app.ui.components.modern_button import ModernButton
from app.ui.icons import AppIcons, icon_provider, make_icon


GROUP_WINDOW_SECONDS = 300


def highlight_mentions(text: str, mentionable_names: list[str], accent_color: str) -> str:
    escaped = html.escape(text).replace("\n", "<br>")
    for name in sorted(mentionable_names, key=len, reverse=True):
        token = f"@{html.escape(name)}"
        if token in escaped:
            escaped = escaped.replace(token, f'<span style="color:{accent_color}; font-weight:700;">{token}</span>')
    return escaped


def _use_grayscale_antialiasing(label: QLabel) -> None:
    """Texto claro sobre fundo saturado (bolha propria, azul) sai borrado
    no ClearType do Windows - o subpixel rendering foi calibrado pra texto
    escuro sobre fundo claro, o caso oposto (claro sobre escuro) sofre de
    franjas de cor que o olho le como desfoque. Forcar antialiasing em
    escala de cinza (que ignora a cor de fundo) resolve sem custo visivel
    nas bolhas normais (escuro sobre claro), que ja ficam nitidas."""
    font = label.font()
    font.setStyleStrategy(QFont.PreferAntialias)
    label.setFont(font)


def _make_label_background_transparent(label: QLabel) -> None:
    label.setAttribute(Qt.WA_TranslucentBackground, True)
    label.setAutoFillBackground(False)


def _format_clock(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return ""
    return parsed.strftime("%H:%M")


def _format_day_and_clock(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return ""
    return parsed.strftime("%d/%m/%Y %H:%M")


# --- widgets da timeline ------------------------------------------------
# Eventos operacionais (producao/galvanizacao/expedicao/fiscal) nao chegam
# mais aqui — o backend so retorna comunicacao humana no timeline do chat
# (ver api/app/modules/chat/service.py::get_proposal_timeline). Atividade
# operacional vive em ProposalActivityPanel, alimentada por
# GET /proposals/{id}/activities (frases ja prontas, sem metadata bruta).


class TimelineDaySeparator(QWidget):
    def __init__(self, day_label: str, service, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        palette = service.palette
        self._label = QLabel(day_label)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet(
            f"background: {palette.get('surface_alt', '#e2e8f0')}; "
            f"color: {palette.get('muted', '#64748b')}; "
            "border-radius: 10px; padding: 2px 14px; font-weight: 700; font-size: 11px;"
        )
        layout.addStretch()
        layout.addWidget(self._label)
        layout.addStretch()

    def update_text(self, day_label: str) -> None:
        if self._label.text() != day_label:
            self._label.setText(day_label)


class MessageFooter(QWidget):
    def __init__(self, entry: dict, text_color: str, *, show_status: bool = True, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        time_label = QLabel(_format_clock(entry.get("created_at")))
        _make_label_background_transparent(time_label)
        time_label.setStyleSheet(f"font-size: 9px; color: {text_color}; background: transparent;")
        _use_grayscale_antialiasing(time_label)
        layout.addWidget(time_label)

        if show_status:
            seen_by = int(entry.get("seen_by_count") or 0)
            if seen_by <= 0:
                icon, tooltip = AppIcons.CHECK, "Entregue"
            elif seen_by == 1:
                icon, tooltip = AppIcons.CHECK_DOUBLE, "Lida"
            else:
                icon, tooltip = AppIcons.CHECK_DOUBLE, f"Visualizada por {seen_by} usuarios"
            mark_label = QLabel()
            _make_label_background_transparent(mark_label)
            mark_icon = icon_provider.get_icon(icon, 12, text_color)
            if mark_icon is not None:
                mark_label.setPixmap(mark_icon.pixmap(12, 12))
            mark_label.setToolTip(tooltip)
            layout.addWidget(mark_label)


MessageStatusIndicator = MessageFooter


def entry_fingerprint(entry: dict, grouped: bool) -> tuple:
    """Assinatura dos campos mutaveis de um entry (status da pergunta,
    contagem de leitura, corpo, agrupamento). Calculada a partir do dict
    recebido no momento da chamada — nunca lida de volta de um widget ja
    construido — para nao dar falso-negativo caso o dict do entry seja
    mutado in-place em vez de substituido por um novo a cada refresh."""
    attachment_sig = tuple(
        (
            item.get("id"),
            item.get("original_filename") or item.get("filename"),
            item.get("size"),
            item.get("sha256") or item.get("sha256_hex"),
            item.get("deleted_at"),
            item.get("purged_at"),
        )
        for item in entry.get("attachments") or []
        if isinstance(item, dict)
    )
    return (entry.get("question_status"), entry.get("seen_by_count"), entry.get("body"), grouped, attachment_sig)


class TimelineEntryWidget(QFrame):
    """Base comum: guarda o entry/contexto e define o contrato de
    atualizacao incremental (update_entry) usado por ChatConversationPanel
    pra nao ter que destruir/recriar o widget a cada refresh quando so um
    campo mutavel (status da pergunta, contagem de leitura) mudou."""

    reply_requested = Signal(int)
    attachment_download_requested = Signal(dict)
    attachment_open_requested = Signal(dict)
    attachment_preview_requested = Signal(dict)
    attachment_delete_requested = Signal(dict)
    supports_reply = False

    def __init__(self, entry: dict, service, current_user_id, mentionable_names: list[str], grouped: bool = False, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.service = service
        self.current_user_id = current_user_id
        self.mentionable_names = mentionable_names
        self.grouped = grouped
        self._fingerprint = entry_fingerprint(entry, grouped)
        self._build()

    def _build(self):
        raise NotImplementedError

    def update_entry(self, entry: dict, grouped: bool = False) -> None:
        self.entry = entry
        self.grouped = grouped
        self._fingerprint = entry_fingerprint(entry, grouped)

    def set_max_bubble_width(self, width: int) -> None:
        self.setMaximumWidth(max(160, width))

    def contextMenuEvent(self, event):
        if not self.supports_reply:
            return
        menu = QMenu(self)
        reply_action = menu.addAction("Responder")
        chosen = menu.exec(event.globalPos())
        if chosen is reply_action:
            self.reply_requested.emit(self.entry.get("id"))

    def _add_attachments(self, layout: QVBoxLayout, *, compact: bool = False) -> None:
        attachments = self.entry.get("attachments") or []
        if not attachments:
            return
        view = ChatAttachmentsView(attachments, self.service.palette, compact=compact, can_delete=self._can_delete_attachment, service=self.service)
        view.download_requested.connect(self.attachment_download_requested)
        view.open_requested.connect(self.attachment_open_requested)
        view.preview_requested.connect(self.attachment_preview_requested)
        view.delete_requested.connect(self.attachment_delete_requested)
        layout.addWidget(view)
        self._attachments_view = view

    def stop_media(self) -> None:
        """Pausa/libera qualquer video ou audio tocando nesta mensagem."""
        view = getattr(self, "_attachments_view", None)
        if view is not None:
            try:
                view.stop_media()
            except RuntimeError:
                pass

    def _can_delete_attachment(self, attachment: dict) -> bool:
        if attachment.get("deleted_at"):
            return False
        if hasattr(self.service, "can_admin_chat") and self.service.can_admin_chat():
            return True
        actor_id = self.current_user_id
        if actor_id is None:
            return False
        return attachment.get("uploaded_by") == actor_id or self.entry.get("author_user_id") == actor_id


class MessageBubble(TimelineEntryWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A bolha deve se moldar ao conteudo (mensagem curta -> bolha curta),
        # nao esticar ate a largura maxima so porque ha espaco disponivel no
        # feed. Maximum = nunca cresce alem do sizeHint; set_max_bubble_width
        # (via setMaximumWidth) continua limitando o teto para textos longos.
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

    def _message_body(self) -> str:
        body = self.entry.get("body") or ""
        if body == "[Anexo]" and self.entry.get("attachments"):
            return ""
        return body

    def _add_body_label(self, layout: QVBoxLayout, body: str, *, color: str, mention_color: str) -> QLabel:
        body_label = QLabel()
        body_label.setTextFormat(Qt.RichText)
        body_label.setText(highlight_mentions(body, self.mentionable_names, mention_color) if body else "-")
        body_label.setWordWrap(True)
        _make_label_background_transparent(body_label)
        body_label.setStyleSheet(f"font-size: 12px; color: {color}; background: transparent;")
        _use_grayscale_antialiasing(body_label)
        layout.addWidget(body_label)
        return body_label

    def _add_footer(self, layout: QVBoxLayout, *, color: str, align_right: bool, show_status: bool) -> MessageFooter:
        footer_layout = QHBoxLayout()
        if align_right:
            footer_layout.addStretch()
        footer = MessageFooter(self.entry, color, show_status=show_status)
        footer_layout.addWidget(footer)
        if not align_right:
            footer_layout.addStretch()
        layout.addLayout(footer_layout)
        return footer


class CurrentUserMessageWidget(MessageBubble):
    supports_reply = True

    def _build(self):
        palette = self.service.palette
        accent = palette.get("accent", "#0078d4")
        text_color = palette.get("accent_text", "#ffffff")
        self.setObjectName("BubbleOwn")
        self.setStyleSheet(f"QFrame#BubbleOwn {{ background: {accent}; border-radius: 12px; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 4)
        layout.setSpacing(2)

        body = self._message_body()
        has_attachments = bool(self.entry.get("attachments"))
        self._add_attachments(layout, compact=True)
        if body or not has_attachments:
            self._add_body_label(layout, body, color=text_color, mention_color="#ffffff")

        self._status_indicator = self._add_footer(layout, color=text_color, align_right=True, show_status=True)

    def update_entry(self, entry, grouped=False):
        super().update_entry(entry, grouped)
        text_color = self.service.palette.get("accent_text", "#ffffff")
        old = self._status_indicator
        self._status_indicator = MessageFooter(entry, text_color, show_status=True)
        if old.parentWidget() and old.parentWidget().layout():
            old.parentWidget().layout().replaceWidget(old, self._status_indicator)
        old.deleteLater()


class OtherUserMessageWidget(MessageBubble):
    supports_reply = True

    def _build(self):
        palette = self.service.palette
        # O avatar fica FORA da bolha (igual grupo do WhatsApp) -- so o
        # conteudo (nome/midia/rodape) ganha fundo/borda arredondada; `self`
        # e so um container transparente que posiciona avatar + bolha lado a lado.
        self.setStyleSheet("background: transparent; border: none;")
        mentions_me = self.current_user_id is not None and self.entry.get("mentioned_user_id") == self.current_user_id
        border = f"1px solid {palette.get('border', '#cbd5e1')}"
        if mentions_me:
            accent = palette.get("accent", "#0078d4")
            border = f"{border}; border-left: 3px solid {accent}"

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        avatar_col = QVBoxLayout()
        if not self.grouped:
            avatar_col.addWidget(make_avatar_label(self.entry.get("author_name"), self.service, 26, self.entry.get("author_user_id")))
        avatar_col.addStretch()
        outer.addLayout(avatar_col)

        bubble = QFrame()
        bubble.setObjectName("BubbleOther")
        bubble.setStyleSheet(
            f"QFrame#BubbleOther {{ background: {palette.get('surface_alt', '#e2e8f0')}; "
            f"border: {border}; border-radius: 12px; }}"
        )
        if mentions_me:
            bubble.setToolTip("Voce foi mencionado nesta mensagem")
        outer.addWidget(bubble, 1)

        content_col = QVBoxLayout(bubble)
        content_col.setContentsMargins(10, 3 if self.grouped else 8, 10, 5)
        content_col.setSpacing(2)
        if not self.grouped:
            header = QHBoxLayout()
            header.setSpacing(6)
            name_label = QLabel(self.entry.get("author_name") or "-")
            _make_label_background_transparent(name_label)
            name_label.setStyleSheet("font-weight: 700; font-size: 11px; background: transparent;")
            header.addWidget(name_label)
            sector = self.entry.get("author_sector")
            if sector:
                sector_label = QLabel(sector)
                sector_label.setObjectName("Caption")
                _make_label_background_transparent(sector_label)
                sector_label.setStyleSheet("font-size: 10px; background: transparent;")
                header.addWidget(sector_label)
            header.addStretch()
            content_col.addLayout(header)

        body = self._message_body()
        if body:
            self._add_body_label(content_col, body, color=palette.get("text", "#0f172a"), mention_color=palette.get("accent", "#0078d4"))
        self._add_attachments(content_col, compact=True)
        self._footer = self._add_footer(content_col, color=palette.get("muted", "#94a3b8"), align_right=False, show_status=False)


class InternalNoteWidget(TimelineEntryWidget):
    """Nota interna manual (message_type=NOTA_INTERNA): visualmente distinta
    de uma mensagem comum — nunca alinhada como bolha de conversa, sempre com
    rotulo "NOTA INTERNA" e a area de origem em destaque, pra ninguem confundir
    com comunicacao entre pessoas."""

    def _build(self):
        palette = self.service.palette
        accent = palette.get("warning", "#d97706")
        self.setObjectName("InternalNoteCard")
        self.setStyleSheet(
            f"QFrame#InternalNoteCard {{ background: {palette.get('surface', '#ffffff')}; "
            f"border: 1px dashed {accent}; border-left: 4px solid {accent}; border-radius: 8px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(3)

        header = QHBoxLayout()
        header.setSpacing(6)
        icon_label = QLabel()
        icon_label.setPixmap(make_icon("doc", accent, 14).pixmap(14, 14))
        header.addWidget(icon_label)
        area = self.entry.get("area")
        area_label = str(area).replace("_", " ").title() if area else None
        title_text = f"NOTA INTERNA · {area_label.upper()}" if area_label else "NOTA INTERNA"
        title_label = QLabel(title_text)
        title_label.setStyleSheet(f"font-weight: 800; font-size: 11px; letter-spacing: 0.4px; color: {accent};")
        header.addWidget(title_label)
        header.addStretch()
        if self.entry.get("is_important"):
            important_badge = QLabel("IMPORTANTE")
            important_badge.setStyleSheet(
                f"background: {accent}22; color: {accent}; border-radius: 8px; padding: 1px 8px; "
                "font-size: 9px; font-weight: 800;"
            )
            header.addWidget(important_badge)
        layout.addLayout(header)

        if self.entry.get("mentioned_user_name"):
            recipient_label = QLabel(f"Para: {self.entry.get('mentioned_user_name')}")
            recipient_label.setObjectName("Caption")
            recipient_label.setStyleSheet("font-size: 10px;")
            layout.addWidget(recipient_label)

        body_label = QLabel(html.escape(self.entry.get("body") or "-"))
        body_label.setWordWrap(True)
        body_label.setStyleSheet("font-size: 12px;")
        layout.addWidget(body_label)
        self._add_attachments(layout)

        author = self.entry.get("author_name")
        footer_text = f"Registrado por {author}" if author else "Registrado"
        clock = _format_clock(self.entry.get("created_at"))
        if clock:
            footer_text = f"{footer_text} · {clock}"
        footer_label = QLabel(footer_text)
        footer_label.setObjectName("Caption")
        footer_label.setStyleSheet("font-size: 10px;")
        layout.addWidget(footer_label)


_QUESTION_STATUS_LABELS = {
    "AGUARDANDO_RESPOSTA": "Aguardando resposta",
    "RESPONDIDA": "Respondida",
    "ATRASADA": "Atrasada",
    "CANCELADA": "Cancelada",
}


class DirectedQuestionWidget(TimelineEntryWidget):
    """Card de "Resposta solicitada" — nunca uma bolha comum. O status
    exibido (self.entry["question_status"]) ja vem calculado pelo backend
    (_effective_question_status): pode ser ATRASADA sem que isso esteja
    gravado, entao esse widget nunca precisa saber calcular atraso sozinho."""

    answer_requested = Signal(int)
    cancel_requested = Signal(int)
    reassign_requested = Signal(int)

    def _build(self):
        palette = self.service.palette
        accent = palette.get("secondary", palette.get("accent", "#7c3aed"))
        self.setObjectName("QuestionCard")
        self.setStyleSheet(
            f"QFrame#QuestionCard {{ background: {palette.get('surface', '#ffffff')}; "
            f"border: 1px solid {accent}; border-left: 4px solid {accent}; border-radius: 8px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(3)

        header = QHBoxLayout()
        header.setSpacing(6)
        icon_label = QLabel()
        icon_label.setPixmap(make_icon("question", accent, 14).pixmap(14, 14))
        header.addWidget(icon_label)
        title_label = QLabel("RESPOSTA SOLICITADA")
        title_label.setStyleSheet(f"font-weight: 800; font-size: 11px; letter-spacing: 0.4px; color: {accent};")
        header.addWidget(title_label)
        header.addStretch()
        time_label = QLabel(_format_clock(self.entry.get("created_at")))
        time_label.setStyleSheet(f"font-size: 9px; color: {palette.get('muted', '#94a3b8')};")
        header.addWidget(time_label)
        self._menu_btn = QToolButton()
        self._menu_btn.setObjectName("GhostButton")
        self._menu_btn.setText("⋮")
        self._menu_btn.setFixedSize(20, 20)
        self._menu_btn.setPopupMode(QToolButton.InstantPopup)
        self._menu = QMenu(self._menu_btn)
        self._cancel_action = self._menu.addAction("Cancelar pergunta")
        self._cancel_action.triggered.connect(lambda: self.cancel_requested.emit(self.entry.get("id")))
        self._reassign_action = self._menu.addAction("Reatribuir responsavel")
        self._reassign_action.triggered.connect(lambda: self.reassign_requested.emit(self.entry.get("id")))
        self._menu_btn.setMenu(self._menu)
        header.addWidget(self._menu_btn)
        layout.addLayout(header)

        author = self.entry.get("author_name") or "-"
        mentioned = self.entry.get("mentioned_user_name") or "-"
        who_label = QLabel(f"{author} perguntou · Responsavel: {mentioned}")
        who_label.setObjectName("Caption")
        who_label.setStyleSheet("font-size: 10px;")
        who_label.setWordWrap(True)
        layout.addWidget(who_label)

        body_label = QLabel()
        body_label.setTextFormat(Qt.RichText)
        body_label.setText(highlight_mentions(self.entry.get("body") or "-", self.mentionable_names, accent))
        body_label.setWordWrap(True)
        body_label.setStyleSheet("font-size: 12px;")
        layout.addWidget(body_label)
        self._add_attachments(layout)

        self._due_label = QLabel()
        self._due_label.setObjectName("Caption")
        self._due_label.setStyleSheet("font-size: 10px;")
        layout.addWidget(self._due_label)

        self._viewed_label = QLabel()
        self._viewed_label.setObjectName("Caption")
        self._viewed_label.setStyleSheet("font-size: 10px;")
        layout.addWidget(self._viewed_label)

        self._cancellation_label = QLabel()
        self._cancellation_label.setWordWrap(True)
        self._cancellation_label.setStyleSheet("font-size: 10px; font-style: italic;")
        layout.addWidget(self._cancellation_label)

        badge_row = QHBoxLayout()
        self._badge_label = QLabel()
        badge_row.addWidget(self._badge_label)
        badge_row.addStretch()
        self._answer_btn = ModernButton("Responder", "status")
        message_id = self.entry.get("id")
        self._answer_btn.clicked.connect(lambda _checked=False: self.answer_requested.emit(message_id))
        badge_row.addWidget(self._answer_btn)
        layout.addLayout(badge_row)
        self._apply_status()

    def _apply_status(self):
        palette = self.service.palette
        status = self.entry.get("question_status")
        colors = {
            "RESPONDIDA": palette.get("success", "#16a34a"),
            "ATRASADA": palette.get("danger", "#dc2626"),
            "CANCELADA": palette.get("muted", "#94a3b8"),
        }
        color = colors.get(status, palette.get("warning", "#d97706"))
        self._badge_label.setText(_QUESTION_STATUS_LABELS.get(status, status or "-"))
        self._badge_label.setStyleSheet(
            f"background: {color}22; color: {color}; border-radius: 8px; padding: 1px 8px; "
            "font-size: 10px; font-weight: 700;"
        )

        due_at = self.entry.get("due_at")
        self._due_label.setText(f"Prazo: {_format_day_and_clock(due_at)}" if due_at else "")
        self._due_label.setVisible(bool(due_at))

        viewed_at = self.entry.get("viewed_at")
        self._viewed_label.setText(f"Visualizada pelo responsavel em {_format_day_and_clock(viewed_at)}" if viewed_at else "")
        self._viewed_label.setVisible(bool(viewed_at))

        cancellation_reason = self.entry.get("cancellation_reason")
        self._cancellation_label.setText(f"Motivo do cancelamento: {cancellation_reason}" if status == "CANCELADA" and cancellation_reason else "")
        self._cancellation_label.setVisible(bool(status == "CANCELADA" and cancellation_reason))

        open_state = status in ("AGUARDANDO_RESPOSTA", "ATRASADA")
        can_answer = open_state and self.entry.get("mentioned_user_id") == self.current_user_id
        self._answer_btn.setVisible(can_answer)

        is_author = self.entry.get("author_user_id") == self.current_user_id
        is_admin = bool(self.service.can_admin_chat()) if hasattr(self.service, "can_admin_chat") else False
        self._cancel_action.setVisible(open_state and (is_author or is_admin))
        self._reassign_action.setVisible(open_state and is_admin)
        self._menu_btn.setVisible(open_state and (is_author or is_admin))

    def update_entry(self, entry, grouped=False):
        super().update_entry(entry, grouped)
        self._apply_status()


class ReplyMessageWidget(TimelineEntryWidget):
    """Mensagem que responde/cita outra (answered_message_id) — mostra uma
    previa clicavel da mensagem original, estilo WhatsApp, acima do texto da
    resposta. Usada tanto para resposta formal a uma Pergunta quanto para
    citacao livre de qualquer mensagem no chat. A mensagem original vem
    embutida em entry["_reply_original"] (resolvida pelo painel a partir das
    entradas ja carregadas — None se ainda nao estiver na pagina atual)."""

    jump_to_message_requested = Signal(int)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

    def _build(self):
        palette = self.service.palette
        accent = palette.get("accent", "#0078d4")
        original = self.entry.get("_reply_original")
        original_id = self.entry.get("answered_message_id")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 2, 0, 2)
        outer.setSpacing(8)

        connector = QFrame()
        connector.setFixedWidth(2)
        connector.setStyleSheet(f"background: {accent};")
        outer.addWidget(connector)

        card = QFrame()
        card.setObjectName("AnswerCard")
        card.setStyleSheet(
            f"QFrame#AnswerCard {{ background: {palette.get('surface', '#ffffff')}; "
            f"border: 1px solid {palette.get('border', '#cbd5e1')}; border-radius: 8px; }}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 6, 10, 6)
        card_layout.setSpacing(4)

        quote = QFrame()
        quote.setObjectName("QuotePreview")
        quote.setStyleSheet(
            f"QFrame#QuotePreview {{ background: {palette.get('surface_alt', '#e2e8f0')}; "
            f"border-left: 3px solid {accent}; border-radius: 4px; }}"
        )
        quote_layout = QVBoxLayout(quote)
        quote_layout.setContentsMargins(8, 4, 8, 4)
        quote_layout.setSpacing(0)
        if original is not None:
            quote_author = QLabel(original.get("author_name") or "-")
            _make_label_background_transparent(quote_author)
            quote_author.setStyleSheet(f"font-weight: 700; font-size: 10px; color: {accent}; background: transparent;")
            quote_layout.addWidget(quote_author)
            snippet = (original.get("body") or "").strip().replace("\n", " ")
            if len(snippet) > 120:
                snippet = snippet[:117] + "..."
            quote_body = QLabel(html.escape(snippet or "-"))
            quote_body.setWordWrap(True)
            _make_label_background_transparent(quote_body)
            quote_body.setStyleSheet("font-size: 11px; background: transparent;")
            quote_layout.addWidget(quote_body)
            quote.setCursor(Qt.PointingHandCursor)
            quote.mousePressEvent = lambda _event, mid=original_id: self.jump_to_message_requested.emit(mid)
        else:
            unavailable = QLabel("Mensagem original indisponivel.")
            unavailable.setObjectName("Caption")
            _make_label_background_transparent(unavailable)
            unavailable.setStyleSheet("font-size: 11px; font-style: italic; background: transparent;")
            quote_layout.addWidget(unavailable)
        card_layout.addWidget(quote)

        header = QHBoxLayout()
        header.setSpacing(6)
        author = self.entry.get("author_name") or "-"
        name_label = QLabel(author)
        _make_label_background_transparent(name_label)
        name_label.setStyleSheet("font-weight: 700; font-size: 11px; background: transparent;")
        header.addWidget(name_label)
        header.addStretch()
        time_label = QLabel(_format_clock(self.entry.get("created_at")))
        _make_label_background_transparent(time_label)
        time_label.setStyleSheet(f"font-size: 9px; color: {palette.get('muted', '#94a3b8')}; background: transparent;")
        header.addWidget(time_label)
        card_layout.addLayout(header)

        body_label = QLabel()
        body_label.setTextFormat(Qt.RichText)
        body_label.setText(highlight_mentions(self.entry.get("body") or "-", self.mentionable_names, accent))
        body_label.setWordWrap(True)
        _make_label_background_transparent(body_label)
        body_label.setStyleSheet("font-size: 12px; background: transparent;")
        card_layout.addWidget(body_label)
        self._add_attachments(card_layout)

        if original is not None and original.get("entry_kind") == "PERGUNTA":
            success = palette.get("success", "#16a34a")
            badge = QLabel("Resposta a pergunta")
            badge.setStyleSheet(
                f"background: {success}22; color: {success}; border-radius: 8px; padding: 1px 8px; "
                "font-size: 10px; font-weight: 700;"
            )
            badge_row = QHBoxLayout()
            badge_row.addWidget(badge)
            badge_row.addStretch()
            card_layout.addLayout(badge_row)

        outer.addWidget(card, 1)
