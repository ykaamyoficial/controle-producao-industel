from __future__ import annotations

from app.ui.animations import fade_in
from app.ui.components.app_icon_button import AppIconButton
from app.ui.components.notification_center_panel import NotificationCenterPanel
from app.ui.icons import AppIcons, IconColorRole, icon_motion


class NotificationBell(AppIconButton):
    """Abre a Central de Notificacoes — so o que exige atencao (mencao,
    resposta, pergunta atribuida/atrasada, nota interna direcionada ou
    importante). Contador e independente do icone de conversa (mensagens
    nao lidas), atualizado por main_window a partir do polling existente.
    Balanca (shake) uma vez quando a contagem de nao lidas sobe - nunca em
    todo poll, so quando ha novidade de verdade (PDF secao 10.1)."""

    def __init__(self, service, parent=None, on_open_conversation=None):
        super().__init__(
            AppIcons.BELL,
            palette=service.palette,
            color_role=IconColorRole.PRIMARY,
            size=20,
            parent=parent,
        )
        self.service = service
        self._on_open_conversation = on_open_conversation
        self.setMinimumHeight(34)
        self._panel: NotificationCenterPanel | None = None
        self._last_count = 0
        self.set_unread_count(0)
        self.clicked.connect(self.toggle_center)

    def set_unread_count(self, count: int):
        if count > self._last_count:
            icon_motion.shake(self)
        self._last_count = count
        self.set_badge_count(count)
        if count == 1:
            tooltip = "Notificacoes — 1 nao lida"
            accessible = "Notificacoes, 1 nao lida"
        elif count > 1:
            tooltip = f"Notificacoes — {count} nao lidas"
            accessible = f"Notificacoes, {count} nao lidas"
        else:
            tooltip = "Notificacoes"
            accessible = "Notificacoes"
        self.setToolTip(tooltip)
        self.setAccessibleName(accessible)
        self.setAccessibleDescription(tooltip)

    def toggle_center(self):
        # ETAPA 10: segundo clique no sino fecha a Central, mesmo padrao de
        # TitleBar._toggle_profile_popover — nao e um QDialog modal, entao
        # o proprio Qt.Popup ja cuida de fechar em clique fora/ESC.
        if self._panel is not None and self._panel.isVisible():
            self._panel.close()
            return
        panel = NotificationCenterPanel(self.service, parent=self.window(), on_open_conversation=self._on_open_conversation)
        point = self.mapToGlobal(self.rect().bottomRight())
        point.setX(point.x() - panel.width())
        panel.move(point)
        panel.show()
        self._panel = panel
        fade_in(panel, duration=140)

    def is_center_open(self) -> bool:
        return self._panel is not None and self._panel.isVisible()

    def apply_realtime_event(self, event_type: str, data: dict) -> None:
        if self._panel is not None and self._panel.isVisible():
            self._panel.apply_realtime_event(event_type, data)

    def close_center(self):
        if self._panel is not None:
            self._panel.close()
