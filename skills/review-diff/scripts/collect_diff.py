"""review-diff 技能带的脚本：把 diff 收窄成 agent 能读的大小。

技能里写死「步骤」会飘，写死「脚本」不会 —— 这就是技能可以带 scripts/ 的理由。
脚本自带 git 探测：PATH 里没有 git 时退回常见安装位置，技能因此可以整包带走。

用法：
    python skills/review-diff/scripts/collect_diff.py --stat
    python skills/review-diff/scripts/collect_diff.py --max-lines 400
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

CWD = Path.cwd()


def find_git() -> str:
    env = os.environ.get("GIT")
    if env and Path(env).exists():
        return env
    found = shutil.which("git")
    if found:
        return found
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "cmd" / "git.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Git" / "cmd" / "git.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Git" / "cmd" / "git.exe",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    desktop = Path(os.environ.get("LOCALAPPDATA", "")) / "GitHubDesktop"
    if desktop.is_dir():
        for p in sorted(desktop.glob("app-*/resources/app/git/cmd/git.exe"), reverse=True):
            return str(p)
    return "git"


GIT = find_git()


def run(args: list[str]) -> str:
    try:
        r = subprocess.run([GIT, *args], cwd=CWD, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return "（找不到 git：装一个，或把 GIT 环境变量指向 git.exe）"
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
    if not diff.strip() or diff.startswith("（找不到 git"):
        print(diff or "(工作区没有改动)")
        return
    lines = diff.splitlines()
    print("\n".join(lines[:max_lines]))
    if len(lines) > max_lines:
        print(f"\n…… diff 共 {len(lines)} 行，已截断到 {max_lines} 行")


if __name__ == "__main__":
    main()
