"""四个工具的语义断言 —— 每一条都对应一个真实会踩的坑。"""
import subprocess
import sys

import pytest

from agent.tools import BUILTIN_TOOLS, ToolContext


@pytest.fixture()
def ctx(tmp_path):
    return ToolContext(tmp_path)


def lines(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ---------- read ----------
def test_read_line_numbers_and_paging(ctx, tmp_path):
    lines(tmp_path, "a.txt", "\n".join(f"line{i}" for i in range(1, 51)))
    r = BUILTIN_TOOLS["read"].run({"path": "a.txt", "offset": 1, "limit": 20}, ctx)
    assert r["ok"] and "line1" in r["output"]
    assert "还有 30 行" in r["output"] and "offset=21" in r["output"]


def test_read_offset_beyond_eof(ctx, tmp_path):
    lines(tmp_path, "a.txt", "only one line")
    r = BUILTIN_TOOLS["read"].run({"path": "a.txt", "offset": 100}, ctx)
    assert not r["ok"] and "超出" in r["output"]


def test_read_missing_and_dir(ctx, tmp_path):
    assert not BUILTIN_TOOLS["read"].run({"path": "nope.txt"}, ctx)["ok"]
    (tmp_path / "d").mkdir()
    assert not BUILTIN_TOOLS["read"].run({"path": "d"}, ctx)["ok"]


def test_read_binary_refused(ctx, tmp_path):
    (tmp_path / "x.bin").write_bytes(b"\x00\x01binary")
    r = BUILTIN_TOOLS["read"].run({"path": "x.bin"}, ctx)
    assert not r["ok"] and "二进制" in r["output"]


def test_read_image_returns_multimodal_block_not_text(ctx, tmp_path):
    # 最小 PNG（1x1 像素）：base64 必须进内容块，不能塞进 text 字段
    (tmp_path / "dot.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89")
    r = BUILTIN_TOOLS["read"].run({"path": "dot.png"}, ctx)
    assert r["ok"] and r["blocks"]
    img = [b for b in r["blocks"] if b["type"] == "image_url"]
    assert img and img[0]["image_url"]["url"].startswith("data:image/png;base64,")


# ---------- write ----------
def test_write_creates_parents_and_counts(ctx, tmp_path):
    r = BUILTIN_TOOLS["write"].run({"path": "deep/nested/new.txt", "content": "a\nb\nc"}, ctx)
    assert r["ok"] and (tmp_path / "deep/nested/new.txt").exists()
    assert "新建" in r["output"] and "3 行" in r["output"]


def test_write_overwrite_reports_lines(ctx, tmp_path):
    lines(tmp_path, "f.txt", "1\n2\n3")
    r = BUILTIN_TOOLS["write"].run({"path": "f.txt", "content": "x"}, ctx)
    assert r["ok"] and "原来 3 行" in r["output"] and "现在 1 行" in r["output"]


def test_write_rejects_escape(ctx):
    r = BUILTIN_TOOLS["write"].run({"path": "../../evil.txt", "content": "x"}, ctx)
    assert not r["ok"] and "越出工作区" in r["output"]


# ---------- edit ----------
def test_edit_unique_replace_with_diff(ctx, tmp_path):
    lines(tmp_path, "c.py", "def f():\n    return 1\n")
    r = BUILTIN_TOOLS["edit"].run({"path": "c.py", "old": "return 1", "new": "return 2"}, ctx)
    assert r["ok"] and "return 2" in (tmp_path / "c.py").read_text(encoding="utf-8")
    assert "+" in r["output"]          # 带最小 diff


def test_edit_not_unique_refuses_and_lists_lines(ctx, tmp_path):
    lines(tmp_path, "d.txt", "same\nmid\nsame\n")
    r = BUILTIN_TOOLS["edit"].run({"path": "d.txt", "old": "same", "new": "x"}, ctx)
    assert not r["ok"] and "2 次" in r["output"] and "[1, 3]" in r["output"]
    assert (tmp_path / "d.txt").read_text(encoding="utf-8") == "same\nmid\nsame\n"  # 一个字都没动


def test_edit_missing_string(ctx, tmp_path):
    lines(tmp_path, "e.txt", "hello")
    r = BUILTIN_TOOLS["edit"].run({"path": "e.txt", "old": "world", "new": "x"}, ctx)
    assert not r["ok"] and "0 次" in r["output"]


def test_edit_replace_all_only_with_flag(ctx, tmp_path):
    lines(tmp_path, "g.txt", "a b a")
    assert not BUILTIN_TOOLS["edit"].run({"path": "g.txt", "old": "a", "new": "z"}, ctx)["ok"]
    r = BUILTIN_TOOLS["edit"].run({"path": "g.txt", "old": "a", "new": "z", "replace_all": True}, ctx)
    assert r["ok"] and (tmp_path / "g.txt").read_text(encoding="utf-8") == "z b z"


def test_edit_empty_old_refused(ctx, tmp_path):
    lines(tmp_path, "h.txt", "x")
    assert not BUILTIN_TOOLS["edit"].run({"path": "h.txt", "old": "", "new": "y"}, ctx)["ok"]


# ---------- bash ----------
def test_bash_nonzero_exit_returned_normally(ctx):
    r = BUILTIN_TOOLS["bash"].run({"command": "python -c \"import sys; sys.exit(3)\""}, ctx)
    assert not r["ok"] and r["exit_code"] == 3 and "exit_code=3" in r["output"]


def test_bash_stdout_stderr_exit_code(ctx):
    r = BUILTIN_TOOLS["bash"].run(
        {"command": "python -c \"import sys; print('OUT'); print('ERR', file=sys.stderr)\""}, ctx)
    assert r["ok"] and "OUT" in r["output"] and "ERR" in r["output"] and "stderr" in r["output"]


def test_bash_timeout_kills_tree(ctx):
    r = BUILTIN_TOOLS["bash"].run(
        {"command": "python -c \"import time; time.sleep(30)\"", "timeout": 1}, ctx)
    assert not r["ok"] and "超时" in r["output"]


def test_bash_truncates_long_output(ctx):
    r = BUILTIN_TOOLS["bash"].run({"command": "python -c \"print('x' * 20000)\""}, ctx)
    assert r["ok"] and "已截断" in r["output"]


def test_bash_runs_in_workspace(ctx, tmp_path):
    lines(tmp_path, "marker.txt", "here")
    r = BUILTIN_TOOLS["bash"].run({"command": "python -c \"print(open('marker.txt').read())\""}, ctx)
    assert r["ok"] and "here" in r["output"]


def test_interrupt(ctx):
    import threading

    from agent.tools.base import Interrupted

    ctx.interrupt.set()
    with pytest.raises(Interrupted):     # 循环层负责把它变成「用户中断」观察
        BUILTIN_TOOLS["bash"].run({"command": "python -c \"print(1)\""}, ctx)
