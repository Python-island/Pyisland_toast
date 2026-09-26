"""系统托盘、手动休眠及启动时的 Windows 原生通知。"""

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, QTimer, Signal, Slot, Qt
from PySide6.QtGui import QIcon, QImage
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

logger = logging.getLogger(__name__)
STARTUP_TITLE = "Pyisland正在启动"


def send_startup_notification(icon_path: Path):
    """用同一 ICO 生成通知图片；notify 发送即返回，不等待用户关闭。"""
    try:
        from win11toast import notify

        # 原生通知图片使用 PNG，托盘仍直接使用 ICO；不修改项目中的原图。
        image = QImage(str(icon_path))
        if image.isNull():
            raise ValueError(f"无法读取应用图标：{icon_path}")
        cache = Path(QStandardPaths.writableLocation(QStandardPaths.CacheLocation))
        cache.mkdir(parents=True, exist_ok=True)
        png = cache / "startup-logo.png"
        if not image.scaled(128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation).save(str(png), "PNG"):
            raise OSError("无法写入启动通知图标缓存")
        return notify(
            title=STARTUP_TITLE,
            icon={"src": png.resolve().as_uri(), "placement": "appLogoOverride"},
            duration="short",
            tag="pyisland-startup",
            group="pyisland",
        )
    except Exception:
        # 系统关闭通知或图标不可读时，不影响托盘和主程序启动。
        logger.warning("发送启动通知失败，应用将继续启动。", exc_info=True)
        return None


class RuntimeController(QObject):
    """统一手动/游戏两种休眠原因；任一原因存在时都不恢复普通通知。"""

    stateChanged = Signal(bool, bool)  # 手动休眠、游戏模式

    def __init__(self, window, watchers, notification_watcher, parent=None):
        super().__init__(parent)
        self.window = window
        self.watchers = tuple(watchers)
        self.notification_watcher = notification_watcher
        self.manual_sleep = False
        self.game_sleep = False
        self._ready = False
        self._closed = False
        self._hidden_timer = QTimer(self)
        self._hidden_timer.setSingleShot(True)
        self._hidden_timer.timeout.connect(self._hide_if_sleeping)

    @property
    def sleeping(self):
        return self.manual_sleep or self.game_sleep

    @Slot(bool)
    def frontend_ready(self, loaded):
        """前端就绪前不启动采集，避免丢失首条事件。"""
        if not loaded or self._ready or self._closed:
            return
        self._ready = True
        if not self.sleeping:
            self._resume_watchers()
        else:
            self._hide_if_sleeping()

    def _resume_watchers(self):
        if self._ready and not self._closed:
            for watcher in self.watchers:
                watcher.start()
            self.notification_watcher.start()

    @Slot()
    def toggle_manual_sleep(self):
        self._set_reason(manual=not self.manual_sleep)

    @Slot()
    def enter_game(self):
        self._set_reason(game=True)

    @Slot()
    def exit_game(self):
        self._set_reason(game=False)

    def _set_reason(self, *, manual=None, game=None):
        if self._closed:
            return
        was_sleeping = self.sleeping
        if manual is not None:
            self.manual_sleep = manual
        if game is not None:
            self.game_sleep = game
        sleeping = self.sleeping
        self.stateChanged.emit(self.manual_sleep, self.game_sleep)

        if sleeping and not was_sleeping:
            self.window.set_sleeping(True)
            self.window.clear_toasts()
            self.notification_watcher.pause()
            # 手动休眠立即隐藏；游戏模式保留一次 Rocket 提醒后隐藏。
            if self.manual_sleep or not self._ready:
                self._hide_if_sleeping()
            else:
                self.window.show_toast(
                    "系统处于高负载状态，Pyisland_toast将休眠", "系统高负载", 6500, force=True
                )
                self._hidden_timer.start(7100)
            for watcher in self.watchers:
                watcher.stop()
        elif not sleeping and was_sleeping:
            self._hidden_timer.stop()
            self.window.resume_display()
            self.window.set_sleeping(False)
            self._resume_watchers()
            if self._ready:
                self.window.show_toast("Pyisland_toast已唤醒", "系统高负载", 4000, force=True)
        elif sleeping and self.manual_sleep:
            self._hidden_timer.stop()
            self._hide_if_sleeping()

    def _hide_if_sleeping(self):
        if self.sleeping and not self._closed:
            self.window.clear_toasts()
            self.window.suspend_display()

    @Slot()
    def stop(self):
        """退出时阻止重启、停止监听；异步通知任务由主入口等待清理。"""
        if self._closed:
            return
        self._closed = True
        self._hidden_timer.stop()
        self.window.set_sleeping(True)
        self.window.clear_toasts()
        self.window.hide()
        self.notification_watcher.stop()
        for watcher in self.watchers:
            watcher.stop()


class SystemTray(QObject):
    """持有托盘和菜单的强引用，退出前显式隐藏托盘。"""

    def __init__(self, app, controller, icon_path: Path, on_settings=None):
        super().__init__(app)
        self.controller = controller
        self.menu = QMenu()
        self.sleep_action = self.menu.addAction("休眠")
        self.settings_action = self.menu.addAction("设置")
        self.menu.addSeparator()
        self.exit_action = self.menu.addAction("退出")
        self.icon = QSystemTrayIcon(QIcon(str(icon_path)), self)
        self.icon.setContextMenu(self.menu)
        self.sleep_action.triggered.connect(controller.toggle_manual_sleep)
        self.exit_action.triggered.connect(app.quit)
        if on_settings is not None:
            self.settings_action.triggered.connect(on_settings)
        controller.stateChanged.connect(self.update_state)
        app.aboutToQuit.connect(self.close)
        self.update_state(controller.manual_sleep, controller.game_sleep)

    def show(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning("当前系统托盘暂不可用。")
        self.icon.show()

    @Slot(bool, bool)
    def update_state(self, manual, game):
        self.sleep_action.setText("唤醒" if manual else "休眠")
        status = "手动休眠" if manual else "游戏模式休眠" if game else "运行中"
        self.icon.setToolTip(f"Pyisland_toast · {status}")

    @Slot()
    def close(self):
        self.icon.hide()
        self.menu.close()
