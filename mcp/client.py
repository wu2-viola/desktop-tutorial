"""MCP 客户端：stdio JSON-RPC，工具名加 mcp__ 前缀。

MCP 的全部理由：工具是协议，不是代码。把接口写给「没见过你代码的人」看，
人和模型都省事 —— 一个 server 的工具，任何宿主都能用。
"""
from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from agent.tools import Tool, ToolContext

MCP_PREFIX = "mcp__"


class MCPError(Exception):
    pass


class MCPClient:
    """一个 MCP server 进程的连接：initialize → tools/list → tools/call。"""

    def __init__(self, name: str, command: str, args: list[str], cwd: Path):
        self.name = name
        if command in ("python", "python3"):
            if getattr(sys, "frozen", False):
                # 打包后没有 python 命令：内置 demo server 变成 exe 自己的一个模式
                command = sys.executable
                args = ["--mcp-server"]
            else:
                command = sys.executable
        self.proc = subprocess.Popen(
            [command, *args], cwd=str(cwd),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
        self._resp: "queue.Queue[dict]" = queue.Queue()
        self._next_id = 0
        self._lock = threading.Lock()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self.tools: list[dict] = []

    # ---- 底层 JSON-RPC ----
    def _read_loop(self) -> None:
        for line in self.proc.stdout:            # MCP stdio：按行分隔的 JSON-RPC
            line = line.strip()
            if not line:
                continue
            try:
                self._resp.put(json.loads(line))
            except json.JSONDecodeError:
                continue

    def _rpc(self, method: str, params: dict | None = None,
             timeout: float = 15.0) -> dict:
        with self._lock:
            self._next_id += 1
            rid = self._next_id
            req = {"jsonrpc": "2.0", "id": rid, "method": method}
            if params is not None:
                req["params"] = params
            self.proc.stdin.write(json.dumps(req) + "\n")
            self.proc.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                msg = self._resp.get(timeout=0.2)
            except queue.Empty:
                continue
            if msg.get("id") == rid:
                if "error" in msg:
                    raise MCPError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            # 其他 id / 通知：放回不匹配就丢弃（通知没有 id，本实现忽略）
        raise MCPError(f"{method} 超时（{timeout}s）")

    # ---- MCP 生命周期 ----
    def initialize(self) -> None:
        self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "desktop-tutorial", "version": "1.0.0"},
        }, timeout=10)
        self._notify("notifications/initialized")

    def _notify(self, method: str, params: dict | None = None) -> None:
        req = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            req["params"] = params
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()

    def list_tools(self) -> list[dict]:
        result = self._rpc("tools/list")
        self.tools = result.get("tools", [])
        return self.tools

    def call_tool(self, name: str, arguments: dict) -> str:
        result = self._rpc("tools/call", {"name": name, "arguments": arguments},
                           timeout=30)
        parts = []
        for block in result.get("content", []):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts) or "(空结果)"

    def close(self) -> None:
        try:
            self.proc.stdin.close()
            self.proc.terminate()
            self.proc.wait(timeout=3)
        except Exception:
            pass


class MCPTool(Tool):
    """把一个远端 MCP 工具包成本地 Tool，名字带 mcp__ 前缀以便区分来源。"""

    def __init__(self, server: str, info: dict, client: MCPClient):
        self._client = client
        self._server = server
        self.name = f"{MCP_PREFIX}{server}__{info['name']}"
        self.description = f"[MCP:{server}] {info.get('description', '')}"
        self.schema = info.get("inputSchema", {"type": "object", "properties": {}})

    def run(self, args: dict, ctx: ToolContext) -> dict:
        ctx.check_interrupt()
        try:
            output = self._client.call_tool(self.name.split("__", 2)[2], args)
            return {"ok": True, "output": output}
        except MCPError as e:
            return {"ok": False, "output": f"MCP 调用失败：{e}"}


def load_mcp_tools(mcp_json: Path, workspace: Path) -> tuple[dict[str, Tool], list[dict]]:
    """按 mcp.json 启动所有 server，返回 (工具表, 状态列表)。

    单个 server 起不来不算致命 —— 记录状态，其余照常工作。
    """
    tools: dict[str, Tool] = {}
    status: list[dict] = []
    if not mcp_json.exists():
        return tools, status
    try:
        conf = json.loads(mcp_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return tools, [{"server": "(mcp.json)", "ok": False, "error": f"解析失败：{e}",
                        "tools": []}]

    for name, cfg in conf.get("mcpServers", {}).items():
        entry = {"server": name, "ok": False, "error": None, "tools": []}
        try:
            cwd_cfg = str(cfg.get("cwd") or "").strip()
            cwd = workspace if cwd_cfg in ("", ".") \
                else (mcp_json.parent / cwd_cfg).resolve()
            client = MCPClient(name, cfg["command"], cfg.get("args", []), cwd)
            client.initialize()
            for info in client.list_tools():
                tools[f"{MCP_PREFIX}{name}__{info['name']}"] = MCPTool(name, info, client)
                entry["tools"].append(f"{MCP_PREFIX}{name}__{info['name']}")
            entry["ok"] = True
        except Exception as e:
            entry["error"] = str(e)
        status.append(entry)
    return tools, status
