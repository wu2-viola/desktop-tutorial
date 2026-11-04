"""工具注册表 —— 四个工具的 schema 就是模型的说明书。

bash 把 N 个专用工具压成 1 个：工具越少，模型选错的概率越低。
"""
from __future__ import annotations

from .base import Interrupted, Tool, ToolContext
from .bash import BashTool
from .edit import EditTool
from .read import ReadTool
from .write import WriteTool

BUILTIN_TOOLS: dict[str, Tool] = {
    t.name: t for t in (ReadTool(), WriteTool(), EditTool(), BashTool())
}


def builtin_specs() -> list[dict]:
    return [t.spec() for t in BUILTIN_TOOLS.values()]


__all__ = ["Interrupted", "Tool", "ToolContext", "BUILTIN_TOOLS", "builtin_specs",
           "BashTool", "EditTool", "ReadTool", "WriteTool"]
