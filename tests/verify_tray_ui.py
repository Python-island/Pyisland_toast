"""验证托盘菜单、队列清理和网页冻结，不退出用户正在运行的应用。"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from qasync import QEventLoop
from pyisland_toast.app import ICON_PATH, ToastWindow
from pyisland_toast.tray import RuntimeController, SystemTray


async def verify():
    window = ToastWindow()
    controller = RuntimeController(window, [MagicMock() for _ in range(3)], MagicMock())
    tray = SystemTray(app, controller, ICON_PATH)
    tray.show()
    window.show()
    ready = asyncio.get_running_loop().create_future()
    window.frontendReady.connect(lambda ok: ready.set_result(ok) if not ready.done() else None)
    try:
        window.init_webengine()
        assert await asyncio.wait_for(ready, 15)
        await asyncio.sleep(0.8)
        controller.frontend_ready(True)
        assert not tray.icon.icon().isNull()
        assert [a.text() for a in tray.menu.actions() if not a.isSeparator()] == ['休眠', '设置', '退出']
        window.show_toast('当前通知', duration=10000)
        window.show_toast('不应残留的队列通知', duration=10000)
        await asyncio.sleep(0.8)
        tray.sleep_action.trigger()
        await asyncio.sleep(0.5)
        assert controller.manual_sleep and window._sleeping
        assert tray.sleep_action.text() == '唤醒'
        assert not window.isVisible()
        from PySide6.QtWebEngineCore import QWebEnginePage
        assert window.view.page().lifecycleState() == QWebEnginePage.LifecycleState.Frozen
        print('PASS tray icon, sleep action, hidden window and frozen page', flush=True)

        tray.sleep_action.trigger()
        await asyncio.sleep(1.4)
        assert not controller.sleeping and window.isVisible()
        assert tray.sleep_action.text() == '休眠'
        assert window.view.page().lifecycleState() == QWebEnginePage.LifecycleState.Active
        result = asyncio.get_running_loop().create_future()
        window.view.page().runJavaScript("JSON.stringify({text:document.querySelector('.text-static')?.textContent,count:document.querySelectorAll('.snackbar').length})", 0, result.set_result)
        state = json.loads(await asyncio.wait_for(result, 3))
        assert state['text'] == 'Pyisland_toast已唤醒' and state['count'] == 1, state
        print('PASS wake action and no stale toast queue', flush=True)

        controller.enter_game()
        tray.sleep_action.trigger()
        controller.exit_game()
        assert controller.sleeping, '游戏退出不应取消手动休眠'
        tray.sleep_action.trigger()
        assert not controller.sleeping
        tray.close()
        assert not tray.icon.isVisible()
        print('PASS independent manual/game sleep and tray removal', flush=True)
    finally:
        controller.stop()
        tray.close()
        window.close()


QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
app = QApplication([])
app.setQuitOnLastWindowClosed(False)
loop = QEventLoop(app)
asyncio.set_event_loop(loop)
with loop:
    loop.run_until_complete(verify())
