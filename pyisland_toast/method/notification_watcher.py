"""异步读取 Windows 通知，只把新通知的标题传给界面。"""

import asyncio
import logging
from collections import OrderedDict
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

POLL_INTERVAL = 2
QUERY_TIMEOUT = 10
RECENT_LIMIT = 2048
EMPTY_TITLE = "你收到一条新消息"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotificationTitle:
    """WinRT 读取器只保留去重字段与标题，不提取正文。"""

    id: int
    creation_time: str
    title: str


class NotificationSource:
    """直接通过 PyWinRT 请求权限并读取系统通知标题。"""

    def __init__(self):
        from winrt.windows.ui.notifications.management import UserNotificationListener

        self.native = UserNotificationListener.current

    async def request_permission(self):
        """必须在 UI 线程调用，权限拒绝时不会启动查询。"""
        from winrt.windows.ui.notifications.management import UserNotificationListenerAccessStatus

        status = await self.native.request_access_async()
        return {
            UserNotificationListenerAccessStatus.ALLOWED: "Allowed",
            UserNotificationListenerAccessStatus.DENIED: "Denied",
            UserNotificationListenerAccessStatus.UNSPECIFIED: "Unspecified",
        }.get(status, "Unknown")

    async def read(self):
        """权限撤销不是空列表；显式报告以免恢复后将旧通知当作新增。"""
        from winrt.windows.ui.notifications.management import UserNotificationListenerAccessStatus

        if self.native.get_access_status() != UserNotificationListenerAccessStatus.ALLOWED:
            raise PermissionError("系统通知访问权限已撤销")
        from winrt.windows.ui.notifications import NotificationKinds

        notifications = await self.native.get_notifications_async(NotificationKinds.TOAST)
        result = []
        for notice in notifications:
            binding = notice.notification.visual.get_binding("ToastGeneric")
            texts = binding.get_text_elements() if binding else []
            result.append(NotificationTitle(
                notice.id, str(notice.creation_time), texts[0].text if texts else ""
            ))
        return result


class NotificationWatcher(QObject):
    """在 qasync 主循环请求权限；暂停期间不查询，恢复后丢弃历史通知。"""

    titleReceived = Signal(str)

    def __init__(self, interval: float = POLL_INTERVAL, parent=None):
        super().__init__(parent)
        if interval <= 0:
            raise ValueError("通知检测间隔必须大于 0")
        self.interval = interval
        self._task = None
        self._active = asyncio.Event()
        self._generation = 0
        self._baseline = True
        self._seen = OrderedDict()
        self._disabled = False
        self.permission = None

    def start(self):
        """由 Qt 主线程调用，避免在后台线程申请 Windows 通知权限。"""
        if self._disabled or self._active.is_set():
            return
        self._generation += 1
        self._baseline = True
        self._seen.clear()
        self._active.set()
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._watch())

    def pause(self):
        """使正在等待的查询结果过期；不阻塞 Qt，也不补弹休眠期间消息。"""
        self._active.clear()
        self._generation += 1

    def stop(self):
        """请求停止；应用退出前由 aclose 等待协程清理完成。"""
        self.pause()
        if self._task is not None and not self._task.done():
            self._task.cancel()

    async def aclose(self):
        """等待取消完成，防止关闭 Qt 事件循环时遗留异步任务。"""
        self.stop()
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    def _new_titles(self, notifications) -> list[str]:
        """以通知 ID 和创建时间去重，不存储正文，空白标题使用固定文案。"""
        titles = []
        for notice in notifications:
            key = (notice.id, notice.creation_time)
            if key not in self._seen and not self._baseline:
                titles.append((notice.title or "").strip() or EMPTY_TITLE)
            self._seen[key] = None
            self._seen.move_to_end(key)
        self._baseline = False
        # 同一通知暂时从快照消失后再次出现，也不会立即被重复播报。
        while len(self._seen) > RECENT_LIMIT:
            self._seen.popitem(last=False)
        return titles

    async def _watch(self):
        """权限拒绝时停用此功能；单次查询错误只跳过本轮，不清空基线。"""
        try:
            source = NotificationSource()
            self.permission = await source.request_permission()
            if self.permission != "Allowed":
                self._disabled = True
                logger.warning("系统通知访问未授权（%s），请检查 Windows 通知访问权限后重启应用。", self.permission)
                return
            logger.info("系统通知监听已授权，仅转发新通知标题。")
            while True:
                await self._active.wait()
                generation = self._generation
                try:
                    notifications = await asyncio.wait_for(
                        source.read(), timeout=QUERY_TIMEOUT
                    )
                    if self._active.is_set() and generation == self._generation:
                        for title in self._new_titles(notifications):
                            self.titleReceived.emit(title)
                except asyncio.CancelledError:
                    raise
                except PermissionError:
                    self._disabled = True
                    logger.warning("系统通知权限已撤销，停止监听；重新授权后请重启应用。")
                    return
                except Exception:
                    # 不记录标题或正文；失败不能伪装成空快照。
                    logger.warning("读取系统通知失败，本轮跳过。", exc_info=True)
                await asyncio.sleep(self.interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._disabled = True
            logger.warning(
                "系统通知监听初始化失败，其他功能继续运行。请检查通知权限和应用包身份配置。",
                exc_info=True,
            )
