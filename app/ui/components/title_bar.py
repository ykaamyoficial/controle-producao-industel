from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from app.ui.animations import fade_in
from app.ui.app_icon import app_icon
from app.ui.components.app_icon_button import AppIconButton
from app.ui.components.notification_bell import NotificationBell
from app.ui.components.user_profile_popover import UserProfilePopover
from app.ui.icons import AppIcons, IconColorRole, icon_motion
from app.version import APP_NAME


TOP_BAR_HEIGHT = 40
ACTION_BUTTON_SIZE = 34
ACTION_ICON_SIZE = 18
WINDOW_BUTTON_WIDTH = 46
WINDOW_BUTTON_HEIGHT = 40
WINDOW_ICON_SIZE = 15
ELEMENT_SPACING = 4


class TitleBar(QFrame):
    """Barra superior personalizada: nome do sistema a esquerda, atalhos
    funcionais (Chat/Notificacoes/Tema/Configuracoes/Usuario) e controles
    da janela a direita. Arraste e redimensionamento da janela sem moldura
    sao tratados nativamente por
    app.ui.components.native_frameless.FramelessHitTestMixin via
    WM_NCHITTEST na janela dona desta barra; este widget so precisa manter
    o registro de quais filhos sao interativos, pra serem excluidos da
    area de arraste/caption.
    """

    chat_requested = Signal()
    theme_toggle_requested = Signal()
    settings_requested = Signal()

    def __init__(self, service, parent=None, on_open_conversation=None):
        super().__init__(parent)
        self.service = service
        self._on_open_conversation = on_open_conversation
        self.setObjectName("TitleBar")
        self.setFixedHeight(TOP_BAR_HEIGHT)
        self._interactive_widgets: list[QWidget] = []
        self._profile_popup: UserProfilePopover | None = None
        self.logout_callback = None
        self.profile_callback = None
        self.password_callback = None
        self._last_chat_unread = 0
        self._build()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(ELEMENT_SPACING)

        icon_label = QLabel()
        icon_label.setPixmap(app_icon().pixmap(18, 18))
        layout.addWidget(icon_label)

        title_label = QLabel(APP_NAME)
        title_label.setObjectName("TitleBarAppName")
        layout.addWidget(title_label)

        layout.addStretch(1)

        self.chat_btn = self._create_action_button(AppIcons.CHAT, "Abrir chat")
        self.chat_btn.setAccessibleName("Chat")
        self.chat_btn.clicked.connect(self.chat_requested.emit)
        layout.addWidget(self.chat_btn)

        self.notification_bell = NotificationBell(self.service, on_open_conversation=self._on_open_conversation)
        self.notification_bell.setFixedSize(ACTION_BUTTON_SIZE, ACTION_BUTTON_SIZE)
        self.notification_bell.setAccessibleName("Notificacoes")
        self._register_interactive(self.notification_bell)
        layout.addWidget(self.notification_bell)

        self.pending_btn = self._create_action_button(AppIcons.WARNING, "Pendencias")
        self.pending_btn.setAccessibleName("Pendencias")
        layout.addWidget(self.pending_btn)

        self.theme_btn = self._create_action_button(AppIcons.MOON, "Alternar tema")
        self.theme_btn.setAccessibleName("Alternar tema")
        self.theme_btn.clicked.connect(self.theme_toggle_requested.emit)
        layout.addWidget(self.theme_btn)

        self.settings_btn = self._create_action_button(AppIcons.SETTINGS, "Abrir configuracoes")
        self.settings_btn.setAccessibleName("Configuracoes")
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        layout.addWidget(self.settings_btn)

        self.profile_btn = self._create_action_button(AppIcons.USERS, "Menu do usuario")
        self.profile_btn.setAccessibleName("Usuario")
        self.profile_btn.clicked.connect(self._toggle_profile_popover)
        self.refresh_profile_avatar()
        layout.addWidget(self.profile_btn)

        separator = QFrame()
        separator.setFrameShape(QFrame.VLine)
        separator.setFixedHeight(20)
        layout.addSpacing(ELEMENT_SPACING)
        layout.addWidget(separator)
        layout.addSpacing(ELEMENT_SPACING)

        self.minimize_btn = self._create_window_button(AppIcons.MINIMIZE, "Minimizar")
        self.minimize_btn.clicked.connect(self._minimize)
        layout.addWidget(self.minimize_btn)

        self.maximize_btn = self._create_window_button(AppIcons.MAXIMIZE, "Maximizar")
        self.maximize_btn.clicked.connect(self._toggle_maximize)
        layout.addWidget(self.maximize_btn)

        self.close_btn = self._create_window_button(AppIcons.WINDOW_CLOSE, "Fechar", close=True)
        self.close_btn.clicked.connect(self._close)
        layout.addWidget(self.close_btn)

    def _create_action_button(self, icon: AppIcons, tooltip: str) -> AppIconButton:
        button = AppIconButton(
            icon,
            palette=self.service.palette,
            color_role=IconColorRole.PRIMARY,
            size=ACTION_ICON_SIZE,
            tooltip=tooltip,
        )
        button.setFixedSize(ACTION_BUTTON_SIZE, ACTION_BUTTON_SIZE)
        self._register_interactive(button)
        return button

    def _create_window_button(self, icon: AppIcons, tooltip: str, close: bool = False) -> AppIconButton:
        button = AppIconButton(
            icon,
            color=self.service.palette.get("text", "#1e293b"),
            size=WINDOW_ICON_SIZE,
            tooltip=tooltip,
        )
        button.setObjectName("TitleBarCloseButton" if close else "TitleBarButton")
        button.setFixedSize(WINDOW_BUTTON_WIDTH, WINDOW_BUTTON_HEIGHT)
        button.setCursor(Qt.ArrowCursor)
        self._register_interactive(button)
        return button

    def _register_interactive(self, widget: QWidget):
        self._interactive_widgets.append(widget)

    def is_over_interactive_widget(self, local_point) -> bool:
        for widget in self._interactive_widgets:
            if not widget.isVisible():
                continue
            if widget.geometry().contains(local_point):
                return True
        return False

    def set_chat_unread_count(self, count: int):
        if count > self._last_chat_unread:
            icon_motion.pulse(self.chat_btn)
        self._last_chat_unread = count
        self.chat_btn.set_badge_count(count)
        if count == 1:
            description = "1 mensagem nao lida"
        elif count > 1:
            description = f"{count} mensagens nao lidas"
        else:
            description = "Abrir chat"
        self.chat_btn.setToolTip(description)
        self.chat_btn.setAccessibleName(f"Chat, {description}" if count else "Chat")
        self.chat_btn.setAccessibleDescription(description)

    def set_pending_count(self, count: int):
        """Pendencias abertas (ActionRequired) — conceito separado do sino:
        uma Notification pode virar READ so por visualizar a mensagem, mas a
        pendencia continua aberta ate ser resolvida/cancelada. Nunca somar
        este numero ao badge do sino."""
        self.pending_btn.set_badge_count(count)
        if count == 1:
            description = "1 pendencia aberta"
        elif count > 1:
            description = f"{count} pendencias abertas"
        else:
            description = "Pendencias"
        self.pending_btn.setToolTip(description)
        self.pending_btn.setAccessibleName(description)
        self.pending_btn.setAccessibleDescription(description)

    def apply_palette(self, palette: dict):
        """Re-renderiza os icones dos botoes fixos com a paleta nova - o
        cache de icones ja foi invalidado pelo chamador (main_window) antes
        disso, entao a proxima renderizacao pega a cor certa."""
        text_color = palette.get("text", "#1e293b")
        for button in (self.chat_btn, self.pending_btn, self.theme_btn, self.settings_btn, self.profile_btn):
            button.set_palette(palette)
        self.refresh_profile_avatar()
        self.notification_bell.set_palette(palette)
        for button in (self.minimize_btn, self.maximize_btn, self.close_btn):
            button.set_color_override(text_color)

    def set_theme_icon(self, dark_mode: bool):
        icon = AppIcons.SUN if dark_mode else AppIcons.MOON
        self.theme_btn.set_palette(self.service.palette)
        self.theme_btn.set_icon_semantic(icon)
        self.theme_btn.setToolTip("Usar tema claro" if dark_mode else "Usar tema escuro")

    def refresh_profile_avatar(self):
        """Substitui o icone do perfil pela foto circular do usuario atual."""
        if not hasattr(self, "profile_btn"):
            return
        user = self.service.user or {}
        content = None
        if user.get("id") and hasattr(self.service, "avatar_bytes_for_user"):
            try:
                content = self.service.avatar_bytes_for_user(int(user["id"]))
            except Exception:
                content = None
        if not content:
            self.profile_btn.set_icon_semantic(AppIcons.USERS)
            self.profile_btn.setIconSize(QSize(ACTION_ICON_SIZE, ACTION_ICON_SIZE))
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(content):
            self.profile_btn.set_icon_semantic(AppIcons.USERS)
            return
        size = 22
        source = pixmap.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        circular = QPixmap(size, size)
        circular.fill(Qt.transparent)
        painter = QPainter(circular)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addEllipse(0, 0, size, size)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, source)
        painter.end()
        self.profile_btn.setIcon(QIcon(circular))
        self.profile_btn.setIconSize(QSize(size, size))

    def set_maximized(self, maximized: bool):
        icon = AppIcons.WINDOW_RESTORE if maximized else AppIcons.MAXIMIZE
        self.maximize_btn.set_icon_semantic(icon)
        self.maximize_btn.setToolTip("Restaurar" if maximized else "Maximizar")

    def _minimize(self):
        self.window().showMinimized()

    def _toggle_maximize(self):
        window = self.window()
        if window.isMaximized():
            window.showNormal()
        else:
            window.showMaximized()

    def _close(self):
        self.window().close()

    def _toggle_profile_popover(self):
        if self._profile_popup is not None and self._profile_popup.isVisible():
            self._profile_popup.close()
            return
        popup = UserProfilePopover(self.service, parent=self)
        popup.logout_requested.connect(self._on_logout_requested)
        popup.profile_requested.connect(self._on_profile_requested)
        popup.password_requested.connect(self._on_password_requested)
        point = self.profile_btn.mapToGlobal(self.profile_btn.rect().bottomRight())
        point.setX(point.x() - popup.width())
        popup.move(point)
        popup.show()
        self._profile_popup = popup
        fade_in(popup, duration=140)

    def _on_logout_requested(self):
        if self.logout_callback is not None:
            self.logout_callback()

    def _on_profile_requested(self):
        if self.profile_callback is not None:
            self.profile_callback(False)

    def _on_password_requested(self):
        if self.password_callback is not None:
            self.password_callback(True)
