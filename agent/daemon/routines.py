"""定时触发：routines.yaml（迷你解析器，不引 pyyaml）。

只认四行：
    routines:
      - name: 名字
        every_seconds: 60        # 或者 at: "09:30"
        skill: review-diff
        task: "要 agent 干什么"
解析器故意写得很笨 —— 认不出来的行直接报错，而不是静默忽略。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Routine:
    name: str
    task: str
    skill: str = ""
    every_seconds: int | None = None
    at: str | None = None
    last_fired: float = field(default=0.0, compare=False)


def parse_routines(text: str) -> list[Routine]:
    routines: list[Routine] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip() or line.strip() == "routines:":
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            if current:
                routines.append(Routine(**current))
            current = {}
            stripped = stripped[2:].strip()
        if current is None:
            raise ValueError(f"routines.yaml 结构不对：{raw!r}")
        if ":" not in stripped:
            raise ValueError(f"认不出这一行：{raw!r}")
        key, value = stripped.split(":", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key == "every_seconds":
            current[key] = int(value)
        elif key in ("name", "task", "skill", "at"):
            current[key] = value
        else:
            raise ValueError(f"未知字段：{key}")
    if current:
        routines.append(Routine(**current))
    for r in routines:
        if not r.every_seconds and not r.at:
            raise ValueError(f"routine {r.name} 既没有 every_seconds 也没有 at")
    return routines


def load_routines(path: Path) -> list[Routine]:
    p = Path(path)
    if not p.exists():
        return []
    return parse_routines(p.read_text(encoding="utf-8"))


class Scheduler:
    """到点判定。时钟可注入 —— 验收时不用真等 60 秒。"""

    def __init__(self, routines: list[Routine], clock=time.time):
        self.routines = routines
        self.clock = clock
        self._fired_at_day: dict[str, str] = {}
        now = clock()
        for r in routines:              # 从现在开始计时：启动不惊群，等一个周期再跑
            if r.last_fired <= 0:
                r.last_fired = now

    def due(self, now: float | None = None) -> list[Routine]:
        now = self.clock() if now is None else now
        fired: list[Routine] = []
        for r in self.routines:
            if r.every_seconds:
                if now - r.last_fired >= r.every_seconds:
                    r.last_fired = now
                    fired.append(r)
            elif r.at:
                today = time.strftime("%Y-%m-%d", time.localtime(now))
                if (time.strftime("%H:%M", time.localtime(now)) == r.at
                        and self._fired_at_day.get(r.name) != today):
                    self._fired_at_day[r.name] = today
                    r.last_fired = now
                    fired.append(r)
        return fired
