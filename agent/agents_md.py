"""AGENTS.md 注入：全局 → 项目，按顺序拼进 system prompt。

两层：
- 全局：~/.desktop-tutorial/AGENTS.md（跨项目偏好，可被 AGENT_GLOBAL_MD 覆盖）
- 项目：从工作区往上找最近的 AGENTS.md（最多 5 层）
全局那份不存在时回落到仓库自带的 docs/agents-global.md，
保证换一台机器 clone 下来跑，仍然是两层。
"""
from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def find_project_agents_md(workspace: Path, max_up: int = 5) -> Path | None:
    cur = Path(workspace).resolve()
    for _ in range(max_up + 1):
        f = cur / "AGENTS.md"
        if f.exists():
            return f
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def load_agents_md(workspace: Path) -> dict:
    """返回 {"text": 拼好的两段, "layers": [...], "bytes": int, "found": bool}。"""
    layers: list[str] = []
    parts: list[str] = []

    global_path = Path(os.environ.get("AGENT_GLOBAL_MD")
                       or (Path.home() / ".desktop-tutorial" / "AGENTS.md"))
    if not global_path.exists():
        global_path = REPO / "docs" / "agents-global.md"
    global_text = _read(global_path).strip()
    if global_text:
        layers.append("global")
        parts.append("[全局 AGENTS.md]\n" + global_text)

    project_path = find_project_agents_md(workspace)
    project_text = _read(project_path).strip() if project_path else ""
    if project_text:
        layers.append("project")
        parts.append(f"[项目 AGENTS.md：{project_path}]\n" + project_text)

    text = "\n\n".join(parts)
    return {"text": text, "layers": layers,
            "bytes": len(text.encode("utf-8")), "found": bool(layers)}


def system_block(info: dict) -> str:
    """注入 system prompt 的那一段（没有就返回空串，不占 token）。"""
    if not info["found"]:
        return ""
    return ("以下是这个仓库的 AGENTS.md（怎么跑、哪里不能碰），"
            "按它执行，不要自己猜项目结构：\n\n" + info["text"])
