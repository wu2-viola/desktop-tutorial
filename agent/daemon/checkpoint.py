"""checkpoint：每一步 turn 落盘，重启后从断点继续，而不是从第 1 步重来。

三件事必须一起做对：
1. **原子写**（tmp + os.replace）—— 写到一半被 kill 不会留下半个 JSON
2. **记录已执行的调用 id** —— resume 时这些工具不再跑第二遍（幂等）
3. **保留 history** —— 兜圈子判定不会因为重启而失忆
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

RUNNING = "running"
DONE = "done"
STOPPED = "stopped"
FAILED = "failed"
KILLED = "killed"


def default_state_dir() -> Path:
    """状态一律写用户目录，不污染工作区（和工作区外写入的规则一致）。"""
    return Path(os.environ.get("AGENT_STATE_DIR")
                or (Path.home() / ".desktop-tutorial" / "runs"))


@dataclass
class RunState:
    run_id: str
    task: str
    messages: list[dict] = field(default_factory=list)
    step: int = 0                      # 已完成的决策步数
    usage_total: int = 0
    executed_calls: list[str] = field(default_factory=list)
    history: list[list[str]] = field(default_factory=list)
    status: str = RUNNING
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    note: str = ""
    state_dir: str = ""               # 这个 run 落在哪个目录（进程间共享靠它）

    # ---- 序列化 ----
    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "RunState":
        known = {f for f in RunState.__dataclass_fields__}
        return RunState(**{k: v for k, v in d.items() if k in known})

    def path(self, state_dir: Path | None = None) -> Path:
        return Path(state_dir or self.state_dir or default_state_dir()) / f"{self.run_id}.json"

    def save(self, state_dir: Path | None = None) -> Path:
        self.updated_at = time.time()
        p = self.path(state_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, p)             # 原子替换：要么旧状态，要么新状态
        return p

    # ---- 读取 ----
    @staticmethod
    def load(state_dir: Path, run_id: str) -> "RunState":
        p = Path(state_dir) / f"{run_id}.json"
        if not p.exists():
            raise FileNotFoundError(f"没有这个 run：{run_id}（{p}）")
        return RunState.from_dict(json.loads(p.read_text(encoding="utf-8")))

    @staticmethod
    def latest(state_dir: Path, status: str | None = None) -> "RunState | None":
        runs = [RunState.from_dict(json.loads(p.read_text(encoding="utf-8")))
                for p in Path(state_dir).glob("*.json")]
        if status:
            runs = [r for r in runs if r.status == status]
        return max(runs, key=lambda r: r.updated_at) if runs else None

    @staticmethod
    def all_runs(state_dir: Path) -> list["RunState"]:
        runs = [RunState.from_dict(json.loads(p.read_text(encoding="utf-8")))
                for p in Path(state_dir).glob("*.json")]
        return sorted(runs, key=lambda r: r.updated_at)


def capture(state: RunState, messages, step: int, usage_total: int,
            executed: set[str], status: str = RUNNING) -> RunState:
    """把循环里的活状态拍平成可落盘的样子。"""
    state.messages = [m.to_dict() for m in messages]
    state.step = step
    state.usage_total = usage_total
    state.executed_calls = sorted(executed)
    state.status = status
    return state
