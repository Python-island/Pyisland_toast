"""Windows-MCP 子进程握手测试。使用假的 stdio 服务，不启动真实桌面控制。"""

import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pyisland_toast.windows_mcp_session import WindowsMcpSession, resolve_command


FAKE_SERVER = r"""
import json
import sys

for line in sys.stdin:
    text = line.strip()
    if not text:
        continue
    message = json.loads(text)
    if message.get("method") == "notifications/initialized":
        continue
    method = message.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "fake", "version": "0"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "Echo", "description": "echo", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}}]}
    elif method == "tools/call":
        arguments = message.get("params", {}).get("arguments") or {}
        result = {"content": [{"type": "text", "text": "ok:" + str(arguments.get("text", ""))}], "isError": False}
    else:
        result = {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": message.get("id"), "result": result}) + "\n")
    sys.stdout.flush()
"""


class ResolveCommandTests(unittest.TestCase):
    def test_explicit_command_is_kept(self):
        command = resolve_command(r"C:\Tools\windows-mcp.exe serve --transport stdio", "Registry,Process")
        self.assertEqual(command[0], r"C:\Tools\windows-mcp.exe")
        self.assertIn("serve", command)

    def test_auto_command_excludes_risky_tools(self):
        def which(name):
            if name == "windows-mcp":
                return r"C:\Tools\windows-mcp.exe"
            return None

        with patch("pyisland_toast.windows_mcp_session.shutil.which", side_effect=which), patch(
            "pyisland_toast.windows_mcp_session._is_file", return_value=True
        ):
            command = resolve_command("", "Registry,Process")
        self.assertEqual(command[0], r"C:\Tools\windows-mcp.exe")
        self.assertEqual(command[1:3], ["serve", "--transport"])
        self.assertIn("--exclude-tools", command)
        self.assertIn("Registry,Process,Screenshot", command)

    def test_missing_install_reports_error(self):
        with patch("pyisland_toast.windows_mcp_session.shutil.which", return_value=None), patch(
            "pyisland_toast.windows_mcp_session._is_file", return_value=False
        ):
            session = WindowsMcpSession()
            self.assertFalse(session.ensure_started())
        self.assertIn("找不到 windows-mcp", session.error)


class HandshakeTests(unittest.TestCase):
    def test_session_lists_and_calls_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "fake_mcp.py"
            script.write_text(FAKE_SERVER, encoding="utf-8")
            session = WindowsMcpSession('"' + sys.executable + '" "' + str(script) + '"', "")
            self.addCleanup(session.close)
            self.assertTrue(session.ensure_started(), session.error)
            self.assertEqual([tool["function"]["name"] for tool in session.openai_tools()], ["Echo"])
            self.assertEqual(session.call_tool("Echo", {"text": "hi"}), "ok:hi")


class DisabledScreenshotTests(unittest.TestCase):
    def test_screenshot_is_not_offered(self):
        session = WindowsMcpSession()
        session._tools = [
            {"name": "Screenshot", "description": "shot", "inputSchema": {"type": "object"}},
            {"name": "Snapshot", "description": "tree", "inputSchema": {"type": "object"}},
        ]
        names = [tool["function"]["name"] for tool in session.openai_tools()]
        self.assertEqual(names, ["Snapshot"])
        self.assertEqual(session._exclude, "Registry,Process,Screenshot")

    def test_image_content_is_not_forwarded(self):
        from pyisland_toast.windows_mcp_session import _tool_text
        text = _tool_text({"content": [
            {"type": "text", "text": "画面说明"},
            {"type": "image", "data": "AAAA", "mimeType": "image/png"},
        ]})
        self.assertIn("画面说明", text)
        self.assertIn("截图已禁用", text)
        self.assertNotIn("AAAA", text)


if __name__ == "__main__":
    unittest.main()
