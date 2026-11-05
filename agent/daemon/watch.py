"""事件触发：轮询目录，变化进队列。

作业允许用 watchdog，但项目有一条自我约束「只用标准库」——
轮询 mtime+size 的代价是 0.2s 延迟，收益是少一个依赖、打包不变大、Windows 上不用管句柄。
"""
from __future__ import annotations

from pathlib import Path

IGNORE_PARTS = {"__pycache__", ".git", "node_modules", "dist", "build"}


class DirectoryWatcher:
    def __init__(self, root: Path, suffixes: tuple[str, ...] = (".py", ".md", ".txt"),
                 queue_max: int = 100):
        self.root = Path(root)
        self.suffixes = suffixes
        self.queue_max = queue_max
        self.queue: list[dict] = []
        self.snapshot = self._scan()          # 启动先拍一张，避免把自己启动当变化

    def _scan(self) -> dict[str, tuple[int, int]]:
        snap: dict[str, tuple[int, int]] = {}
        if not self.root.exists():
            return snap
        for p in self.root.rglob("*"):
            if not p.is_file() or IGNORE_PARTS & set(p.parts):
                continue
            if self.suffixes and p.suffix not in self.suffixes:
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            snap[str(p.relative_to(self.root))] = (st.st_mtime_ns, st.st_size)
        return snap

    def poll(self) -> list[dict]:
        """返回本次变化并用队列去重：同一个文件反复抖动只留最新一条。"""
        current = self._scan()
        events = [{"path": k, "event": "modified"}
                  for k, v in current.items() if k in self.snapshot and self.snapshot[k] != v]
        events += [{"path": k, "event": "created"}
                   for k in current if k not in self.snapshot]
        events += [{"path": k, "event": "deleted"}
                   for k in self.snapshot if k not in current]
        self.snapshot = current
        for ev in events:
            self.queue = [q for q in self.queue if q["path"] != ev["path"]]
            self.queue.append(ev)
        del self.queue[:-self.queue_max]
        return events

    def consume(self) -> dict | None:
        return self.queue.pop(0) if self.queue else None
