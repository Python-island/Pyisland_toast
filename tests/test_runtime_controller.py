"""休眠状态组合与启动通知参数测试，不发送真实系统通知。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QImage

from pyisland_toast.app import ICON_PATH
from pyisland_toast.tray import RuntimeController, send_startup_notification


class RuntimeControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.window = MagicMock()
        self.watchers = [MagicMock() for _ in range(3)]
        self.notices = MagicMock()
        self.controller = RuntimeController(self.window, self.watchers, self.notices)

    def tearDown(self):
        self.controller.stop()

    def test_ready_once_and_manual_sleep_resume(self):
        self.controller.frontend_ready(False)
        self.notices.start.assert_not_called()
        self.controller.frontend_ready(True)
        self.controller.frontend_ready(True)
        self.notices.start.assert_called_once()
        self.controller.toggle_manual_sleep()
        self.assertTrue(self.controller.sleeping)
        self.window.set_sleeping.assert_called_with(True)
        self.window.suspend_display.assert_called_once()
        self.notices.pause.assert_called_once()
        for watcher in self.watchers:
            watcher.stop.assert_called_once()
        self.controller.toggle_manual_sleep()
        self.assertFalse(self.controller.sleeping)
        self.window.resume_display.assert_called_once()
        self.window.set_sleeping.assert_called_with(False)
        self.assertEqual(self.notices.start.call_count, 2)

    def test_manual_sleep_survives_game_exit(self):
        self.controller.frontend_ready(True)
        self.controller.toggle_manual_sleep()
        self.controller.enter_game()
        self.controller.exit_game()
        self.assertTrue(self.controller.sleeping)
        self.window.resume_display.assert_not_called()
        self.controller.toggle_manual_sleep()
        self.assertFalse(self.controller.sleeping)

    def test_cancel_manual_does_not_override_game(self):
        self.controller.frontend_ready(True)
        self.controller.enter_game()
        self.controller.toggle_manual_sleep()
        self.controller.toggle_manual_sleep()
        self.assertTrue(self.controller.sleeping)
        self.window.resume_display.assert_not_called()
        self.controller.exit_game()
        self.window.resume_display.assert_called_once()

    def test_game_hint_and_cancel_delayed_hide(self):
        self.controller.frontend_ready(True)
        self.controller.enter_game()
        self.assertTrue(self.controller._hidden_timer.isActive())
        self.window.show_toast.assert_called_with(
            '系统处于高负载状态，Pyisland_toast将休眠', '系统高负载', 6500, force=True
        )
        self.controller.exit_game()
        self.assertFalse(self.controller._hidden_timer.isActive())
        self.controller._hide_if_sleeping()
        self.window.suspend_display.assert_not_called()

    def test_sleep_before_ready_does_not_start_watchers(self):
        self.controller.toggle_manual_sleep()
        self.controller.frontend_ready(True)
        self.notices.start.assert_not_called()
        self.controller.toggle_manual_sleep()
        self.notices.start.assert_called_once()

    def test_shutdown_is_idempotent(self):
        self.controller.frontend_ready(True)
        self.controller.stop()
        self.controller.stop()
        self.notices.stop.assert_called_once()
        self.controller.toggle_manual_sleep()
        self.assertEqual(self.notices.start.call_count, 1)

    def test_startup_title_and_icon_from_ico(self):
        with tempfile.TemporaryDirectory() as cache:
            with patch('pyisland_toast.tray.QStandardPaths.writableLocation', return_value=cache):
                with patch('win11toast.notify') as notify:
                    send_startup_notification(ICON_PATH)
                    notify.assert_called_once()
                    kwargs = notify.call_args.kwargs
                    self.assertEqual(kwargs['title'], 'Pyisland正在启动')
                    self.assertEqual(kwargs['icon']['placement'], 'appLogoOverride')
                    self.assertEqual(kwargs['icon']['src'], (Path(cache) / 'startup-logo.png').resolve().as_uri())
                    image = QImage(str(Path(cache) / 'startup-logo.png'))
                    self.assertFalse(image.isNull())
                    self.assertLessEqual(image.width(), 128)

    def test_startup_failure_does_not_crash(self):
        with patch('win11toast.notify') as notify:
            with self.assertLogs('pyisland_toast.tray', level='WARNING'):
                result = send_startup_notification(Path('missing-logo.ico'))
            self.assertIsNone(result)
            notify.assert_not_called()


if __name__ == '__main__':
    unittest.main()
