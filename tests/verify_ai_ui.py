"""真实 QtWebEngine 验证 AI 侧边栏、Toast 共存及 Alt+V。"""

import asyncio
import os
import ctypes
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication
from qasync import QEventLoop
from shiboken6 import isValid

from pyisland_toast.ai_ui import AI_IDLE_TIMEOUT, AiWindowController, panel_frame
from pyisland_toast.app import FRONTEND_DIR, ToastWindow
from pyisland_toast.win32_hotkey import (
    GlobalHotkeyWindow,
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    WM_HOTKEY,
)


async def page_state(view, script):
    future = asyncio.get_running_loop().create_future()
    view.page().runJavaScript(script, 0, future.set_result)
    return await asyncio.wait_for(future, 3)


async def wait_loaded(window):
    if window._loaded:
        return
    while not window._loaded:
        await asyncio.sleep(0.05)


async def wait_window(controller, name):
    """WM_HOTKEY 是排队消息，等待 Qt 处理后控制器才会按需创建窗口。"""
    while getattr(controller, name) is None:
        await asyncio.sleep(0.02)
    window = getattr(controller, name)
    await wait_loaded(window)
    return window


async def verify():
    os.environ["PYISLAND_AI_DISABLED"] = "1"
    toast = ToastWindow()
    controller = AiWindowController(toast, FRONTEND_DIR)
    hotkey = GlobalHotkeyWindow(
        hotkey_id=73,
        modifiers=MOD_ALT | MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT,
        key=0x87,  # F24
    )
    hotkey.activated.connect(controller.toggle_input)
    payloads = []
    toast.bridge.toastRequested.connect(payloads.append)
    try:
        screen = QGuiApplication.primaryScreen()
        width, height, target = panel_frame(screen)

        assert hotkey.registered
        ctypes.windll.user32.PostMessageW(int(hotkey.winId()), WM_HOTKEY, 73, 0)
        await asyncio.wait_for(wait_window(controller, "panel"), 15)
        await asyncio.sleep(0.7)
        assert controller.panel.isVisible()
        assert controller.panel.width() == width
        assert controller.panel.height() == height
        assert abs(controller.panel.x() - target.x()) <= 2
        assert abs(controller.panel.y() - target.y()) <= 2
        panel_state = json.loads(await page_state(controller.panel.view, """
          JSON.stringify({input:!!document.querySelector('.ai-input'),
            panel:!!document.querySelector('.panel'),
            shadow:getComputedStyle(document.querySelector('.panel')).boxShadow,
            active:document.activeElement?.classList.contains('ai-input')})
        """))
        assert panel_state["input"] and panel_state["panel"], panel_state
        assert panel_state["shadow"] == "none" and panel_state["active"], panel_state
        print("PASS right floating sidebar geometry, focus and no shadow", flush=True)

        toast.show_toast("AI 打开时仍可显示")
        assert len(payloads) == 2, payloads
        opened = json.loads(payloads[0])
        assert opened["message"] == "侧边栏AI已启动" and opened["type"] == "侧边栏AI"
        assert json.loads(payloads[1])["message"] == "AI 打开时仍可显示"
        print("PASS toast remains available while AI is open", flush=True)

        original = controller.panel
        controller.bridge.closePanel()
        await asyncio.sleep(0.15)
        assert original.isVisible(), "退出动画尚未结束时不应隐藏窗口"
        await asyncio.sleep(0.45)
        assert not original.isVisible() and controller.panel is original
        hotkey.activated.emit()
        await asyncio.sleep(0.7)
        assert controller.panel is original and controller.panel.isVisible()
        print("PASS Esc slide-out, retained window and replayed enter animation", flush=True)

        controller.bridge.submitPrompt("你好 AI")
        await asyncio.sleep(0.3)
        assert controller.panel.isVisible()
        chat_state = json.loads(await page_state(controller.panel.view, """
          JSON.stringify({count:document.querySelectorAll('.message').length,
            user:document.querySelector('.message--user p')?.textContent})
        """))
        assert chat_state == {"count": 2, "user": "你好 AI"}, chat_state
        print("PASS submit stays in the same sidebar", flush=True)

        old_panel = controller.panel
        controller._idle_timer.setInterval(250)
        controller._touch()
        await asyncio.sleep(0.9)
        assert controller.panel is None
        assert not isValid(old_panel)
        controller._idle_timer.setInterval(AI_IDLE_TIMEOUT)
        hotkey.activated.emit()
        await asyncio.sleep(1.2)
        assert controller.panel is not None and controller.panel is not old_panel
        assert controller.panel.isVisible()
        print("PASS idle reclamation and on-demand WebEngine recreation", flush=True)

        controller.set_runtime_sleep(True, False)
        hotkey.activated.emit()
        assert not controller.active
        controller.set_runtime_sleep(False, False)
        print("PASS runtime sleep gate", flush=True)
    finally:
        controller.close()
        hotkey.close()
        toast.close()


QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
app = QApplication([])
app.setQuitOnLastWindowClosed(False)
loop = QEventLoop(app)
asyncio.set_event_loop(loop)
with loop:
    loop.run_until_complete(verify())
