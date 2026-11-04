"""edit 工具：精确字符串替换 + 唯一性检查 —— 出现 2 次就报错，不许猜。

这是四个工具里最需要想清楚的，也是 Claude Code 的核心工具。
做成「模糊匹配」或「整文件重写」的代价：改一个字符，整个文件重排 —— 本实现拒绝这么做。
"""
from __future__ import annotations

import difflib

from .base import guard, Tool, ToolContext


def _atomic_write(path, content: str) -> None:
    import os
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class EditTool(Tool):
    name = "edit"
    description = (
        "在工作区的一个文件里做精确字符串替换：old 必须在文件中唯一，"
        "出现 0 次或多次都会报错并列出行号，绝不猜测。确需多处替换时用 replace_all=true。"
        "返回最小 diff。"
    )
    schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "相对工作区的文件路径"},
            "old": {"type": "string", "description": "要被替换的精确原文（含足够上下文以保证唯一）"},
            "new": {"type": "string", "description": "替换后的内容"},
            "replace_all": {"type": "boolean", "description": "确有多处相同内容要一起替换时才设 true"},
        },
        "required": ["path", "old", "new"],
    }

    @guard
    def run(self, args: dict, ctx: ToolContext) -> dict:
        ctx.check_interrupt()
        path = ctx.resolve_in_workspace(str(args.get("path", "")))
        if not path.exists():
            return {"ok": False, "output": f"文件不存在：{path}"}
        old = str(args.get("old", ""))
        new = str(args.get("new", ""))
        if not old:
            return {"ok": False, "output": "old 为空 —— 空替换没有意义，请用 write 新建文件。"}

        text = path.read_text(encoding="utf-8", errors="replace")
        count = text.count(old)
        if count == 0:
            return {"ok": False, "output": "找不到要替换的字符串（0 次）。先 read 确认原文，注意空格与缩进。"}
        if count > 1 and not args.get("replace_all"):
            hits = [i + 1 for i, line in enumerate(text.splitlines()) if old in line]
            return {"ok": False,
                    "output": f"old 出现 {count} 次（行 {hits}），不唯一，拒绝替换。"
                              f"请补充上下文使它唯一，或确认后用 replace_all=true。"}


        new_text = text.replace(old, new) if args.get("replace_all") else text.replace(old, new, 1)
        _atomic_write(path, new_text)

        diff = list(difflib.unified_diff(text.splitlines(), new_text.splitlines(),
                                         lineterm="", n=1))[2:12]
        return {"ok": True,
                "output": f"已替换 {count if args.get('replace_all') else 1} 处。\n" + "\n".join(diff)}
