"""验收命令入口：所有报告里的数字由这里打印，不接受手写。

    python -m agent.inspect skills --out skill_report.json
兼容入口（作业文档里的写法）：python -m app.inspect ...
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from agent.metrics import token_estimate                            # noqa: E402
from agent.skills import catalog_text, full_text, load_skills, route  # noqa: E402

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


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.inspect", description="作业验收：程序打印数字")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("skills", help="技能系统报告")
    p.add_argument("--out", required=True, help="输出 JSON 路径")
    args = parser.parse_args()
    if args.cmd == "skills":
        cmd_skills(args.out)


if __name__ == "__main__":
    main()
