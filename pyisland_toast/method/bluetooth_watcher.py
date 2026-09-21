import asyncio
import logging
import threading

from PySide6.QtCore import QObject, Signal

from pyisland_toast.method.bluetooth_devices import (
    ABORTED_HRESULT,
    get_connected_devices,
)

POLL_INTERVAL = 5
logger = logging.getLogger(__name__)


class DeviceSnapshot:
    """watcher 设备对象的轻量快照。

    Device 对象来自原生扩展。这里只复制需要的字段，避免长时间持有原生对象。
    """

    def __init__(self, device):
        self.id = device.id
        self.name = device.name


class BluetoothDeviceWatcher(QObject):
    """轮询已连接的蓝牙设备，并发出新连接设备名称。

    蓝牙库暴露的是 asyncio API，而 UI 运行在 Qt 事件循环中。
    这里在守护线程中运行独立 asyncio 循环，并通过 Qt 信号安全通知主线程。
    """

    deviceConnected = Signal(str)

    def __init__(self, interval: int = POLL_INTERVAL, parent=None):
        super().__init__(parent)
        self.interval = interval
        self._thread = None
        self._loop = None
        self._stop_event = None

    def start(self):
        """启动后台轮询线程，重复调用不会重复启动。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="BluetoothDeviceWatcher",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        """请求轮询线程停止，并短暂等待其清理完成。"""
        if self._stop_event is not None:
            self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._thread = None
        self._loop = None
        self._stop_event = None

    def _run(self):
        """线程入口：创建并独占 asyncio 事件循环。"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._watch())
        finally:
            self._loop.close()

    async def _watch(self):
        """轮询设备，与上一轮快照比较，并发出新增连接事件。"""
        known_ids = None

        while not self._stop_event.is_set():
            try:
                devices = await get_connected_devices()
                snapshots = [DeviceSnapshot(d) for d in devices]
                current_ids = {s.id for s in snapshots}

                if known_ids is None:
                    # 首次轮询只建立基线。应用启动前已经连接的设备不应触发 toast。
                    known_ids = current_ids
                else:
                    new_ids = current_ids - known_ids
                    for snapshot in snapshots:
                        if snapshot.id in new_ids:
                            self.deviceConnected.emit(snapshot.name)
                    known_ids = current_ids
            except Exception as exc:
                if ABORTED_HRESULT.lower() in str(exc).lower():
                    logger.debug("蓝牙设备轮询被系统短暂中止：%s", exc)
                else:
                    logger.warning("Bluetooth device poll failed: %s", exc)

            if self._stop_event.wait(self.interval):
                break
