"""电池状态与通知逻辑测试，不修改实际电源状态。"""

import ctypes
import json
import threading
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, Qt

from pyisland_toast.app import ToastBridge
from pyisland_toast.method import battery_watcher as battery


class BatteryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.watcher = battery.BatteryWatcher()

    def test_baseline_and_plug_changes(self):
        self.assertEqual(self.watcher._notifications(battery.BatteryStatus(True, True, 80, False)), [])
        events = self.watcher._notifications(battery.BatteryStatus(False, True, 79, False))
        self.assertEqual([event['message'] for event in events], ['电源已断开'])
        self.assertEqual(self.watcher._notifications(battery.BatteryStatus(False, True, 78, False)), [])
        events = self.watcher._notifications(battery.BatteryStatus(True, True, 78, True))
        self.assertEqual(events[0]['message'], '电源已连接')
        self.assertEqual(events[0]['variant'], 'charging')
        self.assertEqual(events[0]['battery'], {'percent': 78, 'charging': True})

    def test_low_battery_once_and_rearm(self):
        events = self.watcher._notifications(battery.BatteryStatus(False, True, 20, False))
        self.assertEqual(events[0]['message'], '电池电量仅剩20%')
        for percent in (19, 21, 20, 10, 0):
            self.assertEqual(self.watcher._notifications(battery.BatteryStatus(False, True, percent, False)), [])
        self.watcher._notifications(battery.BatteryStatus(False, True, 26, False))
        self.assertEqual(len(self.watcher._notifications(battery.BatteryStatus(False, True, 20, False))), 1)
        self.watcher._notifications(battery.BatteryStatus(True, True, 19, False))
        events = self.watcher._notifications(battery.BatteryStatus(False, True, 18, False))
        self.assertEqual([event['type'] for event in events], ['电源已断开', '电量不足'])

    def test_unknown_state_preserves_baseline(self):
        self.watcher._notifications(battery.BatteryStatus(True, True, 50, False))
        for state in (
            battery.BatteryStatus(None, True, 10, False),
            battery.BatteryStatus(False, None, None, False),
        ):
            self.assertEqual(self.watcher._notifications(state), [])
        self.assertEqual(self.watcher._previous_ac, True)
        events = self.watcher._notifications(battery.BatteryStatus(False, True, None, False))
        self.assertEqual([event['type'] for event in events], ['电源已断开'])

    def test_no_battery_has_no_notifications(self):
        for ac in (True, False, True):
            self.assertEqual(self.watcher._notifications(battery.BatteryStatus(ac, False, None, False)), [])

    def test_api_byte_flags_and_unknown_values(self):
        self.assertEqual(ctypes.sizeof(battery.SystemPowerStatus), 12)

        def read(ac, flag, percent):
            def fill(pointer):
                status = ctypes.cast(pointer, ctypes.POINTER(battery.SystemPowerStatus)).contents
                status.ACLineStatus = ac
                status.BatteryFlag = flag
                status.BatteryLifePercent = percent
                return 1
            with patch.object(battery.kernel32, 'GetSystemPowerStatus', side_effect=fill):
                return battery.get_battery_status()

        self.assertEqual(read(255, 255, 255), battery.BatteryStatus(None, None, None, False))
        self.assertEqual(read(1, 128, 255), battery.BatteryStatus(True, False, None, False))
        self.assertEqual(read(1, 8, 45), battery.BatteryStatus(True, True, 45, True))
        self.assertEqual(read(0, 4, 0).percent, 0)
        self.assertEqual(read(1, 1, 100).percent, 100)

    def test_api_failure_raises(self):
        with patch.object(battery.kernel32, 'GetSystemPowerStatus', return_value=0):
            with self.assertRaises(OSError):
                battery.get_battery_status()

    def test_background_loop_retries_and_stops(self):
        watcher = battery.BatteryWatcher(interval=0.01)
        received = []
        ready = threading.Event()

        def receive(event):
            received.append(event)
            ready.set()

        watcher.notificationRequested.connect(receive, Qt.DirectConnection)
        states = iter([
            OSError('模拟查询失败'),
            battery.BatteryStatus(True, True, 60, False),
            battery.BatteryStatus(False, True, 60, False),
        ])

        def query():
            result = next(states, battery.BatteryStatus(False, True, 60, False))
            if isinstance(result, Exception):
                raise result
            return result

        with patch.object(battery, 'get_battery_status', side_effect=query):
            with self.assertLogs(battery.logger, level='ERROR'):
                watcher.start()
                try:
                    worker = watcher._thread
                    watcher.start()
                    self.assertIs(watcher._thread, worker)
                    self.assertTrue(ready.wait(2), '后台线程没有发出断电通知')
                finally:
                    watcher.stop()
        self.assertFalse(worker.is_alive())
        self.assertEqual([item['type'] for item in received], ['电源已断开'])

    def test_bridge_payload_and_legacy_defaults(self):
        bridge = ToastBridge()
        events = []
        bridge.toastRequested.connect(lambda payload: events.append(json.loads(payload)))
        bridge.show_toast('电源已连接', '电源已连接', 4500, '', 'charging', {'percent': 45})
        self.assertEqual(events[0]['battery']['percent'], 45)
        self.assertEqual(events[0]['variant'], 'charging')
        bridge.show_toast('普通提示')
        self.assertIsNone(events[1]['battery'])
        self.assertEqual(events[1]['variant'], 'default')

    def test_invalid_interval(self):
        for value in (0, -1):
            with self.assertRaises(ValueError):
                battery.BatteryWatcher(interval=value)


if __name__ == '__main__':
    unittest.main()
