"""模型适配层：统一的事件流接口 + DeepSeek（OpenAI 兼容）流式实现 + 离线 mock。

为什么抽一层：M 个应用 × N 个模型 = M×N 段胶水代码；协议（这里的 Event 流）
是 M+N —— 换模型只改这一个文件。
"""
from __future__ import annotations

import json
from typing import Iterator

from .types import Event, Message, ToolCall, Usage

SYSTEM_PROMPT = (
    "你是一个工作区编码智能体。你只能通过工具读写文件、执行命令，"
    "每次只做一小步，看到观察结果再决定下一步。规则：\n"
    "1. 改代码前先 read 看原文；edit 的 old 必须带足够上下文保证唯一；\n"
    "2. 改完要跑测试验证，不要声称完成却没有证据；\n"
    "3. 文件路径一律相对工作区根目录；\n"
    "4. 任务完成后用一段话总结：改了什么、怎么验证的。"
)


class Provider:
    """所有模型实现的公共接口：流式对话，产出 Event。"""
    name = "base"

    def stream_chat(self, messages: list[Message],
                    tools: list[dict]) -> Iterator[Event]:
        raise NotImplementedError


class DeepSeekProvider(Provider):
    """DeepSeek 官方 API（OpenAI 兼容协议，流式 + function calling）。"""
    name = "deepseek"

    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com",
                 model: str = "deepseek-chat"):
        from openai import OpenAI
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=60)

    def stream_chat(self, messages: list[Message],
                    tools: list[dict]) -> Iterator[Event]:
        kwargs: dict = {
            "model": self.model,
            "messages": [m.to_openai() for m in messages],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools
        stream = self.client.chat.completions.create(**kwargs)

        text_parts: list[str] = []
        tool_calls: dict[int, dict] = {}
        usage = Usage()
        for chunk in stream:
            if chunk.usage:
                usage = Usage(chunk.usage.prompt_tokens or 0,
                              chunk.usage.completion_tokens or 0)
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                text_parts.append(delta.content)
                yield Event("assistant_text", {"delta": delta.content})
            if delta and delta.tool_calls:
                for tc in delta.tool_calls:
                    slot = tool_calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["arguments"] += tc.function.arguments

        msg = Message(role="assistant", content="".join(text_parts),
                      tool_calls=[{"id": v["id"], "type": "function",
                                   "function": {"name": v["name"], "arguments": v["arguments"]}}
                                  for v in tool_calls.values()])
        yield Event("assistant_done", {"message": msg})
        if usage.total:
            yield Event("turn_usage", {"prompt_tokens": usage.prompt_tokens,
                                       "completion_tokens": usage.completion_tokens})


class MockProvider(Provider):
    """离线 mock：不联网也能演示完整循环（决定→动作→观察→再决策）。

    脚本固定三步：read 看 bug → edit 修复 → bash 跑测试 → 总结。
    用于 CI、断网演示和 tests —— 模型没变，换了剧本而已。
    """

    def __init__(self, target: str = "stats.py"):
        self.target = target
        self._turn = 0

    def stream_chat(self, messages: list[Message],
                    tools: list[dict]) -> Iterator[Event]:
        self._turn += 1
        done = any(m.role == "tool" and "passed" in m.content.lower()
                   for m in messages if m.role == "tool")

        def emit(msg: Message) -> Iterator[Event]:
            if msg.content:
                yield Event("assistant_text", {"delta": msg.content})
            yield Event("assistant_done", {"message": msg})

        if done:
            yield from emit(Message(role="assistant",
                content="修好了：mean 对空列表抛 ValueError，不再静默返回 0；全部测试通过。"))
            return
        if self._turn == 1:
            yield from emit(Message(role="assistant", content="先看一下现状。",
                tool_calls=[{"id": "mock_call_1", "type": "function",
                             "function": {"name": "read",
                                          "arguments": json.dumps({"path": self.target})}}]))
        elif self._turn == 2:
            yield from emit(Message(role="assistant", content="把空列表静默返回 0 改成抛错。",
                tool_calls=[{"id": "mock_call_2", "type": "function",
                             "function": {"name": "edit",
                                          "arguments": json.dumps({
                                              "path": self.target,
                                              "old": "        return 0",
                                              "new": "        raise ValueError(\"mean() of empty sequence\")"})}}]))
        else:
            yield from emit(Message(role="assistant", content="跑测试验证。",
                tool_calls=[{"id": "mock_call_3", "type": "function",
                             "function": {"name": "bash",
                                          "arguments": json.dumps({
                                              "command": "python -m pytest test_stats.py -q",
                                              "timeout": 60})}}]))
