"""右侧浮空 AI 侧边栏和前后端桥接。"""

import inspect
import json
import os
import sys
import threading
from pathlib import Path

from pyisland_toast.ai_client import UNCONFIGURED_REPLY, ChatClient, load_settings, visible_history
from pyisland_toast.windows_mcp_session import WindowsMcpSession

from shiboken6 import isValid
from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPoint,
    QPropertyAnimation,
    QTimer,
    QUrl,
    Signal,
    Slot,
    Qt,
)
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QVBoxLayout, QWidget

AI_WIDTH_RATIO = 0.20
AI_HEIGHT_RATIO = 0.80
AI_EDGE_MARGIN = 16
AI_EXIT_DURATION = 450
AI_IDLE_TIMEOUT = 3 * 60 * 1000


def panel_frame(screen):
    """按屏幕分辨率计算侧边栏尺寸，并浮在工作区右侧。"""
    full = screen.geometry()
    avail = screen.availableGeometry()
    width = max(1, round(full.width() * AI_WIDTH_RATIO))
    height = max(1, round(full.height() * AI_HEIGHT_RATIO))
    width = min(width, max(1, avail.width() - AI_EDGE_MARGIN * 2))
    height = min(height, max(1, avail.height() - AI_EDGE_MARGIN * 2))
    x = avail.right() - AI_EDGE_MARGIN - width + 1
    y = avail.top() + (avail.height() - height) // 2
    return width, height, QPoint(x, y)


class AiBridge(QObject):
    """AI 页面的桥接对象；模型服务接入点保留在 Python 侧。"""

    focusRequested = Signal()
    conversationUpdated = Signal(str)
    submitRequested = Signal(str)
    closeRequested = Signal()
    clearRequested = Signal()
    panelClosed = Signal()
    activityRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._conversation = "[]"

    def set_conversation(self, payload):
        self._conversation = payload
        self.conversationUpdated.emit(payload)

    @Slot(result=str)
    def getConversation(self):
        """页面晚于提交加载时，仍可主动取得当前会话，避免丢失一次性信号。"""
        return self._conversation

    @Slot(str)
    def submitPrompt(self, prompt):
        prompt = prompt.strip()
        if prompt:
            self.submitRequested.emit(prompt)

    @Slot()
    def closePanel(self):
        self.closeRequested.emit()

    @Slot()
    def clearConversation(self):
        self.clearRequested.emit()

    @Slot()
    def userActivity(self):
        self.activityRequested.emit()


class AiPanelWindow(QWidget):
    """透明、无边框、可聚焦的右侧浮空侧边栏。"""

    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.html_name = "ai.html"
        self.dev_url = "http://localhost:5173/ai.html"
        self.view = None
        self.channel = None
        self._loaded = False
        self._desired_visible = False
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._finish_hide)
        self._animation = QPropertyAnimation(self, b"pos", self)
        self._animation.setDuration(AI_EXIT_DURATION)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

    def init_webengine(self, frontend_dir):
        if self.view is not None:
            return
        from PySide6.QtWebChannel import QWebChannel
        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
        from PySide6.QtWebEngineWidgets import QWebEngineView

        profile = QWebEngineProfile(self)
        profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
        profile.setHttpCacheType(QWebEngineProfile.NoCache)
        self.view = QWebEngineView(self)
        self.view.setAttribute(Qt.WA_TranslucentBackground, True)
        self.view.setStyleSheet("background: transparent")
        page = QWebEnginePage(profile, self.view)
        page.setBackgroundColor(Qt.transparent)
        self.channel = QWebChannel(self)
        self.channel.registerObject("aiBridge", self.bridge)
        page.setWebChannel(self.channel)
        self.view.setPage(page)
        self.layout().addWidget(self.view)
        self.view.loadFinished.connect(self._on_loaded)

        use_dev = "--dev" in sys.argv or os.environ.get("TOAST_DEV") == "1"
        url = QUrl(self.dev_url) if use_dev else QUrl.fromLocalFile(
            str(Path(frontend_dir) / "dist" / self.html_name)
        )
        self.view.setUrl(url)

    def _on_loaded(self, ok):
        self._loaded = ok
        if ok and self._desired_visible:
            for delay in (50, 150, 350):
                QTimer.singleShot(delay, self._focus_web_input)

    def _target_position(self):
        screen = QGuiApplication.primaryScreen()
        if not screen:
            return QPoint(0, 0)
        width, height, target = panel_frame(screen)
        self.setFixedSize(width, height)
        return target

    def show_animated(self):
        target = self._target_position()
        self._hide_timer.stop()
        self._animation.stop()
        self._desired_visible = True
        if not (self.isVisible() and self.pos() == target):
            start = QPoint(target.x() + self.width() + AI_EDGE_MARGIN, target.y())
            self.move(start)
            self.show()
            self.raise_()
            self.activateWindow()
            self._animation.setStartValue(start)
            self._animation.setEndValue(target)
            self._animation.start()
        else:
            self.raise_()
            self.activateWindow()
        if self.view is not None:
            self.view.setFocus(Qt.ShortcutFocusReason)
        if self._loaded:
            for delay in (0, 100, 300):
                QTimer.singleShot(delay, self._focus_web_input)

    def animate_hide(self):
        """滑出屏幕后只隐藏，WebEngine 保留到空闲回收。"""
        if not self._desired_visible and not self.isVisible():
            return
        self._desired_visible = False
        if not self.isVisible():
            self.hide()
            return
        end = QPoint(self.x() + self.width() + AI_EDGE_MARGIN, self.y())
        self._animation.stop()
        self._animation.setStartValue(self.pos())
        self._animation.setEndValue(end)
        self._animation.start()
        self._hide_timer.start(AI_EXIT_DURATION)

    def _finish_hide(self):
        if not self._desired_visible:
            self.hide()

    def _focus_web_input(self):
        if not self.isVisible() or self.view is None or not self._loaded:
            return
        self.view.setFocus(Qt.ShortcutFocusReason)
        self.bridge.focusRequested.emit()
        self.view.page().runJavaScript(
            "document.querySelector('.ai-input')?.focus({preventScroll:true})"
        )

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.bridge.closePanel()
            event.accept()
            return
        super().keyPressEvent(event)


class AiWindowController(QObject):
    """管理一个 AI 侧边栏。打开时不抑制 Toast。"""

    replyReady = Signal(int, int, str)
    progressReady = Signal(int, int, str)

    def __init__(self, toast_window, frontend_dir, parent=None):
        super().__init__(parent)
        self.toast_window = toast_window
        self.frontend_dir = frontend_dir
        self.bridge = AiBridge(self)
        self.panel = None
        self.enabled = True
        self._closed = False
        self.messages = []
        self._open = False
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(AI_IDLE_TIMEOUT)
        self._idle_timer.timeout.connect(self._reclaim_windows)
        self._reclaim_timer = QTimer(self)
        self._reclaim_timer.setSingleShot(True)
        self._reclaim_timer.timeout.connect(self._destroy_windows)
        self._client = None
        self._turn = 0
        self._message_seq = 0
        self._mcp = None
        self.replyReady.connect(self._apply_reply)
        self.progressReady.connect(self._apply_progress)
        self.bridge.submitRequested.connect(self.submit)
        self.bridge.closeRequested.connect(self.close_panel)
        self.bridge.clearRequested.connect(self.clear_conversation)
        self.bridge.activityRequested.connect(self._touch)
        if os.environ.get("PYISLAND_AI_DISABLED") != "1":
            settings = load_settings()
            if settings.configured:
                self._mcp = WindowsMcpSession(
                    settings.windows_mcp_command,
                    settings.windows_mcp_exclude_tools,
                )
                self._client = ChatClient(settings, self._mcp)

    def apply_settings(self, settings):
        if getattr(self, "_closed", False):
            return
        if not settings.configured:
            self._client = None
            return
        if self._mcp is None:
            self._mcp = WindowsMcpSession(
                settings.windows_mcp_command,
                settings.windows_mcp_exclude_tools,
            )
        if self._client is None:
            self._client = ChatClient(settings, self._mcp)
        else:
            self._client.settings = settings
            self._client.session = self._mcp

    @property
    def active(self):
        return self._open

    def _ensure_panel(self):
        """首次使用或空闲回收后再创建 WebEngine。"""
        if self.panel is not None:
            return
        self.panel = AiPanelWindow(self.bridge)
        self.panel.init_webengine(self.frontend_dir)

    def _touch(self):
        if not self._closed:
            self._reclaim_timer.stop()
            self._idle_timer.start()

    @Slot()
    def toggle_input(self):
        if not self.enabled:
            return
        self._touch()
        if self._open:
            self.close_panel()
            return
        self._ensure_panel()
        self._open = True
        self.panel.show_animated()
        self._announce_open()
        self._warm_mcp()

    def _announce_open(self):
        show_toast = getattr(self.toast_window, "show_toast", None)
        if show_toast is None:
            return
        show_toast("侧边栏AI已启动", "侧边栏AI", 4000)

    def _warm_mcp(self):
        session = getattr(self, "_mcp", None)
        if session is None or self._closed:
            return

        def run():
            if not self._closed:
                session.ensure_started()

        threading.Thread(target=run, name="PyislandMcp", daemon=True).start()

    @Slot(str)
    def submit(self, prompt):
        if not self.enabled:
            return
        self._touch()
        opening = not self._open
        self._ensure_panel()
        self._open = True
        self._cancel_turn()
        self.messages.append({"role": "user", "content": prompt})
        client = getattr(self, "_client", None)
        if client is None:
            self.messages.append({"role": "assistant", "content": UNCONFIGURED_REPLY})
        else:
            turn = self._turn
            self._message_seq = getattr(self, "_message_seq", 0) + 1
            message_id = self._message_seq
            self.messages.append({
                "id": message_id,
                "role": "assistant",
                "content": "正在思考…",
                "pending": True,
            })
            history = visible_history(self.messages)
            parameters = inspect.signature(client.complete).parameters
            kwargs = {}
            if "on_progress" in parameters:
                kwargs["on_progress"] = lambda text, turn=turn, message_id=message_id: self.progressReady.emit(turn, message_id, text)
            if "should_stop" in parameters:
                kwargs["should_stop"] = lambda turn=turn: self._closed or turn != self._turn
            client.complete(
                history,
                lambda text, turn=turn, message_id=message_id: self._deliver(turn, message_id, text),
                **kwargs,
            )
        self.panel.show_animated()
        if opening:
            self._announce_open()
        self._publish_conversation()

    def _cancel_turn(self):
        self._turn = getattr(self, "_turn", 0) + 1
        changed = False
        for message in self.messages:
            if message.get("pending"):
                message["content"] = "已取消。"
                message["pending"] = False
                changed = True
        return changed

    def _deliver(self, turn, message_id, content):
        self.replyReady.emit(turn, message_id, content)

    def _apply_reply(self, turn, message_id, content):
        if getattr(self, "_closed", False) or turn != getattr(self, "_turn", None):
            return
        found = False
        for message in self.messages:
            if message.get("id") == message_id and message.get("pending"):
                message["content"] = content
                message["pending"] = False
                found = True
                break
        if not found:
            return
        self._publish_conversation()
        self._touch()

    def _apply_progress(self, turn, message_id, content):
        if getattr(self, "_closed", False) or turn != getattr(self, "_turn", None):
            return
        for message in self.messages:
            if message.get("id") == message_id and message.get("pending"):
                message["content"] = content
                self._publish_conversation()
                self._touch()
                return

    @Slot()
    def clear_conversation(self):
        """丢掉当前会话，并忽略尚未返回的模型回复。"""
        if not self.enabled:
            return
        self._touch()
        self._turn = getattr(self, "_turn", 0) + 1
        self.messages = []
        self._publish_conversation()

    @Slot()
    def close_panel(self):
        if self.panel is None:
            return
        self.clear_conversation()
        self._open = False
        self.panel.animate_hide()
        self.bridge.panelClosed.emit()

    @Slot(bool, bool)
    def set_runtime_sleep(self, manual, game):
        self.enabled = not (manual or game)
        if not self.enabled:
            if self._cancel_turn():
                self._publish_conversation()
            self._open = False
            if self.panel is not None:
                self.panel.animate_hide()

    def _publish_conversation(self):
        payload = json.dumps(self.messages, ensure_ascii=False)
        self.bridge.set_conversation(payload)

    def _reclaim_windows(self):
        """连续 3 分钟无 AI 交互后，先滑出，再释放 WebEngine。"""
        if self._closed:
            return
        self._open = False
        if self.panel is not None:
            self.panel.animate_hide()
        self._reclaim_timer.start(AI_EXIT_DURATION + 50)

    def _destroy_windows(self):
        window = self.panel
        if window is not None and isValid(window):
            window.close()
            window.deleteLater()
        self.panel = None

    def close(self):
        """幂等关闭；Qt 退出时顶层窗口可能已先由 QApplication 销毁。"""
        if self._closed:
            return
        self._closed = True
        self._turn = getattr(self, "_turn", 0) + 1
        session = getattr(self, "_mcp", None)
        if session is not None:
            session.close()
        self._idle_timer.stop()
        self._reclaim_timer.stop()
        self._open = False
        self._destroy_windows()
