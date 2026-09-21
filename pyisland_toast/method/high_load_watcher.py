import ctypes
import logging
import threading
import time
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)

POLL_INTERVAL = 3
CPU_THRESHOLD = 80.0
CONFIRMATIONS_REQUIRED = 2

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class FileTime(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    def value(self) -> int:
        return (self.high << 32) | self.low


class Rect(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("monitor", Rect),
        ("work", Rect),
        ("flags", wintypes.DWORD),
    ]


user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(Rect)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HANDLE
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
user32.GetMonitorInfoW.restype = wintypes.BOOL
kernel32.GetSystemTimes.argtypes = [
    ctypes.POINTER(FileTime),
    ctypes.POINTER(FileTime),
    ctypes.POINTER(FileTime),
]
kernel32.GetSystemTimes.restype = wintypes.BOOL


def _system_cpu_usage(previous: tuple[int, int] | None) -> tuple[float, tuple[int, int]] | None:
    """使用 GetSystemTimes 计算两次采样之间的系统 CPU 使用率。"""
    idle = FileTime()
    kernel = FileTime()
    user = FileTime()
    if not kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        return None

    current_kernel = kernel.value()
    current_user = user.value()
    current_idle = idle.value()
    if previous is None:
        return None

    previous_total, previous_idle = previous
    total = (current_kernel + current_user) - previous_total
    idle_delta = current_idle - previous_idle
    if total <= 0:
        return None
    usage = max(0.0, min(100.0, (total - idle_delta) * 100 / total))
    return usage, (current_kernel + current_user, current_idle)


def _is_fullscreen_foreground() -> bool:
    """判断当前前台窗口是否覆盖其所在显示器，常用于识别游戏场景。"""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False

    window_rect = Rect()
    monitor = user32.MonitorFromWindow(hwnd, 2)
    info = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
    if not user32.GetWindowRect(hwnd, ctypes.byref(window_rect)):
        return False
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return False

    return (
        window_rect.left <= info.monitor.left
        and window_rect.top <= info.monitor.top
        and window_rect.right >= info.monitor.right
        and window_rect.bottom >= info.monitor.bottom
    )


def is_high_load() -> bool:
    """返回当前是否可能处于全屏高负载场景。

    单次调用无法计算 CPU 使用率，因此由 HighLoadWatcher 负责采样并判断。
    这个函数保留为公共检测入口，实际检测使用 _HighLoadSampler。
    """
    return _is_fullscreen_foreground()


class _HighLoadSampler:
    def __init__(self):
        self._previous = None

    def sample(self) -> bool:
        result = _system_cpu_usage(self._previous)
        if result is None:
            idle = FileTime()
            kernel = FileTime()
            user = FileTime()
            if kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
            ):
                self._previous = (kernel.value() + user.value(), idle.value())
            return False

        usage, self._previous = result
        return usage >= CPU_THRESHOLD and _is_fullscreen_foreground()


class HighLoadWatcher(QObject):
    """监测全屏高负载场景，并发出进入/退出休眠信号。"""

    highLoadEntered = Signal()
    highLoadExited = Signal()

    def __init__(self, interval: int = POLL_INTERVAL, parent=None):
        super().__init__(parent)
        self.interval = interval
        self._thread: threading.Thread | None = None
        self._stop_event: threading.Event | None = None

    def start(self):
        """启动高负载检测线程。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="HighLoadWatcher",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        """停止高负载检测线程。"""
        if self._stop_event is not None:
            self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._thread = None
        self._stop_event = None

    def _run(self):
        sampler = _HighLoadSampler()
        high_load = False
        high_count = 0
        normal_count = 0

        while self._stop_event is not None and not self._stop_event.is_set():
            try:
                current_high = sampler.sample()
                if current_high:
                    high_count += 1
                    normal_count = 0
                else:
                    normal_count += 1
                    high_count = 0

                if not high_load and high_count >= CONFIRMATIONS_REQUIRED:
                    high_load = True
                    self.highLoadEntered.emit()
                elif high_load and normal_count >= CONFIRMATIONS_REQUIRED:
                    high_load = False
                    self.highLoadExited.emit()
            except Exception:
                logger.exception("高负载状态检测失败")

            if self._stop_event.wait(self.interval):
                break
