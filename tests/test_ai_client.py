"""模型配置和 chat/completions 请求测试，不访问网络。"""

import io
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from pyisland_toast.ai_client import AiSettings, chat_url, complete_chat, load_settings, run_agent_turn


class SettingsTests(unittest.TestCase):
    def test_missing_file_is_disabled(self):
        settings = load_settings(self._missing())
        self.assertFalse(settings.configured)

    def test_key_is_hidden_from_repr(self):
        settings = AiSettings(enabled=True, base_url="https://example.test", api_key="secret-key-value", model="demo")
        self.assertNotIn("secret-key-value", repr(settings))
        self.assertTrue(settings.configured)

    def _missing(self):
        from pathlib import Path
        return Path("this-file-does-not-exist-ai-config.json")


class CompletionTests(unittest.TestCase):
    def test_chat_url_accepts_host_or_v1_base(self):
        self.assertEqual(chat_url("https://api.deepseek.com"), "https://api.deepseek.com/chat/completions")
        self.assertEqual(chat_url("https://api.openai.com/v1"), "https://api.openai.com/v1/chat/completions")
        self.assertEqual(
            chat_url("https://api.openai.com/v1/chat/completions"),
            "https://api.openai.com/v1/chat/completions",
        )

    def test_request_uses_config_and_returns_text(self):
        settings = AiSettings(
            enabled=True,
            base_url="https://api.deepseek.com",
            api_key="secret-key-value",
            model="demo-model",
            system_prompt="短答",
            temperature=0.2,
            max_tokens=32,
            timeout_seconds=5,
        )
        captured = {}

        class Response:
            def read(self):
                return json.dumps({"choices": [{"message": {"content": "你好"}}]}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["auth"] = request.get_header("Authorization")
            captured["body"] = json.loads(request.data.decode())
            return Response()

        with patch("urllib.request.urlopen", urlopen):
            text = complete_chat(settings, [{"role": "user", "content": "在吗"}])
        self.assertEqual(text, "你好")
        self.assertEqual(captured["url"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(captured["timeout"], 5)
        self.assertEqual(captured["auth"], "Bearer secret-key-value")
        self.assertEqual(captured["body"]["model"], "demo-model")
        self.assertEqual(captured["body"]["messages"][0]["content"], "短答")
        self.assertEqual(captured["body"]["messages"][1]["content"], "在吗")

    def test_http_error_hides_key(self):
        settings = AiSettings(
            enabled=True,
            base_url="https://api.deepseek.com",
            api_key="secret-key-value",
            model="demo-model",
        )
        body = json.dumps({"error": {"message": "bad secret-key-value"}}).encode()

        def urlopen(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 401, "no", {}, io.BytesIO(body))

        with patch("urllib.request.urlopen", urlopen):
            text = complete_chat(settings, [{"role": "user", "content": "你好"}])
        self.assertIn("模型服务拒绝了请求", text)
        self.assertNotIn("secret-key-value", text)
        self.assertIn("***", text)


class AgentTurnTests(unittest.TestCase):
    def test_tool_round_trip_then_answers(self):
        settings = AiSettings(
            enabled=True,
            base_url="https://api.deepseek.com",
            api_key="secret-key-value",
            model="demo-model",
            system_prompt="短答",
        )
        calls = {"n": 0}

        class Response:
            def __init__(self, payload):
                self.payload = payload

            def read(self):
                return json.dumps(self.payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def urlopen(request, timeout):
            body = json.loads(request.data.decode())
            calls["n"] += 1
            if calls["n"] == 1:
                self.assertIn("tools", body)
                self.assertIn("Windows", body["messages"][0]["content"])
                payload = {
                    "choices": [{
                        "message": {
                            "content": "",
                            "tool_calls": [{
                                "id": "c1",
                                "type": "function",
                                "function": {"name": "Echo", "arguments": json.dumps({"text": "hi"})},
                            }],
                        }
                    }]
                }
            else:
                self.assertEqual(body["messages"][-1]["role"], "tool")
                self.assertEqual(body["messages"][-1]["content"], "pong:hi")
                payload = {"choices": [{"message": {"content": "完成"}}]}
            return Response(payload)

        class Session:
            error = ""

            def ensure_started(self):
                return True

            def openai_tools(self):
                return [{
                    "type": "function",
                    "function": {"name": "Echo", "description": "echo", "parameters": {"type": "object", "properties": {}}},
                }]

            def call_tool(self, name, arguments):
                self.last = (name, arguments)
                return "pong:" + arguments["text"]

        progress = []
        with patch("urllib.request.urlopen", urlopen):
            text = run_agent_turn(
                settings,
                [{"role": "user", "content": "做一下"}],
                Session(),
                on_progress=progress.append,
            )
        self.assertEqual(text, "完成")
        self.assertEqual(progress, ["正在执行 Echo…"])
        self.assertEqual(calls["n"], 2)


    def test_screenshot_is_hidden_from_the_model(self):
        settings = AiSettings(
            enabled=True,
            base_url="https://api.deepseek.com",
            api_key="secret-key-value",
            model="demo-model",
        )
        state = {"n": 0, "called": []}

        class Response:
            def __init__(self, payload):
                self.payload = payload

            def read(self):
                return json.dumps(self.payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def urlopen(request, timeout):
            body = json.loads(request.data.decode())
            state["n"] += 1
            if state["n"] == 1:
                names = [tool["function"]["name"] for tool in body["tools"]]
                self.assertEqual(names, ["Snapshot"])
                self.assertNotIn("Screenshot", body["messages"][0]["content"])
                self.assertIn("Snapshot", body["messages"][0]["content"])
                call = {"id": "c1", "type": "function", "function": {"name": "Screenshot", "arguments": "{}"}}
                return Response({"choices": [{"message": {"content": "", "tool_calls": [call]}}]})
            self.assertNotIn("image_url", request.data.decode())
            return Response({"choices": [{"message": {"content": "已用文字界面继续。"}}]})

        class Session:
            error = ""

            def ensure_started(self):
                return True

            def openai_tools(self):
                shot = {"type": "function", "function": {"name": "Screenshot", "description": "shot", "parameters": {"type": "object", "properties": {}}}}
                tree = {"type": "function", "function": {"name": "Snapshot", "description": "tree", "parameters": {"type": "object", "properties": {}}}}
                return [shot, tree]

            def call_tool(self, name, arguments):
                state["called"].append(name)
                return "should-not-run"

        with patch("urllib.request.urlopen", urlopen):
            text = run_agent_turn(settings, [{"role": "user", "content": "看看屏幕"}], Session())
        self.assertEqual(text, "已用文字界面继续。")
        self.assertEqual(state["called"], [])
        self.assertEqual(state["n"], 2)

    def test_step_budget_is_fifty(self):
        from pyisland_toast.ai_client import MAX_TOOL_STEPS
        self.assertEqual(MAX_TOOL_STEPS, 50)

    def test_step_limit_returns_summary(self):
        settings = AiSettings(
            enabled=True,
            base_url="https://api.deepseek.com",
            api_key="secret-key-value",
            model="demo-model",
        )
        calls = {"n": 0, "tool": 0}

        class Response:
            def __init__(self, payload):
                self.payload = payload

            def read(self):
                return json.dumps(self.payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def urlopen(request, timeout):
            body = json.loads(request.data.decode())
            calls["n"] += 1
            if "tools" in body:
                return Response({"choices": [{"message": {"content": "", "tool_calls": [{
                    "id": "c" + str(calls["n"]),
                    "type": "function",
                    "function": {"name": "Snapshot", "arguments": "{}"},
                }]}}]})
            self.assertIn("操作步数已经用完", body["messages"][-1]["content"])
            self.assertNotIn("tools", body)
            return Response({"choices": [{"message": {"content": "已经打开记事本。"}}]})

        class Session:
            error = ""

            def ensure_started(self):
                return True

            def openai_tools(self):
                return [{"type": "function", "function": {"name": "Snapshot", "description": "tree", "parameters": {"type": "object", "properties": {}}}}]

            def call_tool(self, name, arguments):
                calls["tool"] += 1
                return "界面：记事本"

        with patch("pyisland_toast.ai_client.MAX_TOOL_STEPS", 3), patch("urllib.request.urlopen", urlopen):
            text = run_agent_turn(settings, [{"role": "user", "content": "打开记事本"}], Session())
        self.assertEqual(text, "已经打开记事本。")
        self.assertEqual(calls["tool"], 2)
        self.assertNotIn("上限", text)


class SettingsFileTests(unittest.TestCase):
    def test_save_preserves_other_fields_and_reloads(self):
        from pyisland_toast.ai_client import form_settings, save_settings

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ai_config.json"
            path.write_text(json.dumps({
                "enabled": False,
                "api_key": "old-secret",
                "windows_mcp_exclude_tools": "Registry,Process,Screenshot",
                "extra_headers": {"X-Test": "1"},
                "custom": 1,
            }), encoding="utf-8")
            save_settings({
                "enabled": True,
                "base_url": "https://api.deepseek.com",
                "api_key": "new-secret",
                "model": "demo",
                "system_prompt": "短答",
                "temperature": 0.2,
                "top_p": 0.9,
                "max_tokens": 128,
                "timeout_seconds": 15,
            }, path)
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["api_key"], "new-secret")
            self.assertEqual(raw["windows_mcp_exclude_tools"], "Registry,Process,Screenshot")
            self.assertEqual(raw["windows_mcp_command"], "")
            self.assertEqual(raw["extra_headers"], {"X-Test": "1"})
            self.assertEqual(raw["custom"], 1)
            self.assertEqual(raw["provider"], "openai-compatible")
            settings = load_settings(path)
            self.assertTrue(settings.configured)
            self.assertEqual(settings.model, "demo")
            self.assertNotIn("new-secret", repr(settings))
            self.assertEqual(form_settings(path)["api_key"], "new-secret")

    def test_invalid_temperature_does_not_write(self):
        from pyisland_toast.ai_client import save_settings

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ai_config.json"
            with self.assertRaises(ValueError) as caught:
                save_settings({"temperature": 9, "api_key": "secret-key-value"}, path)
            self.assertFalse(path.exists())
            self.assertNotIn("secret-key-value", str(caught.exception))

    def test_missing_file_form_does_not_create_it(self):
        from pyisland_toast.ai_client import form_settings

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ai_config.json"
            form = form_settings(path)
            self.assertEqual(form["base_url"], "https://api.deepseek.com")
            self.assertEqual(form["api_key"], "")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
