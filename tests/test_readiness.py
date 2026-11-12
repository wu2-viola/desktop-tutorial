"""增量 D：九根柱子体检与定级。"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.readiness import LEVELS, PILLARS, decide_level, scan


def test_nine_pillars_and_five_levels() -> None:
    assert len(PILLARS) == 9
    assert [lv for lv, _ in LEVELS] == ["L5", "L4", "L3", "L2", "L1"]


def test_level_is_gated_not_averages() -> None:
    """分数够但测试跑不通 → 掉到 L1；分数不够也上不去 L3。"""
    ok = {"tests_ok": True, "ci_test": True, "ci_style": True}
    assert decide_level(80, ok)[0] == "L3"
    assert decide_level(80, {**ok, "tests_ok": False})[0] == "L1"
    assert decide_level(70, ok)[0] == "L2"
    assert decide_level(20, {})[0] == "L1"
    assert decide_level(86, {**ok, "fast": True, "long_run": True, "o11y": True})[0] == "L4"
    assert decide_level(86, {**ok, "fast": True, "long_run": True})[0] == "L3"


def test_scan_reports_nine_scores_and_three_gaps(tmp_path: Path) -> None:
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "noop.py").write_text("x = 1\n", encoding="utf-8")
    report = scan(tmp_path, run_tests=False)
    assert len(report["scores"]) == 9
    assert set(report["scores"]) == {p[0] for p in PILLARS}
    assert len(report["top_gaps"]) == 3
    assert report["level"] == "L1"
    assert report["one_command_test"]["ok"] is False
    assert all(0 <= v <= 100 for v in report["scores"].values())


def test_scan_runs_the_test_command_for_real(tmp_path: Path) -> None:
    """「一条命令跑测试」是真跑：临时装一个必然通过的小项目，exit=0 才算数。"""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text(
        "def test_ok():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    report = scan(tmp_path)
    assert report["one_command_test"]["ok"] is True
    assert report["one_command_test"]["passed"] == 1
    assert report["scores"]["tests"] >= 40


@pytest.mark.parametrize("field", ["pillars", "level", "top_gaps", "one_command_test"])
def test_report_has_required_fields(field: str, tmp_path: Path) -> None:
    report = scan(tmp_path, run_tests=False)
    assert field in report
