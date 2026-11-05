"""智能体循环 —— 决策 → 动作 → 观察 → 再决策。

写循环最难的不是让它动，是让它停。三道护栏缺一不可：
  1. 步数上限（max_steps）
  2. token 预算（max_budget_tokens）
  3. 同一调用连续 3 次判定为兜圈子，直接叫停
外加用户中断（Interrupted），四条出口全部以 stopped/error 事件收尾。

v1.1：system prompt 里常驻技能目录，正文靠 use_skill 按需加载。
v1.2：AGENTS.md 两层注入 + Pre/Post hook 硬约束 + reviewer 子 agent。
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Iterator

from .agents_md import load_agents_md, system_block
from .daemon.checkpoint import capture
from .hooks import HookEngine
from .providers import SYSTEM_PROMPT, Provider
from .skills import UseSkillTool, catalog_text, load_skills
from .subagents import ReviewerTool
from .tools import Interrupted, Tool, ToolContext
from .types import Event, Message, Observation, ToolCall

REPO = Path(__file__).resolve().parent.parent


def _flag(name: str, default: bool = True) -> bool:
    """环境开关：ENABLE_SKILLS=0 / ENABLE_HOOKS=0 关掉对应能力。"""
    return os.environ.get(name, "1" if default else "0") not in ("0", "false", "False")


class LoopDetected(Exception):
    """同一 (tool, args) 连续出现 3 次 —— 继续只会空转，直接叫停。"""


class AgentLoop:
    def __init__(self, provider: Provider, tools: dict[str, Tool], workspace: Path,
                 max_steps: int = 12, max_budget_tokens: int = 1_000_000,
                 enable_skills: bool | None = None,
                 enable_hooks: bool | None = None,
                 enable_reviewer: bool | None = None,
                 skills_dir: Path | None = None,
                 system_prompt: str | None = None):
        self.provider = provider
        self.workspace = Path(workspace)
        self.max_steps = max_steps
        self.max_budget_tokens = max_budget_tokens
        self.enable_skills = _flag("ENABLE_SKILLS") if enable_skills is None else enable_skills
        self.enable_hooks = _flag("ENABLE_HOOKS") if enable_hooks is None else enable_hooks
        self.enable_reviewer = _flag("ENABLE_SUBAGENT") if enable_reviewer is None else enable_reviewer

        self.skills = load_skills(skills_dir or (REPO / "skills")) if self.enable_skills else []
        self.tools = dict(tools)
        if self.enable_skills:
            self.tools["use_skill"] = UseSkillTool(self.skills)
        self.reviewer: ReviewerTool | None = None
        if self.enable_reviewer:
            self.reviewer = ReviewerTool(provider, self.workspace)
            self.tools["spawn_reviewer"] = self.reviewer

        self.hooks = HookEngine(self.workspace) if self.enable_hooks else None
        self.agents_md = load_agents_md(self.workspace)
        self.base_system_prompt = system_prompt or SYSTEM_PROMPT

    def build_system_prompt(self) -> str:
        parts = [self.base_system_prompt]
        block = system_block(self.agents_md)
        if block:
            parts.append(block)
        if self.enable_skills and self.skills:
            parts.append(catalog_text(self.skills))
        return "\n\n".join(parts)

    # ---- 对外入口：迭代消费事件流 ----
    def run(self, task: str, interrupt: threading.Event | None = None,
            checkpoint=None) -> Iterator[Event]:
        """checkpoint：RunState 协议对象（messages/step/executed_calls/history/save()）。

        传了它，每完成一个工具调用就落盘；进程被 kill 后，daemon 拿着同一份
        checkpoint 再调一次 run()，已执行过的调用 id 会被跳过，而不是重跑。
        """
        ctx = ToolContext(self.workspace, interrupt or threading.Event())
        if checkpoint is None:
            messages: list[Message] = [
                Message(role="system", content=self.build_system_prompt()),
                Message(role="user", content=task),
            ]
            usage_total = 0
            history: list[tuple[str, str]] = []      # (tool, args) 供兜圈子判定
            executed: set[str] = set()
            skip_once: set[str] = set()
            first_step = 1
        else:                                        # 从断点恢复上下文，而不是重新开始
            messages = [Message.from_dict(m) for m in checkpoint.messages]
            usage_total = checkpoint.usage_total
            history = [tuple(h) for h in checkpoint.history]
            executed = set(checkpoint.executed_calls)
            # 只跳过「上个进程执行过的」那一次；同进程内再次发起同一 id 仍算兜圈子
            skip_once = set(checkpoint.executed_calls)
            first_step = checkpoint.step + 1
            self._restore_read_paths(messages, ctx)  # 「edit 前必须 read」也要续上

        def persist(step: int, status: str = "running") -> None:
            if checkpoint is None:
                return
            capture(checkpoint, messages, step, usage_total, executed, status)
            checkpoint.save()

        if checkpoint is not None:                   # 断点处可能「已决策、未执行完」
            pending = self._pending_calls(messages, executed)
            if pending:
                yield Event("step_begin", {"step": checkpoint.step,
                                           "total_steps": self.max_steps, "resumed": True})
                try:
                    for ev in self._run_calls(pending, messages, ctx, history,
                                              executed, checkpoint.step, persist, skip_once):
                        yield ev
                except LoopDetected:
                    persist(checkpoint.step, "stopped")
                    yield Event("stopped", {"reason": "同一调用连续 3 次判定为兜圈子，直接叫停"})
                    return

        for step in range(first_step, self.max_steps + 1):
            yield Event("step_begin", {"step": step, "total_steps": self.max_steps})
            try:
                events = list(self.provider.stream_chat(messages,
                                                        [t.spec() for t in self.tools.values()]))
            except Interrupted:
                persist(step, "stopped")
                yield Event("stopped", {"reason": "用户中断"})
                return
            except Exception as e:               # 网络 / Key / 配额 —— 都在这层变成人话
                persist(step, "failed")
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
                persist(step, "failed")
                yield Event("error", {"message": "模型没有返回任何内容"})
                return
            messages.append(assistant)
            persist(step)                            # 决策落盘：重启后知道走到第几步

            if not assistant.tool_calls:             # 模型认为做完了
                persist(step, "done")
                yield Event("final", {"text": assistant.content, "usage_total": usage_total})
                return

            try:
                for ev in self._run_calls(assistant.tool_calls, messages, ctx, history,
                                          executed, step, persist, skip_once):
                    yield ev
            except LoopDetected:
                persist(step, "stopped")
                yield Event("stopped", {"reason": "同一调用连续 3 次判定为兜圈子，直接叫停"})
                return

            if usage_total > self.max_budget_tokens:
                persist(step, "stopped")
                yield Event("stopped", {"reason": f"token 预算耗尽（{usage_total}）"})
                return

        persist(self.max_steps, "stopped")
        yield Event("stopped", {"reason": f"步数上限（{self.max_steps} 步）已到，先停给你看"})

    # ---- 工具调用的执行与落盘（主循环和断点补跑共用这一段） ----
    @staticmethod
    def _pending_calls(messages: list[Message], executed: set[str]) -> list[dict]:
        """最后一条 assistant 里「已决策但没执行完」的调用。"""
        last = next((m for m in reversed(messages) if m.role == "assistant"), None)
        if last is None:
            return []
        return [tc for tc in (last.tool_calls or [])
                if (tc.get("id") or "") not in executed]

    def _run_calls(self, calls: list[dict], messages: list[Message], ctx: ToolContext,
                   history: list[tuple[str, str]], executed: set[str], step: int,
                   persist, skip_once: set[str] | None = None) -> Iterator[Event]:
        for tc in calls:
            call = ToolCall.from_openai(tc)
            if skip_once and call.id in skip_once:
                skip_once.discard(call.id)       # 上个进程执行过的那一次：结果已在 messages 里
                continue
            obs = self._execute(call, ctx, history)      # LoopDetected 由调用方接
            messages.append(obs.to_tool_message())
            executed.add(call.id)
            persist(step)                        # 每个工具结果落盘一次
            yield Event("tool_end", {
                "call_id": obs.call_id, "tool": obs.tool, "ok": obs.ok,
                "output": obs.output, "error": obs.error,
                "elapsed_ms": obs.elapsed_ms, "blocks": obs.blocks,
            })

    @staticmethod
    def _restore_read_paths(messages: list[Message], ctx: ToolContext) -> None:
        """从历史里恢复「read 过哪些文件」，否则续跑后第一次 edit 会被护栏拒绝。"""
        answered = {m.tool_call_id for m in messages if m.role == "tool"}
        for m in messages:
            for tc in (m.tool_calls or []):
                fn = tc.get("function", {})
                if fn.get("name") != "read" or tc.get("id") not in answered:
                    continue
                try:
                    path = json.loads(fn.get("arguments") or "{}").get("path")
                    if path:
                        ctx.read_paths.add(str(ctx.resolve_in_workspace(path)))
                except Exception:
                    continue

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

            if self.hooks:                      # PreToolUse：硬约束，拒绝并给替代方案
                denied = self.hooks.pre(call.name, args)
                if denied:
                    return Observation(call.id, call.name, False,
                                       output=f"被 hook 拦下：{denied['reason']}",
                                       error="denied by hook")

            result = tool.run(args, ctx)
            output = result.get("output", "")
            if self.hooks:                      # PostToolUse：写完自动跑测试，只回三行
                note = self.hooks.post(call.name, args)
                if note:
                    output = f"{output}\n\n{note}"
            elapsed = int((time.time() - started) * 1000)
            return Observation(call.id, call.name, bool(result.get("ok")),
                               output=output,
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
