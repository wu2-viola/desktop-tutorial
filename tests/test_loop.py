"""循环护栏断言：让它停比让它动难 —— 步数 / 预算 / 兜圈子 / 中断。"""
import json as _json
import threading

import pytest

from agent.loop import AgentLoop
from agent.providers import Provider
from agent.tools import Interrupted, Tool
from agent.types import Event, Message


class EchoTool(Tool):
    name = "echo"
    description = "test"
    schema = {"type": "object", "properties": {}}

    def run(self, args, ctx):
        return {"ok": True, "output": "echoed"}


@pytest.fixture()
def tools():
    return {"echo": EchoTool()}


def _call(name="echo", args="{}", cid="c1"):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": args}}


class ScriptedProvider(Provider):
    """按剧本回放：每轮吐出预设的 assistant 消息。"""

    def __init__(self, script):
        self.script = list(script)
        self.i = 0

    def stream_chat(self, messages, tools):
        msg = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        if isinstance(msg, Exception):
            raise msg
        if msg is Interrupted:
            raise Interrupted()
        yield Event("assistant_done", {"message": msg})


def test_final_without_tool_calls(tools):
    p = ScriptedProvider([Message(role="assistant", content="做完了")])
    events = list(AgentLoop(p, tools, ".").run("任务"))
    assert events[-1].type == "final" and events[-1].data["text"] == "做完了"


def test_tool_call_then_final(tools):
    p = ScriptedProvider([
        Message(role="assistant", content="", tool_calls=[_call()]),
        Message(role="assistant", content="ok"),
    ])
    events = list(AgentLoop(p, tools, ".").run("任务"))
    tool_end = [e for e in events if e.type == "tool_end"]
    assert len(tool_end) == 1 and tool_end[0].data["ok"] is True
    assert events[-1].type == "final"


def test_step_limit_stops(tools):
    class Counting(Provider):
        def __init__(self):
            self.i = 0

        def stream_chat(self, messages, tools):
            self.i += 1        # 每轮参数都不同 → 不会触发兜圈子，只能撞步数上限
            yield Event("assistant_done", {"message": Message(
                role="assistant", content="",
                tool_calls=[_call(args=_json.dumps({"n": self.i}), cid=f"c{self.i}")])})

    events = list(AgentLoop(Counting(), tools, ".", max_steps=3).run("任务"))
    assert events[-1].type == "stopped" and "步数上限" in events[-1].data["reason"]


def test_loop_detection_stops_after_3_same_calls(tools):
    same = Message(role="assistant", content="", tool_calls=[_call(args='{"a":1}', cid="y")])
    p = ScriptedProvider([same])
    events = list(AgentLoop(p, tools, ".").run("任务"))
    assert events[-1].type == "stopped" and "兜圈子" in events[-1].data["reason"]


def test_budget_stops(tools):
    class Spending(Provider):
        def stream_chat(self, messages, tools):
            yield Event("assistant_done", {"message": Message(role="assistant", content="",
                                                              tool_calls=[_call(cid="z")])})
            yield Event("turn_usage", {"prompt_tokens": 600000, "completion_tokens": 0})
    events = list(AgentLoop(Spending(), tools, ".", max_budget_tokens=100).run("任务"))
    assert events[-1].type == "stopped" and "预算" in events[-1].data["reason"]


def test_interrupt_stops(tools):
    p = ScriptedProvider([Interrupted])
    events = list(AgentLoop(p, tools, ".").run("任务"))
    assert events[-1].type == "stopped" and "中断" in events[-1].data["reason"]


def test_provider_error_becomes_readable_event(tools):
    p = ScriptedProvider([RuntimeError("connection reset")])
    events = list(AgentLoop(p, tools, ".").run("任务"))
    assert events[-1].type == "error" and "模型调用失败" in events[-1].data["message"]


def test_unknown_tool_is_observed_not_crash(tools):
    p = ScriptedProvider([
        Message(role="assistant", content="", tool_calls=[_call(name="nope", cid="w")]),
        Message(role="assistant", content="好"),
    ])
    events = list(AgentLoop(p, tools, ".").run("任务"))
    card = [e for e in events if e.type == "tool_end"][0]
    assert card.data["ok"] is False and "未知工具" in card.data["output"]


def test_bad_json_args_observed(tools):
    p = ScriptedProvider([
        Message(role="assistant", content="", tool_calls=[_call(args="{bad json", cid="v")]),
        Message(role="assistant", content="好"),
    ])
    events = list(AgentLoop(p, tools, ".").run("任务"))
    card = [e for e in events if e.type == "tool_end"][0]
    assert card.data["ok"] is False and "JSON" in card.data["output"]
