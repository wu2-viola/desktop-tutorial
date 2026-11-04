"""review-diff 技能带的脚本：把 diff 收窄成 agent 能读的大小。

技能里写死「步骤」会飘，写死「脚本」不会 —— 这就是技能可以带 scripts/ 的理由。
用法：
    python skills/review-diff/scripts/collect_diff.py --stat
    python skills/review-diff/scripts/collect_diff.py --max-lines 400
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CWD = Path.cwd()


def run(args: list[str]) -> str:
    r = subprocess.run(["git", *args], cwd=CWD, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr.strip() else "")


def main() -> None:
    args = sys.argv[1:]
    stat_only = "--stat" in args
    max_lines = 400
    if "--max-lines" in args:
        max_lines = int(args[args.index("--max-lines") + 1])

    if stat_only:
        print(run(["diff", "--stat", "HEAD"]) or "(无改动)")
        return

    diff = run(["diff", "HEAD"])
    if not diff.strip():
        print("(工作区没有改动)")
        return
    lines = diff.splitlines()
    print("\n".join(lines[:max_lines]))
    if len(lines) > max_lines:
        print(f"\n…… diff 共 {len(lines)} 行，已截断到 {max_lines} 行")


if __name__ == "__main__":
    main()
