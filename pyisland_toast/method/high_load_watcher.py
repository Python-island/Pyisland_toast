import ctypes
import logging
from ctypes import wintypes
from enum import IntEnum

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)

EFFECTIVE_POWER_MODE_V2 = 2
S_OK = 0

powrprof = ctypes.WinDLL("PowrProf.dll", use_last_error=True)


class EffectivePowerMode(IntEnum):
    """powersetting.h 中 EFFECTIVE_POWER_MODE 的 V2 枚举值。"""

    BATTERY_SAVER = 0
    BETTER_BATTERY = 1
    BALANCED = 2
    HIGH_PERFORMANCE = 3
    MAX_PERFORMANCE = 4
    GAME_MODE = 5
    MIXED_REALITY = 6


HIGH_LOAD_MODES = {
    EffectivePowerMode.GAME_MODE,
    EffectivePowerMode.MIXED_REALITY,
}

EffectivePowerModeCallback = ctypes.WINFUNCTYPE(
    None,
    ctypes.c_int,
    wintypes.LPVOID,
)

powrprof.PowerRegisterForEffectivePowerModeNotifications.argtypes = [
    wintypes.ULONG,
    EffectivePowerModeCallback,
    wintypes.LPVOID,
    ctypes.POINTER(wintypes.LPVOID),
]
powrprof.PowerRegisterForEffectivePowerModeNotifications.restype = ctypes.c_long

powrprof.PowerUnregisterFromEffectivePowerModeNotifications.argtypes = [
    wintypes.LPVOID,
]
powrprof.PowerUnregisterFromEffectivePowerModeNotifications.restype = ctypes.c_long


def is_high_load_mode(mode: int) -> bool:
    """判断有效电源模式是否属于游戏或混合现实高负载场景。"""
    try:
        return EffectivePowerMode(mode) in HIGH_LOAD_MODES
    except ValueError:
        return False


class HighLoadWatcher(QObject):
    """通过 PowerSetting V2 回调监测游戏模式和混合现实模式。

    注册成功后，Windows 会立即回调当前有效电源模式；后续模式变化时
    继续回调，因此不需要轮询、CPU 采样或前台窗口判断。
    """

    highLoadEntered = Signal()
    highLoadExited = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._registration_handle = wintypes.LPVOID()
        self._callback = EffectivePowerModeCallback(self._on_power_mode_changed)
        self._started = False
        self._high_load = False

    @property
    def current_high_load(self) -> bool:
        """返回最近一次系统回调报告的高负载状态。"""
        return self._high_load

    def start(self):
        """注册 EFFECTIVE_POWER_MODE_V2 系统通知。"""
        if self._started:
            return

        result = powrprof.PowerRegisterForEffectivePowerModeNotifications(
            EFFECTIVE_POWER_MODE_V2,
            self._callback,
            None,
            ctypes.byref(self._registration_handle),
        )
        if result != S_OK:
            raise OSError(
                result,
                "注册有效电源模式通知失败；需要 Windows 10 1903 或更高版本",
            )
        self._started = True

    def stop(self):
        """注销有效电源模式通知，并等待系统回调结束。"""
        if not self._started:
            return

        result = powrprof.PowerUnregisterFromEffectivePowerModeNotifications(
            self._registration_handle
        )
        if result != S_OK:
            logger.warning("注销有效电源模式通知失败：HRESULT 0x%08X", result & 0xFFFFFFFF)

        self._registration_handle = wintypes.LPVOID()
        self._started = False

    def _on_power_mode_changed(self, mode: int, _context):
        """接收 Windows 回调，仅在高负载状态发生变化时发出 Qt 信号。"""
        high_load = is_high_load_mode(mode)
        if high_load == self._high_load:
            return

        self._high_load = high_load
        if high_load:
            self.highLoadEntered.emit()
        else:
            self.highLoadExited.emit()
