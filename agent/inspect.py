"""验收命令入口：所有报告里的数字由这里打印，不接受手写。

    python -m agent.inspect skills --out skill_report.json
    python -m agent.inspect custom --out custom_report.json
兼容入口（作业文档里的写法）：python -m app.inspect ...
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from agent.agents_md import load_agents_md                     # noqa: E402
from agent.hooks import HookEngine                             # noqa: E402
from agent.metrics import token_estimate                       # noqa: E402
from agent.skills import catalog_text, full_text, load_skills, route  # noqa: E402
from agent.subagents import ReviewerTool, ScriptedReviewerProvider    # noqa: E402
from agent.tools import BUILTIN_TOOLS, ToolContext             # noqa: E402

TRIALS: list[tuple[str, str | None]] = [
    ("帮我跑一下测试", "run-tests"),
    ("测试挂了看看为什么", "run-tests"),
    ("把这段 diff 审一遍", "review-diff"),
    ("看看改了什么", "review-diff"),
    ("拉个 issue 看看需求", "fetch-issue"),
    ("issue 里怎么说的", "fetch-issue"),
    ("今天天气怎么样", None),
    ("帮我写一首关于秋天的诗", None),
]

BUGGY = "        return 0            # BUG：空列表应当抛错，而不是静默返回 0"
WRONG_A = "        return 0.9 * total / len(nums)  # 故意改错"
WRONG_B = "        return 0  # 又改错了"
RIGHT = '        raise ValueError("mean() of empty sequence")'


def _write(path: str, data: dict) -> None:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=2))


# ---------------- 增量 A：技能 ----------------
def cmd_skills(out: str) -> dict:
    skills = load_skills(REPO / "skills")
    catalog, full = catalog_text(skills), full_text(skills)
    cat_tokens, full_tokens = token_estimate(catalog), token_estimate(full)

    trials = []
    for query, expected in TRIALS:
        hit = route(query, skills)
        hit_name = hit.name if hit else None
        trials.append({"query": query, "expected": expected,
                       "hit": hit_name, "ok": hit_name == expected})

    report = {
        "skills": [{"name": s.name, "has_scripts": s.has_scripts, "uses_mcp": s.uses_mcp}
                   for s in skills],
        "catalog_tokens": cat_tokens,
        "full_tokens": full_tokens,
        "disclosure_ratio": round(full_tokens / max(1, cat_tokens), 1),
        "trials": trials,
        "false_positive": sum(1 for t in trials
                              if t["expected"] is None and t["hit"] is not None),
    }
    _write(out, report)
    return report


# ---------------- 增量 B：定制 ----------------
def _autotest_scenario() -> dict:
    """真跑两轮「改错 → 红 → 照着红字改对 → 绿」，数字全部来自 HookEngine。"""
    ws = Path(tempfile.mkdtemp(prefix="autotest-"))
    shutil.copytree(REPO / "workspace", ws, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "notes.md"))
    engine = HookEngine(ws)
    ctx = ToolContext(ws)
    read, edit = BUILTIN_TOOLS["read"], BUILTIN_TOOLS["edit"]
    read.run({"path": "stats.py"}, ctx)

    def apply(old: str, new: str) -> None:
        r = edit.run({"path": "stats.py", "old": old, "new": new}, ctx)
        assert r["ok"], r["output"]
        engine.post("edit", {"path": "stats.py"})

    apply(BUGGY, WRONG_A)      # 第 1 轮：改错 → 红
    apply(WRONG_A, RIGHT)      #          照着红字改对 → 绿
    apply(RIGHT, WRONG_B)      # 第 2 轮：又改错 → 红
    apply(WRONG_B, RIGHT)      #          改对 → 绿

    stats = {k: v for k, v in engine.stats.items() if k != "last_status"}
    shutil.rmtree(ws, ignore_errors=True)
    return stats


def cmd_custom(out: str) -> dict:
    workspace = REPO / "workspace"
    agents = load_agents_md(workspace)

    engine = HookEngine(workspace)
    attempts = [("write", {"path": ".env"}),
                ("bash", {"command": "rm -rf build/"}),
                ("bash", {"command": "git push --force origin main"})]
    denied = [d for tool, args in attempts if (d := engine.pre(tool, args))]

    autotest = _autotest_scenario()

    reviewer = ReviewerTool(ScriptedReviewerProvider(), REPO)
    diff_text = (REPO / "docs" / "sample-review.diff").read_text(encoding="utf-8")
    reviewer.run({"diff": diff_text}, ToolContext(REPO))

    report = {
        "agents_md": {"found": agents["found"], "bytes": agents["bytes"],
                      "layers": agents["layers"]},
        "denied": denied,
        "autotest": autotest,
        "reviewer": reviewer.stats,
    }
    _write(out, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.inspect", description="作业验收：程序打印数字")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, help_text in (("skills", "技能系统报告"), ("custom", "定制层报告")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--out", required=True, help="输出 JSON 路径")
    args = parser.parse_args()
    if args.cmd == "skills":
        cmd_skills(args.out)
    elif args.cmd == "custom":
        cmd_custom(args.out)


if __name__ == "__main__":
    main()
