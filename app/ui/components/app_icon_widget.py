"""AppIcon: QLabel que renderiza um AppIcons semantico via IconProvider,
respeitando tokens de tamanho/cor/estado. Uso tipico: icones estaticos em
cards, cabecalhos, listas - qualquer lugar que hoje faria
`label.setPixmap(make_icon(...).pixmap(...))` manualmente.
"""

from __future__ import annotations

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QWidget

from app.ui.icons import AppIcons, IconColorRole, IconSize, IconState, icon_provider


class AppIcon(QLabel):
    def __init__(
        self,
        icon: AppIcons,
        palette: dict | None = None,
        size: int = IconSize.MD,
        color_role: IconColorRole = IconColorRole.PRIMARY,
        state: IconState = IconState.NORMAL,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._icon = icon
        self._palette = palette or {}
        self._size = int(size)
        self._color_role = color_role
        self._state = state
        self.setFixedSize(self._size, self._size)
        self._refresh()

    def _refresh(self) -> None:
        qicon = icon_provider.resolve_icon(self._icon, self._size, self._color_role, self._palette, self._state)
        pixmap = qicon.pixmap(self._size, self._size) if qicon is not None else QPixmap()
        self.setPixmap(pixmap)

    def set_icon(self, icon: AppIcons) -> None:
        self._icon = icon
        self._refresh()

    def set_palette(self, palette: dict) -> None:
        self._palette = palette or {}
        self._refresh()

    def set_color_role(self, role: IconColorRole) -> None:
        self._color_role = role
        self._refresh()

    def set_state(self, state: IconState) -> None:
        self._state = state
        self._refresh()
