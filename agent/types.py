"""数据结构：消息 / 工具调用 / 观察 / token 用量。

循环里的每一步都产出一个事件（Event），UI 和 CLI 消费同一种流，
这样「界面」和「界面之外」看到的东西完全一致。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@dataclass
class Message:
    role: str                       # system / user / assistant / tool
    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)  # assistant 发起的调用
    tool_call_id: Optional[str] = None                    # role=tool 时对应哪个调用

    def to_openai(self) -> dict:
        d: dict[str, Any] = {"role": self.role, "content": self.content or None}
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.tool_call_id is not None:
            d["tool_call_id"] = self.tool_call_id
        return d

    def to_dict(self) -> dict:
        """落盘用：字段与 to_openai 一致，但保留空 content，方便 resume 原样恢复。"""
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.tool_call_id is not None:
            d["tool_call_id"] = self.tool_call_id
        return d

    @staticmethod
    def from_dict(d: dict) -> "Message":
        return Message(role=d["role"], content=d.get("content") or "",
                       tool_calls=list(d.get("tool_calls") or []),
                       tool_call_id=d.get("tool_call_id"))


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str                  # 模型给的是 JSON 字符串，解析失败也算一次观察

    @staticmethod
    def from_openai(tc: dict) -> "ToolCall":
        return ToolCall(id=tc.get("id") or new_id("call"),
                        name=tc.get("function", {}).get("name", ""),
                        arguments=tc.get("function", {}).get("arguments") or "{}")


@dataclass
class Observation:
    call_id: str
    tool: str
    ok: bool
    output: str = ""                # 给模型看的文本结果
    blocks: list[dict] = field(default_factory=list)  # 图片等多模态内容块
    error: Optional[str] = None
    elapsed_ms: int = 0

    def to_tool_message(self) -> Message:
        return Message(role="tool", content=self.output or (self.error or ""),
                       tool_call_id=self.call_id)


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


# ---- 循环事件（UI / CLI / SSE 共用） ----
# type: step_begin | assistant_text | tool_begin | tool_end |
#       turn_usage | final | stopped | error
@dataclass
class Event:
    type: str
    data: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        d = {"type": self.type, "ts": time.time()}
        d.update(self.data)
        return d
