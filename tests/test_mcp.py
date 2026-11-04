"""MCP 断言：协议是真的 —— initialize / tools/list / tools/call 全走一遍。"""
import json

import pytest

from agent.tools import ToolContext
from mcp.client import load_mcp_tools

REPO = __import__("pathlib").Path(__file__).resolve().parent.parent


@pytest.fixture()
def mcp_env(tmp_path):
    conf = {"mcpServers": {"demo": {"command": "python",
                                    "args": [str(REPO / "mcp" / "demo_server.py")],
                                    "cwd": str(tmp_path)}}}
    (tmp_path / "mcp.json").write_text(json.dumps(conf), encoding="utf-8")
    tools, status = load_mcp_tools(tmp_path / "mcp.json", tmp_path)
    yield tools, status, tmp_path


def test_server_online_and_tools_listed(mcp_env):
    tools, status, _ = mcp_env
    assert status and status[0]["ok"] is True
    assert "mcp__demo__workspace_stats" in tools
    assert "mcp__demo__note_add" in tools


def test_names_carry_mcp_prefix(mcp_env):
    tools, _, _ = mcp_env
    assert all(name.startswith("mcp__demo__") for name in tools)


def test_call_workspace_stats(mcp_env):
    tools, _, tmp = mcp_env
    (tmp / "a.py").write_text("print(1)\nprint(2)\n", encoding="utf-8")
    r = tools["mcp__demo__workspace_stats"].run({}, ToolContext(tmp))
    assert r["ok"] and "Python 文件" in r["output"]


def test_call_note_add_writes_notes(mcp_env):
    tools, _, tmp = mcp_env
    r = tools["mcp__demo__note_add"].run({"text": "hello mcp"}, ToolContext(tmp))
    assert r["ok"]
    assert "hello mcp" in (tmp / "notes.md").read_text(encoding="utf-8")


def test_bad_server_reported_not_fatal(tmp_path):
    conf = {"mcpServers": {"broken": {"command": "python",
                                      "args": ["-c", "import sys; sys.exit(1)"],
                                      "cwd": str(tmp_path)}}}
    (tmp_path / "mcp.json").write_text(json.dumps(conf), encoding="utf-8")
    tools, status = load_mcp_tools(tmp_path / "mcp.json", tmp_path)
    assert tools == {}                                    # 没有工具进来
    assert status[0]["ok"] is False and status[0]["error"]  # 但状态被如实记录
