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
    {
        "name": "issue_list",
        "description": "列出当前项目的 issue（编号 / 标题 / 状态）。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "issue_get",
        "description": "按编号读取 issue 详情：标题、正文、验收标准。",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "integer", "description": "issue 编号"}},
            "required": ["id"],
        },
    },
]

# 演示用的 issue 库（真实项目里这里换成 Jira / GitHub API 调用）
ISSUES = {
    12: {
        "title": "mean() 对空列表静默返回 0，应该抛错",
        "state": "open",
        "body": "调用 mean([]) 时返回 0，下游把它当成合法均值。期望与 median([]) 一致抛 ValueError。",
        "acceptance": "1) mean([]) 抛 ValueError；2) 现有 6 个用例全绿；3) 补一个空列表用例。",
    },
    13: {
        "title": "统计模块缺少标准差 stddev",
        "state": "open",
        "body": "需要一个与 variance 配套的 stddev，供报表使用。",
        "acceptance": "1) stddev([2,4,6]) ≈ 1.633；2) 空列表抛 ValueError；3) 补两个用例。",
    },
    14: {
        "title": "测试输出太长，日志里看不出哪个用例失败",
        "state": "closed",
        "body": "CI 日志被 -v 的输出淹没。",
        "acceptance": "默认 -q，失败时只打印失败用例。",
    },
}


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


def tool_issue_list(_: dict) -> str:
    return "\n".join(f"#{i} [{v['state']}] {v['title']}" for i, v in sorted(ISSUES.items()))


def tool_issue_get(args: dict) -> str:
    iid = int(args.get("id", 0))
    issue = ISSUES.get(iid)
    if issue is None:
        raise ValueError(f"没有 #{iid} 这个 issue")
    return (f"#{iid} {issue['title']}\n状态：{issue['state']}\n\n"
            f"正文：{issue['body']}\n\n验收标准：{issue['acceptance']}")


def dispatch(name: str, args: dict) -> str:
    if name == "workspace_stats":
        return tool_workspace_stats(args)
    if name == "note_add":
        return tool_note_add(args)
    if name == "issue_list":
        return tool_issue_list(args)
    if name == "issue_get":
        return tool_issue_get(args)
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
