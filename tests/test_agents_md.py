"""AGENTS.md 注入：两层、按「全局 → 项目」拼、体积有上限。"""
from pathlib import Path

import pytest

from agent.agents_md import find_project_agents_md, load_agents_md, system_block

REPO = Path(__file__).resolve().parent.parent


def test_two_layers_global_then_project(tmp_path):
    info = load_agents_md(REPO / "workspace")
    assert info["found"] and info["layers"] == ["global", "project"]
    assert info["text"].index("[全局 AGENTS.md]") < info["text"].index("[项目 AGENTS.md")


def test_project_file_found_from_subdir(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# 项目地图\n入口 app.py\n", encoding="utf-8")
    (tmp_path / "sub" / "deep").mkdir(parents=True)
    found = find_project_agents_md(tmp_path / "sub" / "deep")
    assert found == tmp_path / "AGENTS.md"


def test_custom_global_via_env(tmp_path, monkeypatch):
    g = tmp_path / "global.md"
    g.write_text("# 全局偏好\n- 中文回答\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_GLOBAL_MD", str(g))
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "AGENTS.md").write_text("# 地图\n", encoding="utf-8")
    info = load_agents_md(tmp_path / "proj")
    assert info["layers"] == ["global", "project"]
    assert "中文回答" in info["text"]


def test_bytes_under_limit():
    info = load_agents_md(REPO / "workspace")
    assert info["bytes"] <= 12000, "AGENTS.md 超过 300 行就该拆了"


def test_system_block_is_map_not_doc():
    block = system_block(load_agents_md(REPO / "workspace"))
    assert "构建与测试" in block and "python -m pytest tests -q" in block
    assert "```" not in block            # 不贴代码片段


def test_missing_layers_still_works(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_GLOBAL_MD", str(tmp_path / "nope.md"))
    empty = tmp_path / "empty"
    empty.mkdir()
    info = load_agents_md(empty)
    assert info["layers"] in ([], ["global"])     # 至少不抛异常
    assert isinstance(info["bytes"], int)
