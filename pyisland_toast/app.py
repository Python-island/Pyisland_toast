import sys
import asyncio
import os
import json

# 配置 QtWebEngine 内嵌 Chromium 的启动参数，目的是降低资源占用、加快启动速度。
# 由于 toast 窗口只展示一个简单的 snackbar，不需要浏览器的诸多特性，
# 因此尽可能关掉翻译、插件、扩展、同步、后台网络等功能，只保留渲染所需的最小能力。
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    " ".join(
        [
            "--in-process-gpu",            # GPU 进程与主进程合并，减少进程数
            "--no-proxy-server",           # 不走代理，直接连接
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
            "--renderer-process-limit=1",  # 限制渲染进程数，降低内存
            "--process-per-site",
            "--js-flags=--max-old-space-size=64",  # JS 堆上限 64MB，控制内存
        ]
    ),
)

# QtWebEngine 模块有意延迟到 ToastWindow 内部导入。
# 如果在这里提前导入，会明显拖慢首个窗口的显示速度。
from PySide6.QtCore import Qt, QObject, Signal, Slot, QUrl, QTimer
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout

# 路径常量：开发时指向仓库，打包后指向 PyInstaller 解包目录。
from pyisland_toast.paths import configure_logging, dist_index, frontend_dir, icon_path, project_root

PROJECT_ROOT = project_root()
FRONTEND_DIR = frontend_dir()
DIST_INDEX = dist_index()
DEV_URL = "http://localhost:5173/"
ICON_PATH = icon_path()


class ToastBridge(QObject):
    """通过 QWebChannel 暴露给 Web 前端的桥接对象。

    Python 后端调用 show_toast -> 序列化为 JSON -> 通过 toastRequested 信号
    发送给前端，前端 bridge.js 监听该信号并解析后入队显示。
    """

    # 该信号会被注册到 QWebChannel 上，前端可通过 bridge.toastRequested.connect 监听。
    toastRequested = Signal(str)
    clearRequested = Signal()

    @Slot(str, str, int, str)
    def show_toast(
        self,
        message: str,           # toast 显示的文本
        toast_type: str = "",   # 类型标识，前端据此选择对应 Lottie 动画
        duration: int = 3000,   # 显示时长（毫秒）
        icon: str = "",         # 可选的图片图标 URL（file:// 或 data URI）
        variant: str = "default",  # 充电通知使用独立的 charging 样式
        battery: dict | None = None,  # 电量百分比及是否正在充电
    ):
        """序列化 toast 请求，并发送给 Vue 前端。"""
        payload = json.dumps(
            {
                "message": message,
                "type": toast_type,
                "duration": duration,
                "icon": icon,
                "variant": variant,
                "battery": battery,
            }
        )
        self.toastRequested.emit(payload)


class ToastWindow(QWidget):
    """承载 snackbar Web UI 的透明置顶窗口。

    设计要点：
    1. 窗口本身是无边框、置顶、透明背景的，不抢焦点也不接收鼠标事件，
       因此 toast 弹出时不会干扰用户操作。
    2. QWebEngineView 延迟到窗口显示后再创建，让轻量 QWidget 先显示出来，
       把较重的 Chromium 初始化放到后台，加快首屏速度。
    """

    frontendReady = Signal(bool)

    def __init__(self):
        super().__init__()
        # 设置窗口标志：无边框 + 置顶 + 工具窗口 + 不抢焦点 + 鼠标穿透
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
            | Qt.WindowTransparentForInput
        )
        # 透明背景相关属性
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

        self.bridge = ToastBridge(self)
        self._sleeping = False   # 休眠标志：高负载时为 True，普通 toast 会被忽略
        self._toast_suppression = set()
        self.view = None         # QWebEngineView，延迟创建
        self.channel = None      # QWebChannel，桥接 Python 与 JS

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.resize(420, 80)     # 初始尺寸，实际宽度由前端胶囊动画撑开
        self._position_window()  # 定位到屏幕偏下居中位置

    def init_webengine(self):
        """窗口显示后再创建 QWebEngineView。

        这样可以把轻量 QWidget 的启动路径与较重的 Chromium 初始化路径分开。
        首次调用时会从 PySide6 动态导入 QtWebEngine 相关模块。
        """
        from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebChannel import QWebChannel

        # 创建独立的 WebEngine profile，关闭持久化 Cookie 与 HTTP 缓存，
        # 避免 toast 这种一次性 UI 在磁盘上留下数据。
        profile = QWebEngineProfile(self)
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies
        )
        profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)

        self.view = QWebEngineView(self)
        self.view.setAttribute(Qt.WA_TranslucentBackground, True)
        self.view.setStyleSheet("background: transparent")

        # 页面背景透明，这样 snackbar 之外的区域不会挡住桌面。
        page = QWebEnginePage(profile, self.view)
        page.setBackgroundColor(Qt.transparent)

        # 关闭 WebEngine 页面上不需要的能力（插件、全屏、剪贴板访问、WebGL 等），
        # 进一步降低资源占用与潜在安全面。
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

        # 注册桥接对象到 WebChannel，前端通过 window.qt.webChannelTransport 建立连接后，
        # 即可在 channel.objects.toastBridge 拿到该对象。
        self.channel = QWebChannel(self)
        self.channel.registerObject("toastBridge", self.bridge)
        page.setWebChannel(self.channel)

        self.view.setPage(page)
        self.layout().addWidget(self.view)
        self.view.loadFinished.connect(self.frontendReady)
        self._load_frontend()

    def _load_frontend(self):
        """开发模式加载 Vite dev server，否则加载已构建的 dist。

        判断依据：命令行含 --dev 或环境变量 TOAST_DEV=1 时走开发服务器，
        否则加载本地构建产物 dist/index.html。
        """
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
        y = int(geo.height() * 0.9 - win_h // 2) + geo.top()
        self.move(x, y)

    def show_toast(
        self,
        message: str,
        toast_type: str = "",
        duration: int = 3000,
        icon: str = "",
        force: bool = False,
        *,
        variant: str = "default",
        battery: dict | None = None,
    ):
        """供后端服务调用的 Python 侧公开接口。

        Args:
            force: 为 True 时即使处于休眠状态也会显示（用于高负载进入/退出提示）。
        """
        if (self._sleeping or self._toast_suppression) and not force:
            return
        self.bridge.show_toast(message, toast_type, duration, icon, variant, battery)

    @Slot(object)
    def show_battery_toast(self, event: dict):
        """在 Qt 主线程接收电池事件，沿用队列和休眠期间的通知拦截。"""
        self.show_toast(
            event["message"],
            event["type"],
            event["duration"],
            variant=event["variant"],
            battery=event["battery"],
        )

    @Slot(str)
    def show_system_notification(self, title: str):
        """系统消息仅显示标题，不转发正文；仍受休眠开关和前端队列约束。"""
        self.show_toast(title.strip() or "你收到一条新消息", "系统通知", 4500)

    def set_sleeping(self, sleeping: bool):
        """设置休眠状态；休眠期间普通 toast 请求会被忽略。"""
        self._sleeping = sleeping

    def set_toast_suppressed(self, reason: str, suppressed: bool):
        """按原因抑制 Toast，多个功能可以互不覆盖地同时占用。"""
        if suppressed:
            self._toast_suppression.add(reason)
        else:
            self._toast_suppression.discard(reason)

    def clear_toasts(self):
        """清空前端队列与正在播放的动画，不在唤醒后补弹休眠前的通知。"""
        self.bridge.clearRequested.emit()

    def suspend_display(self):
        """隐藏窗口并冻结网页计时器；保留托盘和电源模式通知用于唤醒。"""
        self.hide()
        if self.view is not None:
            from PySide6.QtWebEngineCore import QWebEnginePage

            page = self.view.page()
            page.setVisible(False)
            page.setLifecycleState(QWebEnginePage.LifecycleState.Frozen)

    def resume_display(self):
        """先解冻再显示页面，避免重新加载前端及丢失 WebChannel 连接。"""
        if self.view is not None:
            from PySide6.QtWebEngineCore import QWebEnginePage

            page = self.view.page()
            page.setLifecycleState(QWebEnginePage.LifecycleState.Active)
            page.setVisible(True)
        self.show()


def _show_bluetooth_toast(window: ToastWindow, device_name: str):
    """将新连接的蓝牙设备转换为带类型的 toast。"""
    window.show_toast(f"已连接到 {device_name}", "蓝牙设备", 4000)


def _show_network_toast(window: ToastWindow, network_name: str, network_kind: str):
    """将网络连接事件转换为网络类型 toast。"""
    message = f"已连接到{network_name}" if network_kind == "wifi" else network_name
    window.show_toast(message, "网络连接", 4000)


def _show_ready_toast(window: ToastWindow):
    """应用前端加载完成后，显示带应用图标的启动提示。"""
    icon_url = QUrl.fromLocalFile(str(ICON_PATH)).toString()
    QTimer.singleShot(
        250,  # 延迟 250ms，让前端入场动画先播完
        lambda: window.show_toast(
            "Pyisland_toast is ready", duration=3500, icon=icon_url
        ),
    )


def main():
    """注册为 pyisland-toast 命令的应用入口。

    整体流程：
    1. 创建 QApplication（不随最后窗口关闭而退出，保持后台常驻）
    2. 创建并显示透明置顶窗口
    3. 延迟初始化 WebEngine，加载前端页面
    4. 建立托盘菜单；监听器统一由 RuntimeController 管理休眠与唤醒
    5. 退出时清理托盘、监听器和异步任务
    """
    configure_logging()
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    app.setApplicationName("Pyisland_toast")
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    app.setQuitOnLastWindowClosed(False)

    # qasync 让 Windows 权限申请在 UI 线程异步执行，不另起嵌套事件循环。
    from qasync import QEventLoop

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    from pyisland_toast.tray import RuntimeController, SystemTray, send_startup_notification

    # 原生启动通知先于 WebEngine 初始化调度，库加载和发送不占用 Qt 主线程。
    startup_task = loop.create_task(asyncio.to_thread(send_startup_notification, ICON_PATH))

    window = ToastWindow()
    window.show()

    # 前端页面加载完成后，弹出 "ready" 启动提示
    window.frontendReady.connect(
        lambda loaded: _show_ready_toast(window) if loaded else None
    )

    # 用 singleShot(0) 把 WebEngine 初始化推迟到下一个事件循环迭代，
    # 让窗口先完成 show()，避免阻塞首帧。
    QTimer.singleShot(0, window.init_webengine)

    # ---- 蓝牙设备监听器 ----
    from pyisland_toast.method.bluetooth_watcher import BluetoothDeviceWatcher
    from pyisland_toast.method.network_watcher import NetworkWatcher

    watcher = BluetoothDeviceWatcher(parent=app)
    watcher.deviceConnected.connect(lambda name: _show_bluetooth_toast(window, name))

    # ---- 网络连接监听器 ----
    network_watcher = NetworkWatcher(parent=app)
    network_watcher.networkConnected.connect(
        lambda name, kind: _show_network_toast(window, name, kind)
    )

    # 电池消息通过显式排队连接交给主线程，避免后台线程直接操作窗口。
    from pyisland_toast.method.battery_watcher import BatteryWatcher

    battery_watcher = BatteryWatcher(parent=app)
    battery_watcher.notificationRequested.connect(
        window.show_battery_toast, Qt.QueuedConnection
    )

    from pyisland_toast.method.notification_watcher import NotificationWatcher

    notification_watcher = NotificationWatcher(parent=app)
    notification_watcher.titleReceived.connect(window.show_system_notification)

    controller = RuntimeController(
        window, (watcher, network_watcher, battery_watcher), notification_watcher, parent=app
    )
    tray = SystemTray(app, controller, ICON_PATH)

    from pyisland_toast.ai_ui import AiWindowController
    from pyisland_toast.ai_client import load_settings
    from pyisland_toast.settings_ui import SettingsController
    from pyisland_toast.win32_hotkey import GlobalHotkeyWindow

    ai_controller = AiWindowController(window, FRONTEND_DIR, parent=app)
    settings_controller = SettingsController(
        FRONTEND_DIR,
        lambda: ai_controller.apply_settings(load_settings()),
        parent=app,
    )
    tray.settings_action.triggered.connect(settings_controller.show)
    tray.show()

    controller.stateChanged.connect(ai_controller.set_runtime_sleep)
    hotkey = GlobalHotkeyWindow()
    hotkey.activated.connect(ai_controller.toggle_input)

    async def activate_monitors():
        # 启动通知进入通知中心后再建基线，避免把自己的启动通知转发一遍。
        await asyncio.shield(startup_task)
        await asyncio.sleep(0.5)
        controller.frontend_ready(True)

    activation_task = None

    def on_frontend_loaded(loaded):
        nonlocal activation_task
        if loaded and activation_task is None:
            activation_task = loop.create_task(activate_monitors())

    window.frontendReady.connect(on_frontend_loaded)

    # ---- 高负载监听器 ----
    from pyisland_toast.method.high_load_watcher import HighLoadWatcher

    high_load_watcher = HighLoadWatcher(parent=app)

    high_load_watcher.highLoadEntered.connect(controller.enter_game, Qt.QueuedConnection)
    high_load_watcher.highLoadExited.connect(controller.exit_game, Qt.QueuedConnection)
    high_load_watcher.start()

    # 应用退出时确保所有后台线程停止
    app.aboutToQuit.connect(controller.stop)
    app.aboutToQuit.connect(high_load_watcher.stop)
    app.aboutToQuit.connect(hotkey.close)
    app.aboutToQuit.connect(ai_controller.close)
    app.aboutToQuit.connect(settings_controller.close)

    async def finish_shutdown():
        if activation_task is not None:
            activation_task.cancel()
            await asyncio.gather(activation_task, return_exceptions=True)
        await notification_watcher.aclose()
        await asyncio.gather(startup_task, return_exceptions=True)

    with loop:
        try:
            exit_code = loop.run_forever()
        finally:
            controller.stop()
            tray.close()
            loop.run_until_complete(finish_shutdown())
    asyncio.set_event_loop(None)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
