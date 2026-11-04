"""验收 JSON 的字段与阈值 —— 数字必须能和代码对上。"""
import json
from pathlib import Path

from agent.inspect import cmd_custom, cmd_skills

REPO = Path(__file__).resolve().parent.parent


def test_skill_report_thresholds(tmp_path):
    report = cmd_skills(str(tmp_path / "skill_report.json"))
    assert len(report["skills"]) >= 3
    assert report["disclosure_ratio"] >= 5
    assert len(report["trials"]) >= 6
    assert any(t["expected"] is None for t in report["trials"])   # 至少一条不该触发
    assert report["false_positive"] == 0
    assert json.loads((tmp_path / "skill_report.json").read_text(encoding="utf-8")) == report


def test_custom_report_thresholds(tmp_path):
    report = cmd_custom(str(tmp_path / "custom_report.json"))

    assert report["agents_md"]["found"] is True
    assert report["agents_md"]["bytes"] <= 12000
    assert report["agents_md"]["layers"] == ["global", "project"]

    assert len(report["denied"]) >= 2
    assert all(d["reason"] for d in report["denied"])

    at = report["autotest"]
    assert at["runs"] == 4 and at["red"] == 2 and at["green"] == 2
    assert at["red_to_green"] >= 1
    assert at["injected_lines"] == 3 * at["red"]        # 每次红只回三行

    rv = report["reviewer"]
    assert rv["main_context_delta"] <= 500
    assert rv["subagent_tokens"] > 0
    assert rv["issues_found"] >= 1

    assert json.loads((tmp_path / "custom_report.json").read_text(encoding="utf-8")) == report
