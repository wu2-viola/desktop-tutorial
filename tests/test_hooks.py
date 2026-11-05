"""Hooks 断言：软的是建议，硬的必须是代码 —— 拒绝要给替代方案，回注只给三行。"""
from pathlib import Path

import pytest

from agent.hooks import HookEngine
from agent.inspect import _seed_demo_workspace

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture()
def ws(tmp_path):
    _seed_demo_workspace(tmp_path)       # 从 HEAD 取 bug 版，不依赖工作区当前状态
    return tmp_path


def test_deny_secret_files_with_reason(tmp_path):
    e = HookEngine(tmp_path)
    for path in (".env", ".env.local", "deploy.pem", "server.key"):
        d = e.pre("write", {"path": path})
        assert d and "密钥不入库" in d["reason"], path


def test_deny_dangerous_commands_with_alternatives(tmp_path):
    e = HookEngine(tmp_path)
    cases = {
        "rm -rf build/": ("git clean -nd", "git restore"),
        "git push --force origin main": ("git revert",),
        "git reset --hard HEAD~1": ("git stash", "git restore"),
    }
    for cmd, words in cases.items():
        d = e.pre("bash", {"command": cmd})
        assert d, cmd
        assert any(w in d["reason"] for w in words), (cmd, d["reason"])


def test_allow_normal_operations(tmp_path):
    e = HookEngine(tmp_path)
    assert e.pre("write", {"path": "agent/loop.py"}) is None
    assert e.pre("bash", {"command": "python -m pytest -q"}) is None
    assert e.pre("read", {"path": ".env"}) is None          # 只拦写，不拦读


def test_post_runs_tests_and_injects_three_lines(ws):
    e = HookEngine(ws)
    bug = "        return 0            # BUG：空列表应当抛错，而不是静默返回 0"
    (ws / "stats.py").write_text(
        (ws / "stats.py").read_text(encoding="utf-8").replace(
            bug, "        return 0.9 * total / len(nums)  # 故意改错"), encoding="utf-8")
    note = e.post("edit", {"path": "stats.py"})
    assert note and "自动测试红了" in note
    lines = note.splitlines()[1:]
    assert len(lines) == 3, lines
    assert "红：" in lines[0] and "期望：" in lines[1] and "实际：" in lines[2]
    assert e.stats["red"] == 1 and e.stats["injected_lines"] == 3


def test_red_to_green_counted(ws):
    e = HookEngine(ws)
    (ws / "stats.py").write_text(
        (ws / "stats.py").read_text(encoding="utf-8").replace(
            "        return 0            # BUG：空列表应当抛错，而不是静默返回 0",
            '        raise ValueError("mean() of empty sequence")'), encoding="utf-8")
    assert e.post("edit", {"path": "stats.py"}) is None     # 先绿
    assert e.stats["green"] == 1 and e.stats["red_to_green"] == 0


def test_post_only_for_write_and_edit(ws):
    e = HookEngine(ws)
    assert e.post("read", {"path": "stats.py"}) is None
    assert e.stats["runs"] == 0


def test_no_tests_no_noise(tmp_path):
    e = HookEngine(tmp_path)
    assert e.post("write", {"path": "x.py"}) is None
    assert e.stats["runs"] == 0
