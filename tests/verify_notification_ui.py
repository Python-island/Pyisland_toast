"""使用模拟通知快照测试完整监听到页面链路，不读取用户通知。"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from pyisland_toast.app import ToastWindow
from pyisland_toast.method import notification_watcher as module


class FakeSource:
    def __init__(self):
        self.notices = []

    async def request_permission(self):
        return 'Allowed'

    async def read(self):
        return self.notices


async def main():
    window = ToastWindow()
    window.show()
    loaded = asyncio.get_running_loop().create_future()
    window.frontendReady.connect(lambda ok: loaded.set_result(ok) if not loaded.done() else None)
    watcher = module.NotificationWatcher(interval=0.05)
    watcher.titleReceived.connect(window.show_system_notification)
    payloads = []
    window.bridge.toastRequested.connect(lambda data: payloads.append(json.loads(data)))

    async def probe():
        result = asyncio.get_running_loop().create_future()
        window.view.page().runJavaScript("""
          JSON.stringify({count:document.querySelectorAll('.snackbar').length,
            text:document.querySelector('.text-static')?.textContent,
            mode:document.querySelector('.snackbar')?.className,
            svg:document.querySelectorAll('.snackbar__lottie svg').length})
        """, 0, result.set_result)
        return json.loads(await asyncio.wait_for(result, 3))

    try:
        window.init_webengine()
        assert await asyncio.wait_for(loaded, 15), '页面加载失败'
        await asyncio.sleep(0.8)
        source = FakeSource()
        with patch.object(module, 'NotificationSource', return_value=source):
            watcher.start()
            await asyncio.sleep(0.15)
            source.notices = [
                module.NotificationTitle(1, '1', '模拟系统消息标题'),
                module.NotificationTitle(2, '2', '  '),
            ]
            await asyncio.sleep(1.3)
            first = await probe()
            assert first['count'] == 1 and first['text'] == '模拟系统消息标题', first
            assert first['svg'] == 1 and 'icon-lottie' in first['mode'], first
            print('PASS first title and Message.json SVG', flush=True)
            await asyncio.sleep(5.0)
            second = await probe()
            assert second['count'] == 1 and second['text'] == module.EMPTY_TITLE, second
            assert second['svg'] == 1, second
            assert len(payloads) == 2, '重复快照产生重复通知'
            assert all('body' not in item and 'title' not in item for item in payloads)
            window.set_sleeping(True)
            window.show_system_notification('休眠时不显示')
            assert len(payloads) == 2, '休眠拦截失败'
            print('PASS empty-title fallback, serial queue, deduplication and sleep gate', flush=True)
    finally:
        await watcher.aclose()
        window.close()


QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
app = QApplication([])
app.setQuitOnLastWindowClosed(False)
loop = QEventLoop(app)
asyncio.set_event_loop(loop)
with loop:
    loop.run_until_complete(main())
