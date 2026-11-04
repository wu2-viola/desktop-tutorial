"""智能体循环 —— 决策 → 动作 → 观察 → 再决策。

写循环最难的不是让它动，是让它停。三道护栏缺一不可：
  1. 步数上限（max_steps）
  2. token 预算（max_budget_tokens）
  3. 同一调用连续 3 次判定为兜圈子，直接叫停
外加用户中断（Interrupted），四条出口全部以 stopped/error 事件收尾。
v1.1 起：system prompt 里常驻技能目录，正文靠 use_skill 按需加载。
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Iterator

from .providers import SYSTEM_PROMPT, Provider
from .skills import UseSkillTool, catalog_text, load_skills
from .tools import Interrupted, Tool, ToolContext
from .types import Event, Message, Observation, ToolCall

REPO = Path(__file__).resolve().parent.parent


def _flag(name: str, default: bool = True) -> bool:
    """环境开关：ENABLE_SKILLS=0 关掉对应能力。"""
    return os.environ.get(name, "1" if default else "0") not in ("0", "false", "False")


class LoopDetected(Exception):
    """同一 (tool, args) 连续出现 3 次 —— 继续只会空转，直接叫停。"""


class AgentLoop:
    def __init__(self, provider: Provider, tools: dict[str, Tool], workspace: Path,
                 max_steps: int = 12, max_budget_tokens: int = 1_000_000,
                 enable_skills: bool | None = None,
                 skills_dir: Path | None = None,
                 system_prompt: str | None = None):
        self.provider = provider
        self.workspace = Path(workspace)
        self.max_steps = max_steps
        self.max_budget_tokens = max_budget_tokens
        self.enable_skills = _flag("ENABLE_SKILLS") if enable_skills is None else enable_skills

        self.skills = load_skills(skills_dir or (REPO / "skills")) if self.enable_skills else []
        self.tools = dict(tools)
        if self.enable_skills:
            self.tools["use_skill"] = UseSkillTool(self.skills)
        self.base_system_prompt = system_prompt or SYSTEM_PROMPT

    def build_system_prompt(self) -> str:
        parts = [self.base_system_prompt]
        if self.enable_skills and self.skills:
            parts.append(catalog_text(self.skills))
        return "\n\n".join(parts)

    # ---- 对外入口：迭代消费事件流 ----
    def run(self, task: str, interrupt: threading.Event | None = None) -> Iterator[Event]:
        ctx = ToolContext(self.workspace, interrupt or threading.Event())
        messages: list[Message] = [
            Message(role="system", content=self.build_system_prompt()),
            Message(role="user", content=task),
        ]
        usage_total = 0
        history: list[tuple[str, str]] = []      # (tool, args) 供兜圈子判定

        yield Event("step_begin", {"step": 1, "total_steps": self.max_steps})
        for step in range(1, self.max_steps + 1):
            if step > 1:
                yield Event("step_begin", {"step": step, "total_steps": self.max_steps})
            try:
                events = list(self.provider.stream_chat(messages,
                                                        [t.spec() for t in self.tools.values()]))
            except Interrupted:
                yield Event("stopped", {"reason": "用户中断"})
                return
            except Exception as e:               # 网络 / Key / 配额 —— 都在这层变成人话
                yield Event("error", {"message": f"模型调用失败：{e}"})
                return

            assistant: Message | None = None
            for ev in events:
                if ev.type == "assistant_done":
                    assistant = ev.data["message"]
                elif ev.type == "turn_usage":
                    usage_total += ev.data["prompt_tokens"] + ev.data["completion_tokens"]
                    yield ev
                else:
                    yield ev
            if assistant is None:
                yield Event("error", {"message": "模型没有返回任何内容"})
                return
            messages.append(assistant)

            if not assistant.tool_calls:         # 模型认为做完了
                yield Event("final", {"text": assistant.content, "usage_total": usage_total})
                return

            for tc in assistant.tool_calls:
                call = ToolCall.from_openai(tc)
                try:
                    obs = self._execute(call, ctx, history)
                except LoopDetected:
                    yield Event("stopped", {"reason": "同一调用连续 3 次判定为兜圈子，直接叫停"})
                    return
                yield Event("tool_end", {
                    "call_id": obs.call_id, "tool": obs.tool, "ok": obs.ok,
                    "output": obs.output, "error": obs.error,
                    "elapsed_ms": obs.elapsed_ms, "blocks": obs.blocks,
                })
                messages.append(obs.to_tool_message())

            if usage_total > self.max_budget_tokens:
                yield Event("stopped", {"reason": f"token 预算耗尽（{usage_total}）"})
                return

        yield Event("stopped", {"reason": f"步数上限（{self.max_steps} 步）已到，先停给你看"})

    # ---- 执行单个工具调用 ----
    def _execute(self, call: ToolCall, ctx: ToolContext,
                 history: list[tuple[str, str]]) -> Observation:
        started = time.time()

        # 兜圈子判定：同一 (tool, args) 连续 3 次
        signature = (call.name, call.arguments)
        history.append(signature)
        if len(history) >= 3 and history[-3:] == [signature] * 3:
            raise LoopDetected(call.name)

        tool = self.tools.get(call.name)
        if tool is None:
            return Observation(call.id, call.name, False,
                               output=f"未知工具：{call.name}。可用：{', '.join(self.tools)}",
                               error="unknown tool")
        try:
            args = json.loads(call.arguments) if call.arguments.strip() else {}
            if not isinstance(args, dict):
                raise ValueError("arguments 不是 JSON 对象")

            result = tool.run(args, ctx)
            elapsed = int((time.time() - started) * 1000)
            return Observation(call.id, call.name, bool(result.get("ok")),
                               output=result.get("output", ""),
                               blocks=result.get("blocks", []),
                               elapsed_ms=elapsed)
        except Interrupted:
            return Observation(call.id, call.name, False, output="用户中断",
                               error="interrupted")
        except json.JSONDecodeError as e:
            return Observation(call.id, call.name, False,
                               output=f"工具参数不是合法 JSON：{e}", error="bad arguments")
        except Exception as e:
            return Observation(call.id, call.name, False,
                               output=f"工具执行异常：{type(e).__name__}: {e}", error="exception")
