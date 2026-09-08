from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QPoint


WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084

HTCLIENT = 1
HTCAPTION = 2
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17

SM_CXSIZEFRAME = 32
SM_CYSIZEFRAME = 33
SM_CXPADDEDBORDER = 92

RESIZE_BORDER = 7

_IS_WINDOWS = sys.platform == "win32"


if _IS_WINDOWS:

    class _MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("message", wintypes.UINT),
            ("wParam", wintypes.WPARAM),
            ("lParam", wintypes.LPARAM),
            ("time", wintypes.DWORD),
            ("pt", wintypes.POINT),
        ]

    def _frame_inset() -> int:
        try:
            user32 = ctypes.windll.user32
            return user32.GetSystemMetrics(SM_CXSIZEFRAME) + user32.GetSystemMetrics(SM_CXPADDEDBORDER)
        except Exception:
            return 8


class FramelessHitTestMixin:
    """Mixin for a QMainWindow/QWidget that keeps the native window style
    (WS_CAPTION | WS_THICKFRAME) but suppresses the non-client area so a
    custom-drawn title bar can take its place, while Windows still owns
    resize, Aero Snap and the maximize/restore geometry.

    Requires the widget to expose `self.title_bar` (a widget covering the
    custom title bar region) with an `is_over_interactive_widget(QPoint) ->
    bool` method used to exclude buttons/icons from the drag/caption area.
    """

    def nativeEvent(self, eventType, message):
        if _IS_WINDOWS and eventType == b"windows_generic_MSG":
            msg = _MSG.from_address(int(message))
            if msg.message == WM_NCCALCSIZE:
                if msg.wParam:
                    if self.isMaximized():
                        inset = _frame_inset()
                        params = ctypes.cast(msg.lParam, ctypes.POINTER(wintypes.RECT * 3)).contents
                        rect = params[0]
                        rect.left += inset
                        rect.top += inset
                        rect.right -= inset
                        rect.bottom -= inset
                    return True, 0
            elif msg.message == WM_NCHITTEST:
                if self.isMaximized() or self.isFullScreen():
                    return False, 0
                x = ctypes.c_short(msg.lParam & 0xFFFF).value
                y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                local = self.mapFromGlobal(QPoint(x, y))
                w, h, b = self.width(), self.height(), RESIZE_BORDER
                left = local.x() <= b
                right = local.x() >= w - b
                top = local.y() <= b
                bottom = local.y() >= h - b
                if top and left:
                    return True, HTTOPLEFT
                if top and right:
                    return True, HTTOPRIGHT
                if bottom and left:
                    return True, HTBOTTOMLEFT
                if bottom and right:
                    return True, HTBOTTOMRIGHT
                if left:
                    return True, HTLEFT
                if right:
                    return True, HTRIGHT
                if top:
                    return True, HTTOP
                if bottom:
                    return True, HTBOTTOM
                title_bar = getattr(self, "title_bar", None)
                if title_bar is not None and title_bar.geometry().contains(local):
                    bar_local = title_bar.mapFrom(self, local)
                    if not title_bar.is_over_interactive_widget(bar_local):
                        return True, HTCAPTION
                return False, 0
        return super().nativeEvent(eventType, message)
