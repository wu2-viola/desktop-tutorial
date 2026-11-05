"""确定性长任务剧本：用于演示「跑到一半被 kill，重启从断点继续」。

它是**无状态**的：第几幕只看 messages 里已有几条工具结果，不看自己的计数器。
这一点很关键 —— 进程重启后 _turn 归零的 provider 会让 resume 退化成「从第 1 幕重播」。
"""
from __future__ import annotations

import json
import time
from typing import Iterator

from ..providers import Provider
from ..types import Event, Message

BUGGY = "        return 0            # BUG：空列表应当抛错，而不是静默返回 0"
WRONG = "        return 0.9 * total / len(nums)  # 故意改错"
RIGHT = '        raise ValueError("mean() of empty sequence")'

# (tool, args, 一句话说明) —— 五幕之后收尾
ACTIONS: list[tuple[str, dict, str]] = [
    ("read", {"path": "stats.py"}, "先看现状，确认空列表的分支。"),
    ("bash", {"command": "python -m pytest -q"}, "跑一遍测试，看红在哪。"),
    ("read", {"path": "test_stats.py"}, "看测试期望的是抛错还是返回值。"),
    ("edit", {"path": "stats.py", "old": BUGGY, "new": RIGHT}, "把静默返回 0 改成抛 ValueError。"),
    ("bash", {"command": "python -m pytest -q"}, "再跑一遍，确认变绿。"),
]


class ScriptedLongProvider(Provider):
    name = "scripted-long"

    def __init__(self, slow: float = 0.0):
        self.slow = slow

    def stream_chat(self, messages: list[Message],
                    tools: list[dict]) -> Iterator[Event]:
        done_tools = sum(1 for m in messages if m.role == "tool")
        time.sleep(self.slow)                      # 演示时留出 kill 的窗口

        if done_tools >= len(ACTIONS):
            text = ("修好了：mean 对空列表抛 ValueError，不再静默返回 0；"
                    "最后一遍测试全绿。")
            yield Event("assistant_text", {"delta": text})
            yield Event("assistant_done", {"message": Message(role="assistant", content=text)})
            return

        name, args, note = ACTIONS[done_tools]
        call_id = f"s{done_tools + 1}"             # 固定 id：重复执行可被识别
        msg = Message(role="assistant", content=note,
                      tool_calls=[{"id": call_id, "type": "function",
                                   "function": {"name": name,
                                                "arguments": json.dumps(args, ensure_ascii=False)}}])
        yield Event("assistant_text", {"delta": note})
        yield Event("assistant_done", {"message": msg})
