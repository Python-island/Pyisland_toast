"""读取 Windows 电池状态，检测电源插拔和低电量，不主动改变电源设置。"""

import ctypes
import logging
import threading
from ctypes import wintypes
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

POLL_INTERVAL = 3
LOW_BATTERY_THRESHOLD = 20
LOW_BATTERY_RESET_THRESHOLD = 25
logger = logging.getLogger(__name__)


class SystemPowerStatus(ctypes.Structure):
    """与 Windows SYSTEM_POWER_STATUS 的字段顺序、大小保持一致。"""

    _fields_ = [
        ("ACLineStatus", wintypes.BYTE),
        ("BatteryFlag", wintypes.BYTE),
        ("BatteryLifePercent", wintypes.BYTE),
        ("SystemStatusFlag", wintypes.BYTE),
        ("BatteryLifeTime", wintypes.DWORD),
        ("BatteryFullLifeTime", wintypes.DWORD),
    ]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.GetSystemPowerStatus.argtypes = [ctypes.POINTER(SystemPowerStatus)]
kernel32.GetSystemPowerStatus.restype = wintypes.BOOL


@dataclass(frozen=True)
class BatteryStatus:
    """None 表示状态未知，不能当作断电、零电量或没有电池。"""

    plugged_in: bool | None
    has_battery: bool | None
    percent: int | None
    charging: bool


def get_battery_status() -> BatteryStatus:
    """读取系统电源快照；API 失败时保留错误，不返回虚假的断电状态。"""
    status = SystemPowerStatus()
    if not kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        raise ctypes.WinError(ctypes.get_last_error())

    flags_known = status.BatteryFlag != 255
    has_battery = not bool(status.BatteryFlag & 128) if flags_known else None
    return BatteryStatus(
        plugged_in=bool(status.ACLineStatus) if status.ACLineStatus in (0, 1) else None,
        has_battery=has_battery,
        percent=(
            int(status.BatteryLifePercent)
            if has_battery is True and status.BatteryLifePercent <= 100
            else None
        ),
        charging=flags_known and has_battery is True and bool(status.BatteryFlag & 8),
    )


class BatteryWatcher(QObject):
    """后台每 5 秒取样；插拔才通知，低电量在一轮放电期间只提醒一次。"""

    notificationRequested = Signal(object)

    def __init__(self, interval: float = POLL_INTERVAL, parent=None):
        super().__init__(parent)
        if interval <= 0:
            raise ValueError("电池检测间隔必须大于 0")
        self.interval = interval
        self._thread = None
        self._stop_event = threading.Event()
        self._previous_ac = None
        self._low_notified = False

    def start(self):
        """开始检测；启动或唤醒时只重建电源基线，不补发旧插拔事件。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._previous_ac = None
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run, args=(self._stop_event,), name="BatteryWatcher", daemon=True
        )
        self._thread.start()

    def stop(self):
        """打断采样等待；未结束的线程保留引用，避免重复启动。"""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
            if not self._thread.is_alive():
                self._thread = None

    def _notifications(self, status: BatteryStatus) -> list[dict]:
        """根据快照产生通知；未知状态不更新基线，无电池设备不提醒。"""
        if status.has_battery is False:
            self._previous_ac = None
            self._low_notified = False
            return []
        if status.has_battery is None or status.plugged_in is None:
            return []

        events = []
        battery = {"percent": status.percent, "charging": status.charging}
        if self._previous_ac is not None and status.plugged_in != self._previous_ac:
            events.append({
                "message": "电源已连接" if status.plugged_in else "电源已断开",
                "type": "电源已连接" if status.plugged_in else "电源已断开",
                "variant": "charging" if status.plugged_in else "default",
                "battery": battery,
                "duration": 4500,
            })
        self._previous_ac = status.plugged_in

        # 20% 提醒、25% 以上复位，避免电量在阈值附近波动时重复通知。
        if status.plugged_in or (
            status.percent is not None and status.percent > LOW_BATTERY_RESET_THRESHOLD
        ):
            self._low_notified = False
        elif (
            status.percent is not None
            and status.percent <= LOW_BATTERY_THRESHOLD
            and not self._low_notified
        ):
            self._low_notified = True
            events.append({
                "message": f"电池电量仅剩{status.percent}%",
                "type": "电量不足",
                "variant": "default",
                "battery": battery,
                "duration": 5000,
            })
        return events

    def _run(self, stop_event: threading.Event):
        """仅本线程更新检测状态，通过 Qt 信号交由主线程显示通知。"""
        while not stop_event.is_set():
            try:
                status = get_battery_status()
                if stop_event.is_set():
                    break
                for event in self._notifications(status):
                    if not stop_event.is_set():
                        self.notificationRequested.emit(event)
            except Exception:
                logger.exception("电池状态检测失败")
            if stop_event.wait(self.interval):
                break
