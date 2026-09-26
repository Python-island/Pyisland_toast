"""从真实入口启动并触发托盘退出；会发送一次真实启动通知。"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer
from pyisland_toast import app as application
from pyisland_toast import tray as tray_module

original_show = tray_module.SystemTray.show
original_notify = tray_module.send_startup_notification
results = {}


def notify(icon_path):
    notification = original_notify(icon_path)
    results['notification_sent'] = notification is not None
    if notification is not None:
        # 仅检查本次测试自己发送的通知，不读取用户其他通知。
        results['title_ok'] = 'Pyisland正在启动' in notification.content.get_xml()
    return notification


def show(tray):
    original_show(tray)
    results['tray'] = tray
    results['tray_visible'] = tray.icon.isVisible()
    QTimer.singleShot(8000, tray.exit_action.trigger)


with patch.object(tray_module.SystemTray, 'show', show):
    with patch.object(tray_module, 'send_startup_notification', notify):
        try:
            application.main()
        except SystemExit as error:
            assert error.code in (None, 0), error.code

assert results.get('tray_visible'), '托盘未显示'
assert results.get('notification_sent'), '启动通知未成功提交给 Windows'
assert results.get('title_ok'), '启动通知标题不正确'
tray = results['tray']
assert not tray.icon.isVisible(), '退出后托盘仍然可见'
assert tray.controller._closed, '退出未停止运行控制器'
assert tray.controller.notification_watcher._task is None, '异步通知任务未清理'
for watcher in tray.controller.watchers:
    worker = watcher._thread
    assert worker is None or not worker.is_alive(), '设备检测线程仍然存活'
print('PASS startup notification, tray exit and listener cleanup', flush=True)
