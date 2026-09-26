"""托盘打开的模型设置窗口。样式与 AI 侧边栏一致，但是独立页面。"""

from __future__ import annotations

import json
import logging
import os
import sys

from PySide6.QtCore import QObject, QPoint, QTimer, QUrl, Signal, Slot, Qt
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QVBoxLayout, QWidget

from pyisland_toast.ai_client import form_settings, save_settings
from pyisland_toast.paths import icon_path

logger = logging.getLogger(__name__)

SETTINGS_WIDTH = 460
SETTINGS_HEIGHT = 720


class SettingsBridge(QObject):
    """设置页只通过这个对象读写 JSON，密钥不进入前端源码。"""

    closeRequested = Signal()
    saved = Signal()
    reloadRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._host = None

    def attach(self, host):
        self._host = host

    @Slot(float, float)
    def dragBy(self, dx, dy):
        host = self._host
        if host is None:
            return
        host.move(host.x() + int(dx), host.y() + int(dy))

    @Slot(result=str)
    def getSettings(self):
        return json.dumps(form_settings(), ensure_ascii=False)

    @Slot(str, result=str)
    def saveSettings(self, payload):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return "设置内容不是有效的 JSON。"
        if not isinstance(data, dict):
            return "设置内容不是有效的 JSON。"
        try:
            save_settings(data)
        except ValueError as exc:
            return str(exc)
        except OSError:
            logger.warning("无法写入 AI 配置。")
            return "无法写入配置文件。"
        self.saved.emit()
        return ""

    @Slot()
    def closeWindow(self):
        self.closeRequested.emit()


class SettingsWindow(QWidget):
    """居中的无边框设置窗，可聚焦，方便输入密钥。"""

    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.html_name = "settings.html"
        self.dev_url = "http://localhost:5173/settings.html"
        self.view = None
        self.channel = None
        self._loaded = False
        self.setWindowTitle("Pyisland 设置")
        self.bridge.attach(self)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        icon = icon_path()
        if icon.is_file():
            self.setWindowIcon(QIcon(str(icon)))
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
        self.channel.registerObject("settingsBridge", self.bridge)
        page.setWebChannel(self.channel)
        self.view.setPage(page)
        self.layout().addWidget(self.view)
        self.view.loadFinished.connect(self._on_loaded)
        use_dev = "--dev" in sys.argv or os.environ.get("TOAST_DEV") == "1"
        page_path = frontend_dir / "dist" / self.html_name
        if use_dev:
            self.view.setUrl(QUrl(self.dev_url))
        else:
            if not page_path.is_file():
                logger.warning("缺少设置页面：%s", page_path)
            self.view.setUrl(QUrl.fromLocalFile(str(page_path)))

    def present(self):
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        width = SETTINGS_WIDTH
        height = SETTINGS_HEIGHT
        if avail is not None:
            width = min(width, max(320, avail.width() - 32))
            height = min(height, max(420, avail.height() - 32))
            x = avail.left() + (avail.width() - width) // 2
            y = avail.top() + (avail.height() - height) // 2
        else:
            x, y = 80, 80
        self.setFixedSize(width, height)
        self.move(QPoint(x, y))
        self.show()
        self.raise_()
        self.activateWindow()
        if self.view is not None:
            self.view.setFocus(Qt.ShortcutFocusReason)
        if self._loaded:
            QTimer.singleShot(0, self._focus_first_field)
        self.bridge.reloadRequested.emit()

    def _on_loaded(self, ok):
        self._loaded = ok
        if ok and self.isVisible():
            self._focus_first_field()

    def _focus_first_field(self):
        if self.view is None or not self._loaded:
            return
        self.view.page().runJavaScript(
            "document.querySelector('.settings-input')?.focus({preventScroll:true})"
        )

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.bridge.closeWindow()
            event.accept()
            return
        super().keyPressEvent(event)


class SettingsController(QObject):
    def __init__(self, frontend_dir, on_saved=None, parent=None):
        super().__init__(parent)
        self.frontend_dir = frontend_dir
        self._on_saved = on_saved
        self.bridge = SettingsBridge(self)
        self.window = None
        self.bridge.closeRequested.connect(self.hide)
        self.bridge.saved.connect(self._saved)

    @Slot()
    def show(self):
        if self.window is None:
            self.window = SettingsWindow(self.bridge)
            self.window.init_webengine(self.frontend_dir)
        self.window.present()

    @Slot()
    def hide(self):
        if self.window is not None:
            self.window.hide()

    def _saved(self):
        if self._on_saved is not None:
            self._on_saved()

    def close(self):
        window = self.window
        self.window = None
        if window is not None:
            window.close()
            window.deleteLater()