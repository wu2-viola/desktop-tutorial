"""server 层断言：tree / file / config 不回传明文 / SSE 完整事件流。"""
import json

import pytest
from fastapi.testclient import TestClient

import server.app as srv


@pytest.fixture()
def client(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("l1\nl2\nl3\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    # 拷入演示工作区：离线 mock 的剧本要在这里跑通 read→edit→bash
    import shutil
    demo = srv.Path(__file__).resolve().parent.parent / "workspace"
    for f in ("stats.py", "test_stats.py"):
        shutil.copy(demo / f, tmp_path / f)
    srv.STATE["workspace"] = tmp_path
    srv.STATE["mcp_tools"] = {}
    srv.STATE["mcp_status"] = [{"server": "demo", "ok": True, "error": None,
                                "tools": ["mcp__demo__note_add"]}]
    srv.STATE["busy"] = False
    with TestClient(srv.app) as c:
        yield c, tmp_path


def test_health(client):
    c, _ = client
    assert c.get("/api/health").json()["ok"] is True


def test_tree_lists_entries(client):
    c, tmp = client
    data = c.get("/api/tree").json()
    names = [e["name"] for e in data["entries"]]
    assert "a.txt" in names and "sub" in names
    sub = [e for e in data["entries"] if e["name"] == "sub"][0]
    assert sub["type"] == "dir"


def test_file_returns_numbered_lines(client):
    c, _ = client
    data = c.get("/api/file", params={"path": "a.txt"}).json()
    assert data["ok"] and "l2" in data["output"] and "还有 0 行" not in data["output"]


def test_file_escape_refused(client):
    c, _ = client
    data = c.get("/api/file", params={"path": "../x.txt"}).json()
    assert data["ok"] is False


def test_config_post_never_returns_plaintext(client, monkeypatch, tmp_path):
    c, _ = client
    monkeypatch.setattr(srv, "get_api_key", lambda: "")
    import agent.config as config
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / ".dt")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / ".dt" / "config.json")
    r = c.post("/api/config", json={"api_key": "sk-plain-text-key-000"}).json()
    assert "sk-plain-text-key-000" not in json.dumps(r)      # 明文不出现在任何响应里
    assert r["has_key"] is True


def test_run_stream_full_pipeline(client):
    c, _ = client
    body = c.get("/api/run/stream", params={"task": "离线演示"}).text
    assert "provider" in body
    assert "tool_end" in body
    assert "final" in body
    assert body.count("data: ") >= 5                          # 事件是一条条流出来的


def test_interrupt_endpoint(client):
    c, _ = client
    assert c.post("/api/interrupt").json()["ok"] is True
    assert srv.STATE["interrupt"].is_set()
