"""最小但真实的 MCP server：stdio 上按行收发 JSON-RPC。

提供两个工具：
  workspace_stats —— 统计工作区文件数 / 行数
  note_add        —— 往 notes.md 追加一条笔记
它验证的是协议本身：任何 MCP 宿主（不止本作业）都能这样接上它。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

CWD = Path.cwd()

TOOLS = [
    {
        "name": "workspace_stats",
        "description": "统计当前工作区：文件数、目录数、代码总行数、Python 文件数。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "note_add",
        "description": "往工作区的 notes.md 追加一条笔记（自动建文件）。",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "笔记内容"}},
            "required": ["text"],
        },
    },
]


def tool_workspace_stats(_: dict) -> str:
    files = dirs = py = lines = 0
    for p in CWD.rglob("*"):
        if any(part.startswith(".") or part == "__pycache__" for part in p.parts):
            continue
        if p.is_dir():
            dirs += 1
        else:
            files += 1
            if p.suffix == ".py":
                py += 1
                try:
                    lines += len(p.read_text(encoding="utf-8", errors="replace").splitlines())
                except OSError:
                    pass
    return (f"工作区统计：文件 {files} 个，目录 {dirs} 个；"
            f"Python 文件 {py} 个，共 {lines} 行。")


def tool_note_add(args: dict) -> str:
    text = str(args.get("text", "")).strip()
    if not text:
        raise ValueError("text 不能为空")
    notes = CWD / "notes.md"
    with notes.open("a", encoding="utf-8") as f:
        f.write(f"## {time.strftime('%Y-%m-%d %H:%M:%S')}\n{text}\n\n")
    return f"已写入 {notes.name}（现 {len(notes.read_text(encoding='utf-8').splitlines())} 行）"


def dispatch(name: str, args: dict) -> str:
    if name == "workspace_stats":
        return tool_workspace_stats(args)
    if name == "note_add":
        return tool_note_add(args)
    raise ValueError(f"未知工具：{name}")


def main() -> None:
    # Windows 上默认 GBK —— 协议双方必须钉死 UTF-8，否则中文工具结果必炸
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    for line in sys.stdin:                    # 按行读 JSON-RPC，处理完按行写回
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = req.get("method", "")
        rid = req.get("id")
        if rid is None:                       # 通知（如 initialized），无需应答
            continue
        try:
            if method == "initialize":
                result = {"protocolVersion": "2024-11-05",
                          "capabilities": {"tools": {}},
                          "serverInfo": {"name": "demo-server", "version": "1.0.0"}}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = req.get("params", {})
                text = dispatch(params.get("name", ""), params.get("arguments") or {})
                result = {"content": [{"type": "text", "text": text}]}
            else:
                raise ValueError(f"未知方法：{method}")
            resp = {"jsonrpc": "2.0", "id": rid, "result": result}
        except Exception as e:
            resp = {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32000, "message": str(e)}}
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
