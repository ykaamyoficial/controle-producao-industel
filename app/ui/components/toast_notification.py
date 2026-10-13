from __future__ import annotations

from PySide6.QtCore import QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QLabel

from app.ui.animations import SPRING_MS, spring, transition, window_motion_enabled
from app.ui.components.window_shell import APPEAR_MS, EXIT_MS, window_shell_enabled
from app.ui.theme_tokens import active_tokens, contrast_text

TOAST_VISIBLE_MS = 2600
_TOAST_RADIUS = 12
_TOAST_TRAVEL = 14  # o aviso desce estes pixels enquanto aparece


class ToastNotification(QLabel):
    """Aviso rapido no canto de cima da janela (sucesso ou erro).

    Com a casca nova das janelas ligada ele se pinta sozinho sobre fundo
    transparente (canto liso), desce com a mola ao aparecer e some subindo.
    Sem ela continua como era: cor e canto pela folha de estilo
    (`QLabel#ToastNotification[kind]`), aparecendo e sumindo de uma vez.
    """

    def __init__(self, parent, message: str, kind: str = "success"):
        super().__init__(message, parent)
        self._painted = window_shell_enabled()
        self._opacity = 1.0
        self._lift = 0.0  # 1 = ainda acima do lugar, 0 = no lugar
        flags = Qt.FramelessWindowHint | Qt.ToolTip
        if self._painted:
            flags |= Qt.NoDropShadowWindowHint
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowFlags(flags)
        # Tamanho (e, sem a casca, cor e canto) vem de QLabel#ToastNotification.
        self.setObjectName("ToastNotification")
        self.setProperty("kind", "success" if kind == "success" else "error")
        self.adjustSize()
        if self._painted:
            self.resize(self.width(), self.height() + _TOAST_TRAVEL)
        parent_rect = parent.geometry()
        self.move(parent_rect.right() - self.width() - 34, parent_rect.top() + 34 - (_TOAST_TRAVEL if self._painted else 0))
        if self._painted and window_motion_enabled():
            self._opacity, self._lift = 0.0, 1.0
        self.show()
        if self._painted:
            transition(self, "_opacity", 1.0, APPEAR_MS)
            transition(self, "_lift", 0.0, SPRING_MS, spring)
            QTimer.singleShot(TOAST_VISIBLE_MS, self._leave)
        else:
            QTimer.singleShot(TOAST_VISIBLE_MS, self.close)

    def _leave(self) -> None:
        transition(self, "_lift", 1.0, EXIT_MS)
        transition(self, "_opacity", 0.0, EXIT_MS, on_finished=self._finish)

    def _finish(self) -> None:
        self.close()
        self.deleteLater()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if not self._painted:
            super().paintEvent(event)
            return
        tokens = active_tokens()
        fill = tokens["success"] if self.property("kind") == "success" else tokens["danger"]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setOpacity(max(0.0, min(1.0, self._opacity)))
        body = QRectF(0, _TOAST_TRAVEL * (1 - self._lift), self.width(), self.height() - _TOAST_TRAVEL)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(body, _TOAST_RADIUS, _TOAST_RADIUS)
        painter.setPen(QColor(contrast_text(fill)))
        painter.setFont(self.font())
        painter.drawText(body, Qt.AlignCenter | Qt.TextWordWrap, self.text())
        painter.end()
