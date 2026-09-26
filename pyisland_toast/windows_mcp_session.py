"""启动用户已安装的 Windows-MCP，并用 stdio 完成 MCP 握手。"""

from __future__ import annotations

import json
import logging
import os
import queue
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

START_TIMEOUT = 40
TOOL_TIMEOUT = 45
MAX_TOOL_CHARS = 12000


def _split_command(command: str) -> list[str]:
    parts = shlex.split(command, posix=False)
    cleaned = []
    for part in parts:
        if len(part) >= 2 and part[0] == part[-1] and part[0] in {"'", '"'}:
            part = part[1:-1]
        cleaned.append(part)
    return cleaned


def _is_file(path: str) -> bool:
    return bool(path) and Path(path).is_file()


def _exclude_argument(exclude_tools: str) -> str:
    names = []
    seen = set()
    for part in (exclude_tools or "").split(","):
        name = part.strip()
        if not name or name in seen:
            continue
        names.append(name)
        seen.add(name)
    if "Screenshot" not in seen:
        names.append("Screenshot")
    return ",".join(names)


def resolve_command(command: str, exclude_tools: str) -> list[str] | None:
    """空命令时查找 windows-mcp 或 uvx。显式命令按原样使用。"""
    if command.strip():
        return _split_command(command)
    extra = ["serve", "--transport", "stdio", "--exclude-tools", _exclude_argument(exclude_tools)]
    found = shutil.which("windows-mcp")
    if found and _is_file(found):
        return [found, *extra]
    local = Path.home() / ".local" / "bin" / "windows-mcp.exe"
    if _is_file(str(local)):
        return [str(local), *extra]
    for name in ("uvx", "uv"):
        located = shutil.which(name)
        if not located or not _is_file(located):
            continue
        uvx = Path(located)
        if uvx.name.lower() not in {"uvx", "uvx.exe"}:
            sibling = uvx.with_name("uvx.exe")
            if not _is_file(str(sibling)):
                continue
            uvx = sibling
        return [str(uvx), "windows-mcp", *extra]
    return None


class WindowsMcpSession:
    """持有一个由本程序启动的 stdio 子进程。"""

    def __init__(self, command: str = "", exclude_tools: str = "Registry,Process,Screenshot"):
        self._command_text = command
        self._exclude = _exclude_argument(exclude_tools)
        self._lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[int, queue.Queue] = {}
        self._proc: subprocess.Popen | None = None
        self._next_id = 0
        self._tools: list[dict] = []
        self._stderr: list[str] = []
        self._stopped = False
        self.error = ""

    @property
    def ready(self) -> bool:
        proc = self._proc
        return proc is not None and proc.poll() is None and bool(self._tools)

    def ensure_started(self) -> bool:
        with self._lock:
            if self._stopped:
                return False
            if self.ready:
                return True
            self._shutdown_locked()
            command = resolve_command(self._command_text, self._exclude)
            if not command:
                self.error = "找不到 windows-mcp。请先运行 uv tool install windows-mcp。"
                return False
            try:
                self._spawn_locked(command)
                self._handshake_locked()
            except Exception:
                logger.warning("Windows-MCP 启动失败。")
                if self._stderr:
                    logger.warning("Windows-MCP：%s", self._stderr[-1][:300])
                self.error = "Windows-MCP 没有连上。"
                self._shutdown_locked()
                return False
            self.error = ""
            return True

    def openai_tools(self) -> list[dict]:
        tools = []
        for tool in self._tools:
            name = str(tool.get("name") or "")
            if not name or name == "Screenshot":
                continue
            parameters = tool.get("inputSchema")
            if not isinstance(parameters, dict):
                parameters = {"type": "object", "properties": {}}
            tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(tool.get("description") or ""),
                    "parameters": parameters,
                },
            })
        return tools

    def call_tool(self, name: str, arguments: dict | None) -> str:
        with self._lock:
            if not self.ready:
                raise RuntimeError("Windows-MCP 尚未启动。")
            result = self._request_locked(
                "tools/call",
                {"name": name, "arguments": arguments or {}},
                TOOL_TIMEOUT,
            )
        return _tool_text(result)

    def close(self) -> None:
        with self._lock:
            self._stopped = True
            self._shutdown_locked()

    def _spawn_locked(self, command: list[str]) -> None:
        env = os.environ.copy()
        env["ANONYMIZED_TELEMETRY"] = "false"
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        self._stderr = []
        self._tools = []
        self._proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            **kwargs,
        )
        threading.Thread(target=self._read_stdout, name="PyislandMcpOut", daemon=True).start()
        threading.Thread(target=self._read_stderr, name="PyislandMcpErr", daemon=True).start()
        logger.info("已启动 Windows-MCP。")

    def _handshake_locked(self) -> None:
        self._request_locked(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pyisland", "version": "0.1"},
            },
            START_TIMEOUT,
        )
        self._notify_locked("notifications/initialized", {})
        listed = self._request_locked("tools/list", {}, START_TIMEOUT)
        tools = listed.get("tools") if isinstance(listed, dict) else None
        if not isinstance(tools, list) or not tools:
            raise RuntimeError("Windows-MCP 没有返回工具。")
        self._tools = [item for item in tools if isinstance(item, dict)]

    def _request_locked(self, method: str, params: dict, timeout: float) -> dict:
        proc = self._proc
        if proc is None or proc.poll() is not None or proc.stdin is None:
            raise RuntimeError("Windows-MCP 已退出。")
        self._next_id += 1
        request_id = self._next_id
        mailbox: queue.Queue = queue.Queue()
        with self._pending_lock:
            self._pending[request_id] = mailbox
        try:
            self._write_locked({
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            })
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(method)
                try:
                    message = mailbox.get(timeout=min(0.2, remaining))
                    break
                except queue.Empty:
                    if proc.poll() is not None:
                        raise RuntimeError("Windows-MCP 已退出。")
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)
        if not isinstance(message, dict) or message.get("error"):
            raise RuntimeError(method)
        result = message.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(method)
        return result

    def _notify_locked(self, method: str, params: dict) -> None:
        self._write_locked({"jsonrpc": "2.0", "method": method, "params": params})

    def _write_locked(self, payload: dict) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise RuntimeError("Windows-MCP 已退出。")
        proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        proc.stdin.flush()

    def _read_stdout(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            text = line.strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            request_id = message.get("id")
            with self._pending_lock:
                mailbox = self._pending.get(request_id)
            if mailbox is not None:
                mailbox.put(message)

    def _read_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        for line in proc.stderr:
            text = line.strip()
            if not text:
                continue
            self._stderr.append(text)
            del self._stderr[:-20]

    def _shutdown_locked(self) -> None:
        proc = self._proc
        self._proc = None
        self._tools = []
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for mailbox in pending:
            mailbox.put({"error": {"message": "closed"}})
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.close()
        except OSError:
            pass
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
        for stream in (proc.stdout, proc.stderr, proc.stdin):
            if stream is None:
                continue
            try:
                stream.close()
            except OSError:
                pass


def _tool_text(result: dict) -> str:
    content = result.get("content")
    parts = []
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif item.get("type") == "image":
                parts.append("截图已禁用，请改用 Snapshot。")
    text = "\n".join(part for part in parts if part).strip()
    if not text:
        text = json.dumps({key: value for key, value in result.items() if key != "content"}, ensure_ascii=False)
    if result.get("isError"):
        text = "工具返回错误：\n" + text
    if len(text) > MAX_TOOL_CHARS:
        text = text[:MAX_TOOL_CHARS] + "\n…（结果已截断）"
    return text
