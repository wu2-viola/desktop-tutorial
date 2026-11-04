"""reviewer 子 agent 断言：只读、只回结论、主上下文只增加一点点。"""
from pathlib import Path

from agent.subagents import (DiffOnlyBash, ReviewerTool, ScriptedReviewerProvider,
                             find_issues, render_review)
from agent.tools import ToolContext

REPO = Path(__file__).resolve().parent.parent
SAMPLE = (REPO / "docs" / "sample-review.diff").read_text(encoding="utf-8")


def test_find_issues_catches_all_five():
    issues = find_issues(SAMPLE)
    assert issues["deps"]                      # 新增依赖
    assert issues["except_pass"]               # except: pass
    assert issues["debug"]                     # print( / TODO
    assert issues["tests"]                     # 改代码没改测试
    assert not issues["scope"]                 # 没有改到生成物


def test_render_review_has_five_lines_and_total():
    text = render_review(find_issues(SAMPLE))
    assert len([l for l in text.splitlines() if l[:2] in ("1.", "2.", "3.", "4.", "5.")]) == 5
    assert "问题总数：5" in text


def test_reviewer_only_returns_conclusion():
    tool = ReviewerTool(ScriptedReviewerProvider(), REPO)
    res = tool.run({"diff": SAMPLE}, ToolContext(REPO))
    assert res["ok"]
    assert "问题总数" in res["output"]
    assert len(res["output"].splitlines()) <= 8      # 只回结论，不回过程
    assert "diff --git" not in res["output"]         # 不复述 diff


def test_reviewer_context_accounting():
    tool = ReviewerTool(ScriptedReviewerProvider(), REPO)
    res = tool.run({"diff": SAMPLE}, ToolContext(REPO))
    assert res["main_context_delta"] <= 500
    assert res["subagent_tokens"] > res["main_context_delta"]
    assert tool.stats["issues_found"] == 5


def test_diff_only_bash_rejects_write_commands():
    tool = DiffOnlyBash()
    ctx = ToolContext(REPO)
    assert not tool.run({"command": "rm -rf build"}, ctx)["ok"]
    assert not tool.run({"command": "python -m pytest -q"}, ctx)["ok"]
    r = tool.run({"command": "git diff HEAD --stat"}, ctx)
    assert "reviewer 只能执行" not in r.get("output", "")
