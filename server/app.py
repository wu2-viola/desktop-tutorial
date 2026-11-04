"""FastAPI 后端：/api/tree /api/file /api/run/stream(SSE) /ws。

顺序问题：后端先跑通再做界面 —— 关掉前端，curl -N 也要能看到事件流：
    curl -N "http://127.0.0.1:8765/api/run/stream?task=读一下 workspace/stats.py"
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from agent.config import get_api_key, load_config, save_config
from agent.loop import AgentLoop
from agent.providers import DeepSeekProvider, MockProvider, Provider
from agent.tools import BUILTIN_TOOLS, Tool, ToolContext

app = FastAPI(title="desktop-tutorial")

STATE: dict = {
    "workspace": Path(__file__).resolve().parent.parent / "workspace",
    "mcp_tools": {},
    "mcp_status": [],
    "interrupt": threading.Event(),
    "busy": False,
}


def init(workspace: Path, mcp_json: Path | None = None) -> None:
    """启动时调用：钉死工作区，加载 MCP server。"""
    STATE["workspace"] = workspace.resolve()
    if mcp_json is not None:
        from mcp.client import load_mcp_tools
        tools, status = load_mcp_tools(mcp_json, STATE["workspace"])
        STATE["mcp_tools"] = tools
        STATE["mcp_status"] = status


def _all_tools() -> dict[str, Tool]:
    return {**BUILTIN_TOOLS, **STATE["mcp_tools"]}


def _make_provider() -> Provider:
    cfg = load_config()
    key = get_api_key()
    if key:
        return DeepSeekProvider(key, cfg["base_url"], cfg["model"])
    return MockProvider()          # 没配 Key 也能跑：离线 mock 走完整循环


# ---------- 配置（Key 只进不读） ----------
@app.get("/api/config")
def get_config():
    cfg = load_config()
    cfg["mcp"] = STATE["mcp_status"]
    return cfg


@app.post("/api/config")
async def set_config(request: Request):
    body = await request.json()
    save_config(api_key=body.get("api_key"),
                base_url=body.get("base_url"), model=body.get("model"))
    return load_config()           # 只回掩码，不回明文


# ---------- 资源管理器 ----------
@app.get("/api/tree")
def tree(path: str = ""):
    root = STATE["workspace"]
    target = (root / path).resolve() if path else root
    if root not in target.parents and target != root:
        raise HTTPException(400, "路径越出工作区")
    if not target.exists():
        raise HTTPException(404, "目录不存在")
    entries = []
    for p in sorted(target.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        if p.name.startswith(".") or p.name == "__pycache__":
            continue
        entries.append({"name": p.name, "type": "dir" if p.is_dir() else "file",
                        "path": str(p.relative_to(root)).replace("\\", "/")})
    return {"path": path, "entries": entries}


@app.get("/api/file")
def read_file(path: str, offset: int = 1, limit: int = 2000):
    tool = BUILTIN_TOOLS["read"]
    result = tool.run({"path": path, "offset": offset, "limit": limit},
                      ToolContext(STATE["workspace"]))
    return result


# ---------- 运行（SSE 事件流） ----------
def _sse(events) -> StreamingResponse:
    def gen():
        for ev in events:
            yield f"data: {json.dumps(ev.to_json(), ensure_ascii=False)}\n\n"
        yield "data: {\"type\": \"__done__\"}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/api/run/stream")
def run_stream(task: str = Query(...), skills: int = 1, hooks: int = 1):
    if STATE["busy"]:
        raise HTTPException(409, "已有任务在跑，先等它结束或点停止")
    STATE["busy"] = True
    interrupt = threading.Event()
    STATE["interrupt"] = interrupt
    loop = AgentLoop(_make_provider(), _all_tools(), STATE["workspace"],
                     enable_skills=bool(skills), enable_hooks=bool(hooks))

    def gen():
        try:
            yield f"data: {json.dumps({'type': 'provider', 'name': loop.provider.name}, ensure_ascii=False)}\n\n"
            caps = {"type": "capabilities",
                    "skills": [s.name for s in loop.skills],
                    "hooks": loop.hooks is not None,
                    "agents_md": loop.agents_md["layers"]}
            yield f"data: {json.dumps(caps, ensure_ascii=False)}\n\n"
            for ev in loop.run(task, interrupt):
                yield f"data: {json.dumps(ev.to_json(), ensure_ascii=False)}\n\n"
        finally:
            STATE["busy"] = False

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.post("/api/interrupt")
def interrupt():
    STATE["interrupt"].set()
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True, "has_key": bool(get_api_key())}


# ui/ 挂在最后，/api/* 优先
app.mount("/", StaticFiles(directory=str(Path(__file__).parent.parent / "ui"),
                           html=True), name="ui")
