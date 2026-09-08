"""AppIconButton: QPushButton com icone semantico (AppIcons) ou nome legado,
tooltip que vira acessibilidade automaticamente, badge opcional e helpers de
motion (pulse/shake/rotate_while). Base para os botoes de icone do app -
`ModernButton` e os botoes da barra superior sao implementados por cima
desta classe.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QWidget

from app.ui.components.count_badge import format_count_badge
from app.ui.icons import AppIcons, IconColorRole, IconSize, icon_motion, icon_provider, make_icon, resolve_color


class AppIconButton(QPushButton):
    def __init__(
        self,
        icon: "AppIcons | str | None" = None,
        text: str = "",
        *,
        palette: dict | None = None,
        color: str | None = None,
        color_role: IconColorRole = IconColorRole.PRIMARY,
        size: int = IconSize.MD,
        accent: bool = False,
        tooltip: str | None = None,
        checkable: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(text, parent)
        self._icon = icon
        self._palette = palette or {}
        self._color_override = color
        self._color_role = color_role
        self._size = int(size)
        self._badge_count = 0

        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("AccentButton" if accent else "GhostButton")
        self.setIconSize(QSize(self._size, self._size))
        self.setCheckable(checkable)
        if tooltip:
            self.setToolTip(tooltip)
            self.setAccessibleName(tooltip)
            self.setAccessibleDescription(tooltip)
        self._refresh_icon()

    def _resolve_color(self) -> str:
        if self._color_override:
            return self._color_override
        role = IconColorRole.DISABLED if not self.isEnabled() else self._color_role
        return resolve_color(role, self._palette)

    def _refresh_icon(self) -> None:
        if self._icon is None:
            return
        color = self._resolve_color()
        if isinstance(self._icon, AppIcons):
            qicon = icon_provider.get_icon(self._icon, self._size, color)
        else:
            qicon = make_icon(str(self._icon), color, self._size)
        if qicon is not None:
            self.setIcon(qicon)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 (Qt override)
        super().setEnabled(enabled)
        self._refresh_icon()

    def set_icon_semantic(self, icon: "AppIcons | str") -> None:
        self._icon = icon
        self._refresh_icon()

    def set_palette(self, palette: dict) -> None:
        self._palette = palette or {}
        self._refresh_icon()
        self.update()

    def set_color_override(self, color: str) -> None:
        self._color_override = color
        self._refresh_icon()

    def set_color_role(self, role: IconColorRole) -> None:
        self._color_role = role
        self._refresh_icon()

    def set_size(self, size: int) -> None:
        """Re-renderiza o icone no tamanho final pedido, em vez de deixar o
        Qt esticar um pixmap menor (era o que acontecia na sidebar
        recolhida antes desta migracao)."""
        self._size = int(size)
        self.setIconSize(QSize(self._size, self._size))
        self._refresh_icon()

    def pulse(self) -> None:
        icon_motion.pulse(self)

    def shake(self) -> None:
        icon_motion.shake(self)

    def rotate_while(self, active: bool) -> None:
        icon_motion.rotate_while(self, active)

    def set_badge_count(self, count: int) -> None:
        """Numero pequeno sobreposto ao canto superior direito do icone,
        pintado no paintEvent (nunca via setText) — assim o botao nunca
        muda de tamanho/posicao quando o contador aparece ou some."""
        count = max(0, int(count))
        if count == self._badge_count:
            return
        self._badge_count = count
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().paintEvent(event)
        text = format_count_badge(self._badge_count)
        if not text:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        font = painter.font()
        font.setPointSize(max(6, font.pointSize() - 3))
        font.setBold(True)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        pill_width = max(16, metrics.horizontalAdvance(text) + 10)
        pill_height = 14
        rect = QRectF(self.width() - pill_width - 2, 0, pill_width, pill_height)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(self._palette.get("danger", "#dc2626"))))
        painter.drawRoundedRect(rect, pill_height / 2, pill_height / 2)
        painter.setPen(QPen(QColor("#ffffff")))
        painter.drawText(rect, Qt.AlignCenter, text)
        painter.end()
