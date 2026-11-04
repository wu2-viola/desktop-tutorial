"""read 工具：按行返回带行号，读不完告诉你还有 N 行，图片走多模态块。

最容易做错的两件事（也是本实现重点防的）：
1. 超大文件一次全塞给模型 → 必须分页；
2. 图片 base64 塞进 text 字段 → 模型看到一堆乱码，必须走内容块。
"""
from __future__ import annotations

import base64
import mimetypes

from .base import Tool, ToolContext

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
MAX_BYTES = 5 * 1024 * 1024


class ReadTool(Tool):
    name = "read"
    description = (
        "读取工作区里的一个文件。文本按行返回并带行号；文件太大时自动分页，"
        "并在结尾告诉你还有多少行。图片（png/jpg/gif/webp/bmp）返回 base64 "
        "多模态内容块而不是文本。"
    )
    schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "相对工作区的文件路径"},
            "offset": {"type": "integer", "description": "起始行号（1 起），默认 1"},
            "limit": {"type": "integer", "description": "最多读多少行，默认 2000，上限 2000"},
        },
        "required": ["path"],
    }

    def run(self, args: dict, ctx: ToolContext) -> dict:
        ctx.check_interrupt()
        path = ctx.resolve_in_workspace(str(args.get("path", "")))
        if not path.exists():
            return {"ok": False, "output": f"文件不存在：{path}"}
        if path.is_dir():
            return {"ok": False, "output": f"这是一个目录，请用 bash ls 或读目录下的文件：{path}"}

        raw = path.read_bytes()
        if path.suffix.lower() in IMAGE_EXTS:
            if len(raw) > MAX_BYTES:
                return {"ok": False, "output": f"图片超过 5MB，拒绝读取：{path}"}
            mime = mimetypes.guess_type(str(path))[0] or "image/png"
            b64 = base64.b64encode(raw).decode()
            blocks = [{"type": "text", "text": f"[图片 {path.name}，{len(raw)} 字节，已按多模态内容块返回]"},
                      {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]
            return {"ok": True, "output": blocks[0]["text"], "blocks": blocks}

        if b"\x00" in raw[:4096]:
            return {"ok": False, "output": "这像是二进制文件，文本读取没有意义；请用 bash 处理。"}

        offset = max(1, int(args.get("offset") or 1))
        limit = min(2000, max(1, int(args.get("limit") or 2000)))
        lines = raw.decode("utf-8", errors="replace").splitlines()
        total = len(lines)
        if offset > total:
            return {"ok": False, "output": f"offset={offset} 超出文件行数（共 {total} 行）"}

        chunk = lines[offset - 1: offset - 1 + limit]
        numbered = "\n".join(f"{offset + i:>6}\t{line}" for i, line in enumerate(chunk))
        remaining = total - (offset - 1 + len(chunk))
        if remaining > 0:
            numbered += f"\n……（还有 {remaining} 行，用 offset={offset + len(chunk)} 继续读）"
        return {"ok": True, "output": numbered}
