from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.ui.components.modern_button import ModernButton
from app.ui.icons import AppIcons, make_icon


def _pluralize(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular}" if count == 1 else f"{count} {plural}"


class LoginSummaryBanner(QFrame):
    """Resumo consolidado mostrado uma unica vez por sessao, logo apos o
    primeiro carregamento pos-login de GET /chat/unread-summary — nunca um
    QDialog bloqueante, nunca marca nada como lido/resolvido (so apresenta
    numeros que ja existem). Fechar (x ou clicar numa acao) apenas remove
    este widget; o estado real continua nos badges do header, sempre
    atualizados pela mesma fonte (ETAPA 6)."""

    view_messages_requested = Signal()
    view_pending_requested = Signal()

    def __init__(
        self,
        service,
        display_name: str,
        unread_messages: int,
        unread_mentions: int,
        open_action_required: int,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.service = service
        self.setObjectName("Panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._build(display_name, unread_messages, unread_mentions, open_action_required)

    def _build(self, display_name: str, unread_messages: int, unread_mentions: int, open_action_required: int) -> None:
        palette = self.service.palette
        self.setStyleSheet(
            f"QFrame#Panel {{ background: {palette.get('surface', '#ffffff')}; "
            f"border: 1px solid {palette.get('border', '#cbd5e1')}; border-radius: 10px; }}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel(f"Bem-vindo, {display_name}" if display_name else "Bem-vindo")
        title.setStyleSheet("font-size: 14px; font-weight: 800;")
        title.setWordWrap(True)
        header.addWidget(title, 1)
        close_btn = QPushButton("x")
        close_btn.setObjectName("GhostButton")
        close_btn.setFixedSize(20, 20)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setToolTip("Fechar")
        close_btn.clicked.connect(self._dismiss)
        header.addWidget(close_btn)
        outer.addLayout(header)

        subtitle = QLabel("Voce possui itens que precisam da sua atencao.")
        subtitle.setObjectName("Caption")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        rows = QHBoxLayout()
        rows.setSpacing(20)
        if unread_messages > 0:
            rows.addLayout(
                self._indicator(AppIcons.CHAT, palette.get("accent", "#0078d4"), _pluralize(unread_messages, "mensagem nova", "mensagens novas"))
            )
        if unread_mentions > 0:
            rows.addLayout(
                self._indicator(
                    "at", palette.get("secondary", palette.get("accent", "#7c3aed")), _pluralize(unread_mentions, "mencao", "mencoes")
                )
            )
        if open_action_required > 0:
            rows.addLayout(
                self._indicator(
                    AppIcons.WARNING,
                    palette.get("warning", "#d97706"),
                    _pluralize(open_action_required, "pendencia aberta", "pendencias abertas"),
                )
            )
        rows.addStretch()
        outer.addLayout(rows)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch()
        if unread_messages > 0:
            view_messages_btn = ModernButton("Ver mensagens", "chat")
            view_messages_btn.clicked.connect(self._on_view_messages)
            buttons.addWidget(view_messages_btn)
        if open_action_required > 0:
            view_pending_btn = ModernButton("Ver pendencias", "warning")
            view_pending_btn.clicked.connect(self._on_view_pending)
            buttons.addWidget(view_pending_btn)
        outer.addLayout(buttons)

    def _indicator(self, icon, color: str, text: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        icon_label = QLabel()
        icon_label.setPixmap(make_icon(icon, color, 16).pixmap(16, 16))
        row.addWidget(icon_label)
        text_label = QLabel(text)
        text_label.setStyleSheet("font-size: 12px; font-weight: 600;")
        row.addWidget(text_label)
        return row

    def _dismiss(self) -> None:
        # fechar NUNCA muda estado no backend — so tira o resumo da tela
        # desta sessao (os badges do header continuam mostrando os numeros reais).
        self.hide()
        self.deleteLater()

    def _on_view_messages(self) -> None:
        self.view_messages_requested.emit()
        self._dismiss()

    def _on_view_pending(self) -> None:
        self.view_pending_requested.emit()
        self._dismiss()
