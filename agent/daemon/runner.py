"""常驻进程：定时触发 + 事件触发 + 崩溃续跑 + 完成通知。

设计上它只是「循环的调度器」—— 不复制循环逻辑，续跑靠 checkpoint，幂等靠 executed_calls。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

from ..loop import AgentLoop
from ..skills import load_skills
from ..tools import BUILTIN_TOOLS
from .checkpoint import DONE, RUNNING, RunState, default_state_dir
from .notify import notify
from .routines import Routine, Scheduler, load_routines
from .scripted import ScriptedLongProvider
from .watch import DirectoryWatcher

REPO = Path(__file__).resolve().parent.parent.parent
EMPTY_STATS = {"triggers_fired": 0, "event_triggers_fired": 0,
               "notify_fired": 0, "runs": 0, "resumes": 0}


class Daemon:
    def __init__(self, workspace: Path, state_dir: Path | None = None, slow: float = 0.0,
                 hooks: bool = False, routines_path: Path | None = None,
                 watch_dir: Path | None = None, allow_toast: bool = True):
        self.workspace = Path(workspace)
        self.state_dir = Path(state_dir or default_state_dir())
        self.slow = slow
        self.hooks = hooks
        self.routines_path = Path(routines_path or (REPO / "routines.yaml"))
        self.watch_dir = Path(watch_dir or self.workspace)
        self.allow_toast = allow_toast
        self.stats_path = self.state_dir / "stats.json"
        self.stats = self._load_stats()

    # ---- 统计落盘（子进程之间共享） ----
    def _load_stats(self) -> dict:
        stats = dict(EMPTY_STATS)
        if self.stats_path.exists():
            try:
                stats.update(json.loads(self.stats_path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass
        return stats

    def _save_stats(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.stats_path.write_text(json.dumps(self.stats, ensure_ascii=False, indent=2),
                                   encoding="utf-8")

    def _loop(self, max_steps: int = 8) -> AgentLoop:
        return AgentLoop(ScriptedLongProvider(self.slow), BUILTIN_TOOLS, self.workspace,
                         max_steps=max_steps, enable_skills=True,
                         enable_hooks=self.hooks, enable_reviewer=False)

    def _finish(self, state: RunState, tools: int, text: str) -> dict:
        body = f"{state.task[:50]} —— {state.status}（第 {state.step} 步，{tools} 次工具调用）"
        n = notify("Desktop Agent", body, allow_toast=self.allow_toast,
                   log_path=self.state_dir / "notifications.log")
        if n["ok"]:
            self.stats["notify_fired"] += 1
            self._save_stats()
        return {"run_id": state.run_id, "status": state.status, "step": state.step,
                "tool_calls": tools, "executed_calls": len(state.executed_calls),
                "text": text, "notify": n}

    # ---- 跑一次完整任务 ----
    def run_task(self, task: str, run_id: str | None = None, max_steps: int = 8) -> dict:
        rid = run_id or f"run_{int(time.time())}_{uuid.uuid4().hex[:4]}"
        state = RunState(run_id=rid, task=task, state_dir=str(self.state_dir))
        text, tools = "", 0
        for ev in self._loop(max_steps).run(task, checkpoint=state):
            if ev.type == "tool_end":
                tools += 1
            elif ev.type == "final":
                text = ev.data["text"]
            elif ev.type in ("stopped", "error"):
                text = ev.data.get("reason") or ev.data.get("message") or ""
        self.stats["runs"] += 1
        self._save_stats()
        return self._finish(state, tools, text)

    # ---- 从断点续跑（幂等的关键） ----
    def resume(self, run_id: str | None = None, max_steps: int = 10) -> dict:
        state = (RunState.load(self.state_dir, run_id) if run_id
                 else RunState.latest(self.state_dir))
        if state is None:
            return {"resumed": False, "reason": "没有可续跑的 run"}
        if state.status == DONE:
            return {"resumed": False, "run_id": state.run_id, "step": state.step,
                    "executed_calls": len(state.executed_calls),
                    "reason": "已完成，幂等跳过：不重放任何工具"}

        resume_from = state.step + 1
        text, tools = "", 0
        for ev in self._loop(max_steps).run(state.task, checkpoint=state):
            if ev.type == "tool_end":
                tools += 1
            elif ev.type == "final":
                text = ev.data["text"]
        self.stats["resumes"] += 1
        self._save_stats()
        result = self._finish(state, tools, text)
        result.update({"resumed": True, "resume_from_step": resume_from,
                       "tools_this_round": tools})
        return result

    # ---- 定时 / 事件 ----
    def fire_routine(self, routine: Routine) -> dict:
        """到点跑一个 skill：有 scripts/ 就跑脚本，没有就唤醒循环跑一个短任务。"""
        self.stats["triggers_fired"] += 1
        self._save_stats()
        skills = {s.name: s for s in load_skills(REPO / "skills")}
        skill = skills.get(routine.skill)
        scripts = sorted((skill.path / "scripts").glob("*.py")) if skill and skill.has_scripts else []
        if scripts:
            proc = subprocess.run([sys.executable, "-X", "utf8", str(scripts[0]), "--stat"],
                                  cwd=REPO, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=60)
            ok = proc.returncode == 0
            detail = (proc.stdout or proc.stderr)[:200]
            action = "script"
        else:
            r = self.run_task(routine.task, max_steps=6)   # 无脚本的技能：真唤醒一次循环
            ok, detail, action = r["status"] == DONE, r["text"][:200], "task"
        notify("Desktop Agent · 定时触发",
               f"{routine.name} → {routine.skill or 'task'}", allow_toast=self.allow_toast,
               log_path=self.state_dir / "notifications.log")
        self.stats["notify_fired"] += 1
        self._save_stats()
        return {"routine": routine.name, "skill": routine.skill, "action": action,
                "ok": ok, "detail": detail}

    def start(self, duration: float = 20.0, tick: float = 0.2) -> dict:
        """常驻：到点跑 routine，文件变了进队列并消费，每次结束发通知。"""
        scheduler = Scheduler(load_routines(self.routines_path))
        watcher = DirectoryWatcher(self.watch_dir)
        fired: list[dict] = []
        end = time.time() + duration
        while time.time() < end:
            for routine in scheduler.due():
                fired.append(self.fire_routine(routine))
            for _ in watcher.poll():
                self.stats["event_triggers_fired"] += 1
                self._save_stats()
                event = watcher.consume()
                fired.append({"event": event, "action": "queued"})
            time.sleep(tick)
        return {"triggers_fired": self.stats["triggers_fired"],
                "event_triggers_fired": self.stats["event_triggers_fired"], "fired": fired}
