"""验证系统消息去重、空标题、权限和暂停，不读取真实通知。"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PySide6.QtCore import QCoreApplication

from pyisland_toast.method import notification_watcher as module


def notice(number, title="测试标题", time="1"):
    return SimpleNamespace(id=number, creation_time=time, title=title, message="正文不应转发")


class NotificationDiffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.watcher = module.NotificationWatcher()

    def test_initial_baseline_and_title_only(self):
        self.assertEqual(self.watcher._new_titles([notice(1)]), [])
        self.assertEqual(self.watcher._new_titles([notice(1), notice(2, "  新标题  ")]), ["新标题"])

    def test_empty_and_whitespace_title(self):
        self.watcher._new_titles([])
        result = self.watcher._new_titles([notice(1, ""), notice(2, " \n\t "), notice(3, None)])
        self.assertEqual(result, [module.EMPTY_TITLE] * 3)

    def test_duplicate_and_reappearing_notifications(self):
        self.watcher._new_titles([])
        self.assertEqual(self.watcher._new_titles([notice(1), notice(1)]), ["测试标题"])
        self.watcher._new_titles([])
        self.assertEqual(self.watcher._new_titles([notice(1)]), [])

    def test_reused_id_with_new_creation_time(self):
        self.watcher._new_titles([notice(1)])
        self.assertEqual(self.watcher._new_titles([notice(1, "新消息", "2")]), ["新消息"])

    def test_same_id_content_update_not_new_message(self):
        self.watcher._new_titles([notice(1)])
        self.assertEqual(self.watcher._new_titles([notice(1, "内容更新")]), [])

    def test_invalid_interval(self):
        with self.assertRaises(ValueError):
            module.NotificationWatcher(interval=0)


class NotificationAsyncTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    async def asyncSetUp(self):
        self.watcher = module.NotificationWatcher(interval=0.01)
        self.titles = []
        self.watcher.titleReceived.connect(self.titles.append)

    async def asyncTearDown(self):
        await self.watcher.aclose()

    def source(self, **kwargs):
        return SimpleNamespace(
            request_permission=AsyncMock(return_value=kwargs.get('permission', 'Allowed')),
            read=kwargs.get('read', AsyncMock(return_value=[])),
        )

    async def test_permission_denied_does_not_read(self):
        source = self.source(permission='Denied')
        with patch.object(module, 'NotificationSource', return_value=source):
            with self.assertLogs(module.logger, level='WARNING'):
                self.watcher.start()
                await self.watcher._task
        source.read.assert_not_called()
        self.assertTrue(self.watcher._disabled)

    async def test_poll_error_preserves_baseline(self):
        source = self.source(read=AsyncMock(side_effect=[
            [notice(1)], RuntimeError('模拟中断'), [notice(1), notice(2, '新标题')]
        ]))
        delivered = asyncio.Event()
        self.watcher.titleReceived.connect(lambda _: delivered.set())
        with patch.object(module, 'NotificationSource', return_value=source):
            with self.assertLogs(module.logger, level='WARNING'):
                self.watcher.start()
                await asyncio.wait_for(delivered.wait(), 1)
                await self.watcher.aclose()
        self.assertEqual(self.titles, ['新标题'])

    async def test_pause_discards_inflight_and_resume_rebaselines(self):
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0
        async def read():
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                await release.wait()
            return [notice(1)]
        source = self.source(read=read)
        with patch.object(module, 'NotificationSource', return_value=source):
            self.watcher.start()
            original = self.watcher._task
            self.watcher.start()
            self.assertIs(self.watcher._task, original)
            await started.wait()
            self.watcher.pause()
            release.set()
            await asyncio.sleep(0.03)
            self.assertEqual(calls, 1)
            self.assertTrue(self.watcher._baseline)
            self.watcher.start()
            await asyncio.sleep(0.03)
            self.assertFalse(self.watcher._baseline)
            self.assertEqual(self.titles, [])
            await self.watcher.aclose()
            self.assertTrue(original.done())

    async def test_revoked_permission_stops_polling(self):
        source = self.source(read=AsyncMock(side_effect=PermissionError('已撤销')))
        with patch.object(module, 'NotificationSource', return_value=source):
            with self.assertLogs(module.logger, level='WARNING'):
                self.watcher.start()
                await self.watcher._task
        self.assertTrue(self.watcher._disabled)
        self.assertEqual(self.titles, [])

    async def test_native_permission_status(self):
        # 使用模拟接口，避免测试弹出真实权限窗口。
        from winrt.windows.ui.notifications.management import UserNotificationListenerAccessStatus
        reader = module.NotificationSource.__new__(module.NotificationSource)
        for status, expected in (
            (UserNotificationListenerAccessStatus.ALLOWED, 'Allowed'),
            (UserNotificationListenerAccessStatus.DENIED, 'Denied'),
            (UserNotificationListenerAccessStatus.UNSPECIFIED, 'Unspecified'),
            (99, 'Unknown'),
        ):
            reader.native = SimpleNamespace(request_access_async=AsyncMock(return_value=status))
            self.assertEqual(await reader.request_permission(), expected)
            reader.native.request_access_async.assert_awaited_once()

    async def test_native_reader_titles_and_missing_binding(self):
        from winrt.windows.ui.notifications.management import UserNotificationListenerAccessStatus
        from winrt.windows.ui.notifications import NotificationKinds
        reader = module.NotificationSource.__new__(module.NotificationSource)
        binding = SimpleNamespace(get_text_elements=lambda: [
            SimpleNamespace(text='标题'), SimpleNamespace(text='正文不应转发')
        ])
        notices = [SimpleNamespace(
            id=i, creation_time='time',
            notification=SimpleNamespace(visual=SimpleNamespace(get_binding=lambda _, b=b: b)),
        ) for i, b in enumerate((binding, None, SimpleNamespace(get_text_elements=lambda: [])))]
        reader.native = SimpleNamespace(
            get_access_status=lambda: UserNotificationListenerAccessStatus.ALLOWED,
            get_notifications_async=AsyncMock(return_value=notices),
        )
        self.assertEqual(await reader.read(), [
            module.NotificationTitle(0, 'time', '标题'),
            module.NotificationTitle(1, 'time', ''),
            module.NotificationTitle(2, 'time', ''),
        ])
        reader.native.get_notifications_async.assert_awaited_once_with(NotificationKinds.TOAST)
        reader.native.get_notifications_async.side_effect = RuntimeError('读取失败')
        with self.assertRaises(RuntimeError):
            await reader.read()

    async def test_native_reader_rejects_revoked_access(self):
        from winrt.windows.ui.notifications.management import UserNotificationListenerAccessStatus
        reader = module.NotificationSource.__new__(module.NotificationSource)
        reader.native = SimpleNamespace(
            get_access_status=lambda: UserNotificationListenerAccessStatus.DENIED,
            get_notifications_async=AsyncMock(),
        )
        with self.assertRaises(PermissionError):
            await reader.read()
        reader.native.get_notifications_async.assert_not_called()


if __name__ == '__main__':
    unittest.main()
