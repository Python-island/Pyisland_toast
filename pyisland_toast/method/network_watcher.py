import asyncio
import logging
import re
import socket
import struct
import subprocess
import threading
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

DNS_SERVER = "114.114.114.114"     # 国内通用 DNS，用于检测网络是否真正可达
DNS_PORT = 53
DNS_TIMEOUT = 2                    # DNS 查询超时（秒）
POLL_INTERVAL = 5                 # 轮询间隔（秒）
DEBOUNCE_CONFIRMATIONS = 2         # 网络切换需要连续确认的次数，防抖
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NetworkConnection:
    """当前可用网络连接的快照。"""

    name: str    # Wi-Fi SSID 或 "已连接网络"
    kind: str    # "wifi" 或 "ethernet"


def _query_dns() -> bool:
    """向 114 DNS 发送最小 DNS 查询，确认网络确实可用。

    构造一个查询 example.com 的 A 记录 DNS 报文，发送后只要能收到
    回复（且交易 ID 匹配），就说明网络是通的。比单纯 ping 更可靠，
    因为有些网络会屏蔽 ICMP。
    """
    transaction_id = 1
    # DNS 报文头：ID、标志（标准查询）、问题数=1、其余为 0
    header = struct.pack("!HHHHHH", transaction_id, 0x0100, 1, 0, 0, 0)
    # 查询部分：example.com + QTYPE=A(1) + QCLASS=IN(1)
    question = b"\x07example\x03com\x00" + struct.pack("!HH", 1, 1)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(DNS_TIMEOUT)
            sock.sendto(header + question, (DNS_SERVER, DNS_PORT))
            response, _ = sock.recvfrom(512)
        # 回复长度合法且交易 ID 匹配即视为网络可达
        return len(response) >= 12 and response[:2] == struct.pack("!H", transaction_id)
    except (OSError, struct.error):
        return False


def _get_wifi_ssid() -> str | None:
    """通过 Windows netsh 获取当前已连接 Wi-Fi 的 SSID。

    解析 `netsh wlan show interfaces` 输出中的 SSID 行。
    未连接 Wi-Fi 或命令执行失败时返回 None。
    """
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
    """获取当前网络连接；无网络时返回 None。

    检测顺序：
    1. 先查 DNS 确认网络可达
    2. 可达则尝试获取 Wi-Fi SSID，有则标记为 wifi，否则视为以太网
    """
    reachable = await asyncio.to_thread(_query_dns)
    if not reachable:
        return None

    ssid = await asyncio.to_thread(_get_wifi_ssid)
    if ssid:
        return NetworkConnection(name=ssid, kind="wifi")
    return NetworkConnection(name="已连接网络", kind="ethernet")


class NetworkWatcher(QObject):
    """每 10 秒检查网络，并通知新建立或切换的网络连接。

    防抖机制：网络轻微抖动可能导致某次检测失败。候选状态必须连续出现
    DEBOUNCE_CONFIRMATIONS 次才确认为真正切换，避免断连瞬间恢复后误弹 toast。
    """

    networkConnected = Signal(str, str)   # (network_name, network_kind)

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
        previous: NetworkConnection | None = None      # 上一次确认的网络
        candidate: NetworkConnection | None = None     # 待确认的候选网络
        candidate_count = 0                            # 候选连续出现次数
        initialized = False                            # 是否已建立基线

        while self._stop_event is not None and not self._stop_event.is_set():
            try:
                current = await get_current_network()
                if not initialized:
                    # 首次检测只建立基线，不提示应用启动前已经存在的网络。
                    initialized = True
                    previous = current
                elif current == previous:
                    # 与已确认网络一致，重置候选计数
                    candidate = None
                    candidate_count = 0
                else:
                    # 网络状态变化，进入候选确认流程
                    if current == candidate:
                        candidate_count += 1
                    else:
                        candidate = current
                        candidate_count = 1

                    # 连续确认达到阈值，正式认定网络切换
                    if candidate_count >= DEBOUNCE_CONFIRMATIONS:
                        previous = candidate
                        candidate = None
                        candidate_count = 0
                        if previous is not None:
                            self.networkConnected.emit(previous.name, previous.kind)
            except Exception:
                logger.exception("网络状态检测失败")

            if self._stop_event.wait(self.interval):
                break