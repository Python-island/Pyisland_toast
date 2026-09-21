import sys
import os
import json
from pathlib import Path

os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    " ".join(
        [
            "--in-process-gpu",
            "--no-proxy-server",
            "--proxy-bypass-list=<-loopback>",
            "--disable-features=Translate,MediaRouter,OptimizationHints,"
            "IsolateOrigins,site-per-process",
            "--disable-plugins",
            "--disable-extensions",
            "--disable-component-update",
            "--disable-domain-reliability",
            "--disable-background-networking",
            "--disable-default-apps",
            "--disable-sync",
            "--disable-low-res-tiling",
            "--disable-renderer-backgrounding",
            "--disable-background-timer-throttling",
            "--disable-breakpad",
            "--disable-crash-reporter",
            "--renderer-process-limit=1",
            "--process-per-site",
            "--js-flags=--max-old-space-size=64",
        ]
    ),
)

# QtWebEngine 模块有意延迟到 ToastWindow 内部导入。
# 如果在这里提前导入，会明显拖慢首个窗口的显示速度。
from PySide6.QtCore import Qt, QObject, Signal, Slot, QUrl, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_ROOT / "toast_frontend" / "frontend"
DIST_INDEX = FRONTEND_DIR / "dist" / "index.html"
DEV_URL = "http://localhost:5173/"


class ToastBridge(QObject):
    """通过 QWebChannel 暴露给 Web 前端的桥接对象。"""

    toastRequested = Signal(str)

    @Slot(str, str, int, str)
    def show_toast(
        self,
        message: str,
        toast_type: str = "",
        duration: int = 3000,
        icon: str = "",
    ):
        """序列化 toast 请求，并发送给 Vue 前端。"""
        payload = json.dumps(
            {
                "message": message,
                "type": toast_type,
                "duration": duration,
                "icon": icon,
            }
        )
        self.toastRequested.emit(payload)


class ToastWindow(QWidget):
    """承载 snackbar Web UI 的透明置顶窗口。"""

    frontendReady = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
            | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

        self.bridge = ToastBridge(self)
        self._sleeping = False
        self.view = None
        self.channel = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.resize(420, 80)
        self._position_window()

    def init_webengine(self):
        """窗口显示后再创建 QWebEngineView。

        这样可以把轻量 QWidget 的启动路径与较重的 Chromium 初始化路径分开。
        """
        from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebChannel import QWebChannel

        profile = QWebEngineProfile(self)
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies
        )
        profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)

        self.view = QWebEngineView(self)
        self.view.setAttribute(Qt.WA_TranslucentBackground, True)
        self.view.setStyleSheet("background: transparent")

        page = QWebEnginePage(profile, self.view)
        page.setBackgroundColor(Qt.transparent)

        settings = page.settings()
        for attr in (
            "PluginsEnabled",
            "FullScreenSupportEnabled",
            "JavascriptCanPaste",
            "JavascriptCanOpenWindows",
            "JavascriptCanAccessClipboard",
            "AllowWindowActivationFromJavaScript",
            "WebGLEnabled",
            "PdfViewerEnabled",
            "HyperlinkAuditingEnabled",
            "ErrorPageEnabled",
            "ScrollAnimatorEnabled",
            "ShowScrollBars",
            "FocusOnNavigationEnabled",
            "SpatialNavigationEnabled",
            "Accelerated2dCanvasEnabled",
        ):
            if hasattr(settings, attr):
                setattr(settings, attr, False)

        self.channel = QWebChannel(self)
        self.channel.registerObject("toastBridge", self.bridge)
        page.setWebChannel(self.channel)

        self.view.setPage(page)
        self.layout().addWidget(self.view)
        self.view.loadFinished.connect(self.frontendReady)
        self._load_frontend()

    def _load_frontend(self):
        """开发模式加载 Vite dev server，否则加载已构建的 dist。"""
        use_dev = "--dev" in sys.argv or os.environ.get("TOAST_DEV") == "1"
        if use_dev:
            self.view.setUrl(QUrl(DEV_URL))
        elif DIST_INDEX.exists():
            self.view.setUrl(QUrl.fromLocalFile(str(DIST_INDEX)))
        else:
            print(
                f"[warn] {DIST_INDEX} not found. Run 'npm run build' in the frontend "
                f"directory or launch with --dev (requires 'npm run dev').",
                file=sys.stderr,
            )
            self.view.setUrl(QUrl.fromLocalFile(str(DIST_INDEX)))

    def _position_window(self):
        """将 toast 放置在主屏幕偏下居中的位置。"""
        screen = QGuiApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        win_w = self.width()
        win_h = self.height()
        x = (geo.width() - win_w) // 2 + geo.left()
        y = int(geo.height() * 0.8 - win_h // 2) + geo.top()
        self.move(x, y)

    def show_toast(
        self,
        message: str,
        toast_type: str = "",
        duration: int = 3000,
        icon: str = "",
        force: bool = False,
    ):
        """供后端服务调用的 Python 侧公开接口。"""
        if self._sleeping and not force:
            return
        self.bridge.show_toast(message, toast_type, duration, icon)

    def set_sleeping(self, sleeping: bool):
        """设置休眠状态；休眠期间普通 toast 请求会被忽略。"""
        self._sleeping = sleeping


def _show_bluetooth_toast(window: ToastWindow, device_name: str):
    """将新连接的蓝牙设备转换为带类型的 toast。"""
    window.show_toast(f"已连接到 {device_name}", "蓝牙设备", 4000)


def _show_network_toast(window: ToastWindow, network_name: str, network_kind: str):
    """将网络连接事件转换为网络类型 toast。"""
    message = f"已连接到{network_name}" if network_kind == "wifi" else network_name
    window.show_toast(message, "网络连接", 4000)


def _show_high_load_toast(window: ToastWindow):
    """显示高负载休眠提醒，允许绕过普通 toast 的休眠拦截。"""
    window.show_toast(
        "系统处于高负载状态，Pyisland_toast将休眠",
        "系统高负载",
        6500,
        force=True,
    )


def _show_wakeup_toast(window: ToastWindow):
    """显示高负载结束后的唤醒提醒。"""
    window.show_toast("Pyisland_toast已唤醒", "系统高负载", 3500, force=True)


def _show_ready_toast(window: ToastWindow):
    """应用前端加载完成后，显示带应用图标的启动提示。"""
    icon_path = PROJECT_ROOT / "pyisland_toast" / "ico" / "PyislandLogo.ico"
    icon_url = QUrl.fromLocalFile(str(icon_path)).toString()
    QTimer.singleShot(
        250,
        lambda: window.show_toast(
            "Pyisland_toast is ready", duration=3500, icon=icon_url
        ),
    )


def main():
    """注册为 pyisland-toast 命令的应用入口。"""
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    window = ToastWindow()
    window.show()

    window.frontendReady.connect(
        lambda loaded: _show_ready_toast(window) if loaded else None
    )

    QTimer.singleShot(0, window.init_webengine)

    from pyisland_toast.method.bluetooth_watcher import BluetoothDeviceWatcher
    from pyisland_toast.method.network_watcher import NetworkWatcher

    watcher = BluetoothDeviceWatcher(parent=app)
    watcher.deviceConnected.connect(lambda name: _show_bluetooth_toast(window, name))
    watcher.start()

    network_watcher = NetworkWatcher(parent=app)
    network_watcher.networkConnected.connect(
        lambda name, kind: _show_network_toast(window, name, kind)
    )
    network_watcher.start()

    from pyisland_toast.method.high_load_watcher import HighLoadWatcher

    high_load_watcher = HighLoadWatcher(parent=app)

    def enter_sleep():
        _show_high_load_toast(window)
        window.set_sleeping(True)
        watcher.stop()
        network_watcher.stop()

    def exit_sleep():
        window.set_sleeping(False)
        watcher.start()
        network_watcher.start()
        _show_wakeup_toast(window)

    high_load_watcher.highLoadEntered.connect(enter_sleep)
    high_load_watcher.highLoadExited.connect(exit_sleep)
    high_load_watcher.start()

    app.aboutToQuit.connect(watcher.stop)
    app.aboutToQuit.connect(network_watcher.stop)
    app.aboutToQuit.connect(high_load_watcher.stop)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
