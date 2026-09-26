"""使用 Win32 RegisterHotKey 注册全局快捷键。"""

import ctypes
import logging
from ctypes import wintypes

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
VK_V = 0x56
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL


class GlobalHotkeyWindow(QWidget):
    """持有稳定 HWND，接收 WM_HOTKEY 后只发 Qt 信号。"""

    activated = Signal()

    def __init__(self, hotkey_id=1, modifiers=MOD_ALT | MOD_NOREPEAT, key=VK_V):
        super().__init__()
        self.hotkey_id = hotkey_id
        self._hwnd = wintypes.HWND(int(self.winId()))
        self._registered = bool(
            user32.RegisterHotKey(self._hwnd, hotkey_id, modifiers, key)
        )
        self.hide()
        if not self._registered:
            error = ctypes.get_last_error()
            reason = "快捷键已被其他程序占用" if error == ERROR_HOTKEY_ALREADY_REGISTERED else "注册失败"
            logger.warning("Alt+V 全局快捷键%s（WinError %s），其他功能继续运行。", reason, error)

    @property
    def registered(self):
        return self._registered

    def nativeEvent(self, event_type, message):
        try:
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            if msg.message == WM_HOTKEY and int(msg.wParam) == self.hotkey_id:
                self.activated.emit()
                return True, 0
        except (TypeError, ValueError):
            logger.exception("解析全局快捷键消息失败。")
        return super().nativeEvent(event_type, message)

    def close(self):
        """幂等注销；不依赖解释器退出时的析构顺序。"""
        if self._registered:
            user32.UnregisterHotKey(self._hwnd, self.hotkey_id)
            self._registered = False
        return super().close()
