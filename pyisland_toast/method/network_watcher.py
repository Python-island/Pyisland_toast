import asyncio
import logging
import re
import socket
import struct
import subprocess
import threading
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

DNS_SERVER = "114.114.114.114"
DNS_PORT = 53
DNS_TIMEOUT = 2
POLL_INTERVAL = 10
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NetworkConnection:
    """当前可用网络连接的快照。"""

    name: str
    kind: str


def _query_dns() -> bool:
    """向 114 DNS 发送最小 DNS 查询，确认网络确实可用。"""
    transaction_id = 1
    header = struct.pack("!HHHHHH", transaction_id, 0x0100, 1, 0, 0, 0)
    question = b"\x07example\x03com\x00" + struct.pack("!HH", 1, 1)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(DNS_TIMEOUT)
            sock.sendto(header + question, (DNS_SERVER, DNS_PORT))
            response, _ = sock.recvfrom(512)
        return len(response) >= 12 and response[:2] == struct.pack("!H", transaction_id)
    except (OSError, struct.error):
        return False


def _get_wifi_ssid() -> str | None:
    """通过 Windows netsh 获取当前已连接 Wi-Fi 的 SSID。"""
    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            timeout=DNS_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    output = result.stdout.decode("utf-8", errors="ignore")
    match = re.search(r"^\s*SSID\s*:\s*(.+?)\s*$", output, re.MULTILINE)
    if not match:
        return None

    ssid = match.group(1).strip()
    return ssid or None


async def get_current_network() -> NetworkConnection | None:
    """获取当前网络连接；无网络时返回 None。"""
    reachable = await asyncio.to_thread(_query_dns)
    if not reachable:
        return None

    ssid = await asyncio.to_thread(_get_wifi_ssid)
    if ssid:
        return NetworkConnection(name=ssid, kind="wifi")
    return NetworkConnection(name="已连接网络", kind="ethernet")


class NetworkWatcher(QObject):
    """每 10 秒检查网络，并通知新建立或切换的网络连接。"""

    networkConnected = Signal(str, str)

    def __init__(self, interval: int = POLL_INTERVAL, parent=None):
        super().__init__(parent)
        self.interval = interval
        self._thread: threading.Thread | None = None
        self._stop_event: threading.Event | None = None

    def start(self):
        """启动后台网络检测线程。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="NetworkWatcher",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        """停止后台网络检测线程。"""
        if self._stop_event is not None:
            self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._thread = None
        self._stop_event = None

    def _run(self):
        asyncio.run(self._watch())

    async def _watch(self):
        previous: NetworkConnection | None = None
        initialized = False

        while self._stop_event is not None and not self._stop_event.is_set():
            try:
                current = await get_current_network()
                if not initialized:
                    # 首次检测只建立基线，不提示应用启动前已经存在的网络。
                    initialized = True
                    previous = current
                elif current is not None and current != previous:
                    # previous 为 None 表示刚从断网状态恢复，也需要提示。
                    self.networkConnected.emit(current.name, current.kind)
                    previous = current
                elif current is None:
                    previous = None
            except Exception:
                logger.exception("网络状态检测失败")

            if self._stop_event.wait(self.interval):
                break
