"""设置窗口桥接测试，不打开网页，也不写真实配置。"""

import unittest

from PySide6.QtCore import QCoreApplication

from pyisland_toast.settings_ui import SettingsBridge


class _Host:
    def __init__(self):
        self._x = 10
        self._y = 20

    def x(self):
        return self._x

    def y(self):
        return self._y

    def move(self, x, y):
        self._x = x
        self._y = y


class SettingsBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_drag_moves_attached_window(self):
        bridge = SettingsBridge()
        host = _Host()
        bridge.attach(host)
        bridge.dragBy(6, -4)
        self.assertEqual((host.x(), host.y()), (16, 16))

    def test_drag_without_window_is_ignored(self):
        SettingsBridge().dragBy(1, 1)


if __name__ == "__main__":
    unittest.main()
