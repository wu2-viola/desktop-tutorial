"""write 工具：自动创建父目录；临时文件 + rename 做原子写。

最容易做错的两件事：
1. 忘了建父目录 → FileNotFoundError；
2. 直接 open(path,'w') 写一半崩了 → 文件损坏。先写临时文件再 os.replace 才是原子的。
"""
from __future__ import annotations

import os
import tempfile

from .base import guard, Tool, ToolContext


class WriteTool(Tool):
    name = "write"
    description = (
        "把完整内容写入工作区里的一个文件（覆盖式）。父目录不存在会自动创建；"
        "写入是原子的（先写临时文件再替换），不会留下写一半的文件。"
        "返回「原来多少行 → 现在多少行」。要改文件的一部分请用 edit。"
    )
    schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "相对工作区的文件路径"},
            "content": {"type": "string", "description": "完整的文件内容"},
        },
        "required": ["path", "content"],
    }

    @guard
    def run(self, args: dict, ctx: ToolContext) -> dict:
        ctx.check_interrupt()
        path = ctx.resolve_in_workspace(str(args.get("path", "")))
        content = str(args.get("content", ""))
        old_lines = len(path.read_text(encoding="utf-8", errors="replace").splitlines()) if path.exists() else 0

        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)          # 同分区 rename，原子生效
        finally:
            if os.path.exists(tmp):        # 中途出异常时不留垃圾
                os.unlink(tmp)

        new_lines = len(content.splitlines())
        verb = "覆盖" if old_lines else "新建"
        return {"ok": True,
                "output": f"{verb} {path.name}：原来 {old_lines} 行 → 现在 {new_lines} 行（{path}）"}
