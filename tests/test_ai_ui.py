"""AI 桥接和侧边栏控制测试，不调用外部模型。"""

import json
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QCoreApplication, QRect

from pyisland_toast.ai_ui import AiBridge, AiWindowController, panel_frame


class AiBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_prompt_trim_and_empty_rejection(self):
        bridge = AiBridge()
        prompts = []
        bridge.submitRequested.connect(prompts.append)
        bridge.submitPrompt("  hello  ")
        bridge.submitPrompt("   ")
        self.assertEqual(prompts, ["hello"])

    def test_conversation_cache(self):
        bridge = AiBridge()
        events = []
        bridge.conversationUpdated.connect(events.append)
        bridge.set_conversation('[{"role":"user"}]')
        self.assertEqual(bridge.getConversation(), events[0])


class AiControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.toast = MagicMock()
        self.controller = AiWindowController.__new__(AiWindowController)
        self.controller.toast_window = self.toast
        self.controller.bridge = AiBridge()
        self.controller.panel = MagicMock()
        self.controller.enabled = True
        self.controller._closed = False
        self.controller.messages = []
        self.controller._open = False
        self.controller._idle_timer = MagicMock()
        self.controller._reclaim_timer = MagicMock()
        self.controller.frontend_dir = MagicMock()

    def test_open_does_not_suppress_toast(self):
        self.controller.toggle_input()
        self.controller.panel.show_animated.assert_called_once()
        self.toast.show_toast.assert_called_once_with("侧边栏AI已启动", "侧边栏AI", 4000)
        self.controller.toggle_input()
        self.toast.show_toast.assert_called_once_with("侧边栏AI已启动", "侧边栏AI", 4000)
        self.toast.set_toast_suppressed.assert_not_called()
        self.toast.clear_toasts.assert_not_called()

    def test_submit_keeps_panel_and_reply(self):
        self.controller.submit("隐私测试内容")
        self.controller.panel.show_animated.assert_called_once()
        self.controller.panel.animate_hide.assert_not_called()
        payload = json.loads(self.controller.bridge.getConversation())
        self.assertEqual(payload[0], {"role": "user", "content": "隐私测试内容"})
        self.assertIn("尚未配置", payload[1]["content"])
        self.toast.show_toast.assert_called_once_with("侧边栏AI已启动", "侧边栏AI", 4000)
        self.controller.submit("再问一次")
        self.toast.show_toast.assert_called_once_with("侧边栏AI已启动", "侧边栏AI", 4000)
        self.toast.set_toast_suppressed.assert_not_called()
        self.toast.clear_toasts.assert_not_called()

    def test_close_hides_panel_without_touching_toasts(self):
        self.controller._open = True
        self.controller._turn = 2
        self.controller.messages = [
            {"role": "user", "content": "旧问题"},
            {"id": 1, "role": "assistant", "content": "正在思考…", "pending": True},
        ]
        self.controller.close_panel()
        self.assertFalse(self.controller.active)
        self.controller.panel.animate_hide.assert_called_once()
        self.toast.set_toast_suppressed.assert_not_called()
        self.assertEqual(json.loads(self.controller.bridge.getConversation()), [])
        self.controller._apply_reply(2, 1, "迟到的回复")
        self.assertEqual(self.controller.messages, [])

    def test_runtime_sleep_closes_ai_and_blocks_hotkey(self):
        self.controller._open = True
        self.controller.set_runtime_sleep(True, False)
        self.assertFalse(self.controller.enabled)
        self.controller.panel.animate_hide.assert_called_once()
        self.controller.toggle_input()
        self.controller.panel.show_animated.assert_not_called()
        self.controller.set_runtime_sleep(False, False)
        self.assertTrue(self.controller.enabled)

    def test_idle_timeout_animates_then_reclaims(self):
        self.controller._open = True
        self.controller._reclaim_windows()
        self.assertFalse(self.controller.active)
        self.controller.panel.animate_hide.assert_called_once()
        self.controller._reclaim_timer.start.assert_called_with(500)
        self.toast.set_toast_suppressed.assert_not_called()

    def test_activity_cancels_pending_reclaim(self):
        self.controller._touch()
        self.controller._reclaim_timer.stop.assert_called_once()
        self.controller._idle_timer.start.assert_called_once()


    def test_configured_client_replaces_pending_reply(self):
        class FakeClient:
            def complete(self, history, callback):
                self.history = history
                callback("模型回复")

        fake = FakeClient()
        delivered = []
        self.controller._client = fake
        self.controller._turn = 0
        self.controller._message_seq = 0
        self.controller._deliver = lambda turn, message_id, content: delivered.append((turn, message_id, content))
        self.controller.submit("你好")
        self.assertEqual(fake.history, [{"role": "user", "content": "你好"}])
        self.assertEqual(delivered[0][2], "模型回复")
        payload = json.loads(self.controller.bridge.getConversation())
        self.assertEqual(payload[1]["content"], "正在思考…")
        self.controller._apply_reply(*delivered[0])
        payload = json.loads(self.controller.bridge.getConversation())
        self.assertEqual(payload[1]["content"], "模型回复")
        self.assertNotIn("尚未配置", payload[1]["content"])


    def test_clear_conversation_drops_history_and_late_reply(self):
        self.controller._turn = 3
        self.controller.messages = [
            {"role": "user", "content": "旧问题"},
            {"id": 1, "role": "assistant", "content": "正在思考…", "pending": True},
        ]
        self.controller.clear_conversation()
        self.assertEqual(json.loads(self.controller.bridge.getConversation()), [])
        self.controller._apply_reply(3, 1, "迟到的回复")
        self.assertEqual(self.controller.messages, [])

    def test_panel_frame_uses_screen_resolution(self):
        class Screen:
            def geometry(self):
                return QRect(0, 0, 2000, 1000)

            def availableGeometry(self):
                return QRect(10, 20, 1900, 900)

        width, height, origin = panel_frame(Screen())
        self.assertEqual((width, height), (400, 800))
        self.assertEqual(origin.x(), 10 + 1900 - 1 - 16 - 400 + 1)
        self.assertEqual(origin.y(), 20 + (900 - 800) // 2)

        class Short:
            def geometry(self):
                return QRect(0, 0, 1000, 1000)

            def availableGeometry(self):
                return QRect(0, 0, 1000, 100)

        width, height, origin = panel_frame(Short())
        self.assertEqual(width, 200)
        self.assertEqual(height, 100 - 32)
        self.assertEqual(origin.y(), (100 - height) // 2)



    def test_apply_settings_enables_and_disables_client(self):
        from pyisland_toast.ai_client import AiSettings

        self.controller._closed = False
        self.controller._client = None
        self.controller._mcp = None
        settings = AiSettings(enabled=True, base_url="https://example.test", api_key="k", model="m")
        with patch("pyisland_toast.ai_ui.WindowsMcpSession") as session, patch("pyisland_toast.ai_ui.ChatClient") as client:
            self.controller.apply_settings(settings)
        session.assert_called_once_with("", "Registry,Process,Screenshot")
        client.assert_called_once_with(settings, session.return_value)
        self.assertIs(self.controller._client, client.return_value)
        self.controller.apply_settings(AiSettings())
        self.assertIsNone(self.controller._client)

if __name__ == "__main__":
    unittest.main()
