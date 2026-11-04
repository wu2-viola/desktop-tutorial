"""技能系统断言：目录常驻、正文按需、description 触发、闲聊不误触发。"""
from pathlib import Path

import pytest

from agent.metrics import token_estimate
from agent.skills import (UseSkillTool, catalog_text, full_text, load_skills,
                          route)
from agent.tools import ToolContext

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"


@pytest.fixture(scope="module")
def skills():
    return load_skills(SKILLS)


def test_three_skills_and_three_forms(skills):
    assert len(skills) >= 3
    names = {s.name for s in skills}
    assert names == {"run-tests", "review-diff", "fetch-issue"}
    assert any(s.has_scripts for s in skills)          # 提示词 + 脚本
    assert any(s.uses_mcp for s in skills)             # 提示词 + MCP
    assert any(not s.has_scripts and not s.uses_mcp for s in skills)  # 纯提示词


def test_every_description_has_trigger_phrases(skills):
    for s in skills:
        assert "Use this when" in s.description
        assert s.triggers, f"{s.name} 没有触发语"


def test_catalog_is_much_smaller_than_full(skills):
    cat, full = token_estimate(catalog_text(skills)), token_estimate(full_text(skills))
    assert full / cat >= 5, f"渐进披露没做到：{full}/{cat}"


def test_catalog_does_not_leak_body(skills):
    """目录里不能出现正文独有的一句 —— 否则等于没做渐进披露。"""
    cat = catalog_text(skills)
    for s in skills:
        first_step = next((l for l in s.body.splitlines() if l.strip().startswith("1.")), "")
        if first_step:
            assert first_step.strip() not in cat


@pytest.mark.parametrize("query,expected", [
    ("帮我跑一下测试", "run-tests"),
    ("测试挂了看看为什么", "run-tests"),
    ("把这段 diff 审一遍", "review-diff"),
    ("看看改了什么", "review-diff"),
    ("拉个 issue 看看需求", "fetch-issue"),
    ("issue 里怎么说的", "fetch-issue"),
    ("今天天气怎么样", None),
    ("帮我写一首关于秋天的诗", None),
])
def test_route_by_description(skills, query, expected):
    hit = route(query, skills)
    assert (hit.name if hit else None) == expected


def test_use_skill_injects_body_and_records(tmp_path, skills):
    ctx = ToolContext(tmp_path)
    tool = UseSkillTool(skills)
    r = tool.run({"name": "run-tests"}, ctx)
    assert r["ok"] and "怎么算做完了" in r["output"]
    assert "run-tests" in ctx.loaded_skills


def test_use_skill_unknown_name_lists_available(tmp_path, skills):
    r = UseSkillTool(skills).run({"name": "nope"}, ToolContext(tmp_path))
    assert not r["ok"] and "run-tests" in r["output"]


def test_missing_front_matter_rejected(tmp_path):
    d = tmp_path / "bad-skill"
    d.mkdir()
    (d / "SKILL.md").write_text("# 没有 YAML 头\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_skills(tmp_path)


def test_name_must_match_dir(tmp_path):
    d = tmp_path / "a"
    d.mkdir()
    (d / "SKILL.md").write_text(
        '---\nname: b\ndescription: x。Use this when "x"\n---\n正文\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_skills(tmp_path)
