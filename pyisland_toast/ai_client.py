"""读取本地模型配置，并调用 OpenAI 兼容的 chat/completions。"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from pyisland_toast.paths import config_path

logger = logging.getLogger(__name__)

CONFIG_PATH = config_path()
UNCONFIGURED_REPLY = "AI 服务尚未配置，请从托盘菜单打开设置并填写接口和密钥。"


@dataclass(frozen=True)
class AiSettings:
    enabled: bool = False
    base_url: str = ""
    api_key: str = field(default="", repr=False)
    model: str = ""
    system_prompt: str = ""
    temperature: float = 0.7
    top_p: float = 1.0
    max_tokens: int = 2048
    timeout_seconds: float = 60
    extra_headers: dict[str, str] = field(default_factory=dict, repr=False)
    windows_mcp_command: str = ""
    windows_mcp_exclude_tools: str = "Registry,Process,Screenshot"

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.base_url.strip() and self.api_key.strip() and self.model.strip())


def load_settings(path: Path | None = None) -> AiSettings:
    """文件缺失或损坏时返回未启用配置，避免拖垮托盘程序。"""
    config_path = path or CONFIG_PATH
    if not config_path.exists():
        return AiSettings()
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("配置必须是 JSON 对象")
        headers = raw.get("extra_headers") if isinstance(raw.get("extra_headers"), dict) else {}
        return AiSettings(
            enabled=bool(raw.get("enabled", False)),
            base_url=str(raw.get("base_url") or ""),
            api_key=str(raw.get("api_key") or ""),
            model=str(raw.get("model") or ""),
            system_prompt=str(raw.get("system_prompt") or ""),
            temperature=_number(raw.get("temperature", 0.7), 0.7),
            top_p=_number(raw.get("top_p", 1.0), 1.0),
            max_tokens=max(1, int(_number(raw.get("max_tokens", 2048), 2048))),
            timeout_seconds=max(1.0, _number(raw.get("timeout_seconds", 60), 60)),
            extra_headers={str(key): str(value) for key, value in headers.items()},
            windows_mcp_command=str(raw.get("windows_mcp_command") or ""),
            windows_mcp_exclude_tools=str(raw.get("windows_mcp_exclude_tools", "Registry,Process,Screenshot") or ""),
        )
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        logger.warning("AI 配置无法读取，模型调用已停用。")
        return AiSettings()


def _default_form() -> dict:
    return {
        "enabled": True,
        "base_url": "https://api.deepseek.com",
        "api_key": "",
        "model": "deepseek-flash",
        "system_prompt": "你是一个电脑助手，当用户询问你问题的时候，请用简短的话回答用户的问题。",
        "temperature": 0.7,
        "top_p": 1.0,
        "max_tokens": 2048,
        "timeout_seconds": 60,
    }


def form_settings(path: Path | None = None) -> dict:
    """给设置页的字段。文件缺失时给出可编辑的默认值，不创建文件。"""
    form = _default_form()
    target = path or CONFIG_PATH
    if not target.exists():
        return form
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return form
    if not isinstance(raw, dict):
        return form
    form["enabled"] = bool(raw.get("enabled", form["enabled"]))
    for key in ("base_url", "api_key", "model", "system_prompt"):
        if key in raw and raw[key] is not None:
            form[key] = str(raw[key])
    form["temperature"] = _number(raw.get("temperature", form["temperature"]), form["temperature"])
    form["top_p"] = _number(raw.get("top_p", form["top_p"]), form["top_p"])
    form["max_tokens"] = max(1, int(_number(raw.get("max_tokens", form["max_tokens"]), form["max_tokens"])))
    form["timeout_seconds"] = max(1.0, _number(raw.get("timeout_seconds", form["timeout_seconds"]), form["timeout_seconds"]))
    return form


def save_settings(payload: dict, path: Path | None = None) -> None:
    """写回配置。只更新设置页字段，保留 Windows-MCP 和未知项。"""
    if not isinstance(payload, dict):
        raise ValueError("设置内容不是有效的 JSON。")
    target = path or CONFIG_PATH
    existing = {}
    if target.exists():
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = None
        if isinstance(raw, dict):
            existing = raw
    updated = dict(existing)
    updated["enabled"] = bool(payload.get("enabled", False))
    updated["provider"] = str(existing.get("provider") or "openai-compatible")
    updated["base_url"] = str(payload.get("base_url") or "").strip()
    updated["api_key"] = str(payload.get("api_key") or "").strip()
    updated["model"] = str(payload.get("model") or "").strip()
    updated["system_prompt"] = str(payload.get("system_prompt") or "").strip()
    updated["temperature"] = _bounded(payload.get("temperature", 0.7), 0, 2, "温度")
    updated["top_p"] = _bounded(payload.get("top_p", 1), 0, 1, "Top P")
    updated["max_tokens"] = int(_bounded(payload.get("max_tokens", 2048), 1, 32768, "最大输出"))
    updated["timeout_seconds"] = _bounded(payload.get("timeout_seconds", 60), 1, 600, "超时")
    updated.setdefault("extra_headers", {})
    updated.setdefault("windows_mcp_command", "")
    updated.setdefault("windows_mcp_exclude_tools", "Registry,Process,Screenshot")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def _bounded(value, low: float, high: float, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(label + "不是有效数字。") from None
    if number < low or number > high:
        raise ValueError(f"{label}需要在 {low:g} 到 {high:g} 之间。")
    return number

def chat_url(base_url: str) -> str:
    url = base_url.strip().rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    return url + "/chat/completions"


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict

    def as_message(self) -> dict:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


@dataclass(frozen=True)
class ChatResult:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)


MAX_TOOL_STEPS = 50
HIDDEN_TOOLS = {"Screenshot"}
READ_ONLY_TOOLS = {"Snapshot", "Scrape", "DisplayInventory", "Clipboard"}
TOOL_GUIDANCE = (
    "需要操作这台 Windows 电脑时，用 Snapshot 获取界面上的可点击元素。"
    "截图工具已禁用，不要尝试截图。界面没有变化时不要重复查看。信息够了就立刻用简短中文回答。"
)
LIMIT_NUDGE = "操作步数已经用完。请根据已有结果用简短中文说明做到哪一步，不要再调用工具。"


def complete_chat(settings: AiSettings, history: list[dict]) -> str:
    return complete_chat_result(settings, history).text


def complete_chat_result(settings: AiSettings, history: list[dict], tools: list[dict] | None = None) -> ChatResult:
    messages = _request_messages(settings, history, bool(tools))
    payload = {
        "model": settings.model,
        "messages": messages,
        "temperature": settings.temperature,
        "top_p": settings.top_p,
        "max_tokens": settings.max_tokens,
    }
    if tools:
        payload["tools"] = tools
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    headers.update(settings.extra_headers)
    request = urllib.request.Request(chat_url(settings.base_url), data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=settings.timeout_seconds) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = _safe_detail(exc.read().decode("utf-8", "replace"), settings.api_key)
        return ChatResult(f"模型服务拒绝了请求：{detail}")
    except (urllib.error.URLError, TimeoutError, OSError):
        return ChatResult("无法连接模型服务。")
    return _read_completion_result(body)


def run_agent_turn(settings: AiSettings, history: list[dict], session=None, on_progress=None, should_stop=None) -> str:
    """需要操作电脑时调用 Windows-MCP，再把结果交回模型。"""
    if should_stop and should_stop():
        return ""
    tools = []
    failure = ""
    if session is not None:
        try:
            started = session.ensure_started()
        except Exception:
            logger.warning("Windows-MCP 启动失败。")
            started = False
        if should_stop and should_stop():
            return ""
        if started:
            tools = _visible_tools(session.openai_tools())
        else:
            failure = getattr(session, "error", "") or "Windows-MCP 没有启动。"
    messages = [dict(message) for message in history]
    seen = []
    for _ in range(MAX_TOOL_STEPS):
        if should_stop and should_stop():
            return ""
        result = complete_chat_result(settings, messages, tools or None)
        if tools and _rejected(result):
            result = complete_chat_result(settings, messages, None)
            tools = []
        if not result.tool_calls:
            if failure and not tools:
                note = "（" + failure + "）"
                return result.text if note in result.text else result.text + "\n\n" + note
            return result.text
        if session is None:
            return result.text or "模型要求调用工具，但 Windows-MCP 没有启动。"
        messages.append({
            "role": "assistant",
            "content": result.text or None,
            "tool_calls": [call.as_message() for call in result.tool_calls],
        })
        for call in result.tool_calls:
            if should_stop and should_stop():
                return ""
            output = _tool_output(session, call, seen, on_progress)
            seen.append(_call_signature(call))
            messages.append({"role": "tool", "tool_call_id": call.id, "content": output})
    return _finish_after_limit(settings, messages, should_stop)


def _call_signature(call: ToolCall) -> str:
    return call.name + "\n" + json.dumps(call.arguments, ensure_ascii=False, sort_keys=True)


def _visible_tools(tools: list[dict]) -> list[dict]:
    visible = []
    for tool in tools:
        function = tool.get("function") if isinstance(tool, dict) else None
        name = function.get("name") if isinstance(function, dict) else ""
        if name in HIDDEN_TOOLS:
            continue
        visible.append(tool)
    return visible


def _tool_output(session, call: ToolCall, seen: list[str], on_progress=None) -> str:
    if call.name in HIDDEN_TOOLS:
        return "Screenshot 已禁用。请用 Snapshot 了解界面。"
    signature = _call_signature(call)
    if call.name in READ_ONLY_TOOLS and seen.count(signature) >= 2:
        return "同样的界面信息已经获取过。请根据已有结果继续下一步，或直接回答。"
    if on_progress is not None:
        on_progress("正在执行 " + call.name + "…")
    try:
        return session.call_tool(call.name, call.arguments)
    except Exception:
        logger.warning("工具 %s 执行失败。", call.name)
        return "工具执行失败。"


def _rejected(result: ChatResult) -> bool:
    return not result.tool_calls and result.text.startswith("模型服务拒绝了请求")


def _finish_after_limit(settings: AiSettings, messages: list[dict], should_stop) -> str:
    if should_stop and should_stop():
        return ""
    messages.append({"role": "user", "content": LIMIT_NUDGE})
    result = complete_chat_result(settings, messages, None)
    if result.tool_calls or not result.text or result.text.startswith(("模型服务拒绝了请求", "无法连接", "模型请求失败")):
        return "已达到操作步数上限。"
    return result.text


def _request_messages(settings: AiSettings, history: list[dict], with_tools: bool) -> list[dict]:
    messages = []
    prompt = settings.system_prompt.strip()
    if with_tools:
        prompt = (prompt + "\n" + TOOL_GUIDANCE).strip()
    if prompt:
        messages.append({"role": "system", "content": prompt})
    messages.extend(history)
    return messages


class ChatClient:
    """在后台线程请求模型，避免卡住 Qt。"""

    def __init__(self, settings: AiSettings, session=None):
        self.settings = settings
        self.session = session

    def complete(self, history: list[dict], callback, on_progress=None, should_stop=None):
        snapshot = [dict(message) for message in history]
        threading.Thread(
            target=self._run,
            args=(snapshot, callback, on_progress, should_stop),
            name="PyislandAi",
            daemon=True,
        ).start()

    def _run(self, history, callback, on_progress, should_stop):
        try:
            text = run_agent_turn(
                self.settings,
                history,
                self.session,
                on_progress=on_progress,
                should_stop=should_stop,
            )
        except Exception:
            logger.warning("AI 请求失败。")
            text = "模型请求失败。"
        if should_stop and should_stop():
            return
        callback(text)


def visible_history(messages: list[dict]) -> list[dict]:
    history = []
    for message in messages:
        if message.get("pending") or message.get("content") == "已取消。":
            continue
        role = message.get("role")
        if role in {"user", "assistant"}:
            history.append({"role": role, "content": str(message.get("content") or "")})
    return history


def _read_completion_result(body: str) -> ChatResult:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return ChatResult("模型返回的不是 JSON。")
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ChatResult("模型没有返回内容。")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return ChatResult("模型没有返回内容。")
    text = _message_text(message.get("content")).strip()
    calls = _tool_calls(message)
    if calls:
        return ChatResult(text, calls)
    return ChatResult(text or "（模型没有返回文字）")


def _read_completion(body: str) -> str:
    return _read_completion_result(body).text


def _tool_calls(message: dict) -> list[ToolCall]:
    raw_calls = message.get("tool_calls")
    if not isinstance(raw_calls, list):
        return []
    calls = []
    for item in raw_calls:
        if not isinstance(item, dict):
            continue
        function = item.get("function") if isinstance(item.get("function"), dict) else {}
        name = str(function.get("name") or "")
        if not name:
            continue
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError:
                arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        calls.append(ToolCall(str(item.get("id") or name), name, arguments))
    return calls


def _message_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
        return "".join(parts)
    return str(content)


def _safe_detail(body: str, api_key: str) -> str:
    text = body
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict) and error.get("message"):
            text = str(error["message"])
        elif parsed.get("message"):
            text = str(parsed["message"])
    if api_key:
        text = text.replace(api_key, "***")
    text = " ".join(text.split())
    return text[:300] or "未知错误"


def _number(value, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback
