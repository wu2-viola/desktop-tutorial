"""工具基类与执行上下文（含中断信号）。

每个工具只做一件事，语义写进 description —— description 就是提示词，
是写给「没见过你代码的人」和模型一起看的。
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from functools import wraps
from pathlib import Path


class Interrupted(Exception):
    """用户点了「停止」。工具在耗时操作前后自查，循环捕获后收尾。"""


class ToolContext:
    """一次运行共享的上下文：工作区根目录 + 中断信号 + 已读文件记录。"""

    def __init__(self, workspace: Path, interrupt: threading.Event | None = None):
        self.workspace = workspace.resolve()
        self.interrupt = interrupt or threading.Event()
        self.read_paths: set[str] = set()        # edit 前必须 read 过同一文件
        self.loaded_skills: set[str] = set()     # 渐进披露：记录已注入正文的技能

    def check_interrupt(self) -> None:
        if self.interrupt.is_set():
            raise Interrupted()

    def resolve_in_workspace(self, path: str) -> Path:
        """把相对路径钉在工作区内；越界（.. 逃出工作区）直接拒绝。"""
        p = (self.workspace / path).resolve()
        root = self.workspace
        if not (p == root or root in p.parents):
            raise ValueError(f"路径越出工作区，拒绝访问：{path}")
        return p


class Tool(ABC):
    name: str = ""
    description: str = ""
    schema: dict = {}               # JSON Schema，模型的选择说明书

    @abstractmethod
    def run(self, args: dict, ctx: ToolContext) -> dict:
        """返回 {"ok": bool, "output": str, ...}；抛异常也会被循环接住变成失败观察。"""

    def spec(self) -> dict:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description,
                             "parameters": self.schema}}


def guard(fn):
    """把「路径越出工作区」这类可预期错误变成失败观察，而不是异常。"""

    @wraps(fn)
    def wrapper(self, args: dict, ctx: ToolContext) -> dict:
        try:
            return fn(self, args, ctx)
        except Interrupted:
            raise
        except ValueError as e:
            return {"ok": False, "output": str(e)}

    return wrapper
