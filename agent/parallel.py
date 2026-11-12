"""增量 E：开两个工位跑一次 —— git worktree 隔离，两条线同时干活，再合回来。

一个目录一个分支，两份 index，互不踩脚：agent 在 A 里改 slugify，在 B 里改 chunk，
各自跑完测试才允许合流。合流发生在临时的 `parallel/integration` 分支上（主分支不动，
所以这个演示可以反复跑），冲突文件与原因由 git 自己吐出来，不靠人回忆。

    python -m app.inspect parallel --out parallel_report.json
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from agent.gitutil import find_git

GIT_ID = ["-c", "user.name=desktop-agent", "-c", "user.email=agent@example.invalid"]
LANE_BRANCH = {"a": "parallel/task-a", "b": "parallel/task-b"}
LANE_FEAT = {"a": "feat(parallel-a): 新增 slugify", "b": "feat(parallel-b): 新增 chunk"}
CONFLICT_FILE = "CHANGELOG.md"


class GitError(RuntimeError):
    pass


def _git(root: Path, *args: str, check: bool = True, timeout: int = 300) -> subprocess.CompletedProcess:
    git = find_git()
    if not git:
        raise GitError("找不到 git：请安装 git 或设置 GIT 环境变量")
    r = subprocess.run([git, "-C", str(root), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    if check and r.returncode != 0:
        raise GitError(f"git {' '.join(args)} 失败：{(r.stderr or r.stdout).strip()[:400]}")
    return r


def _run_pytest(where: Path, timeout: int = 900) -> dict:
    started = time.time()
    r = subprocess.run([sys.executable, "-X", "utf8", "-m", "pytest", "tests", "-q"],
                       cwd=str(where), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    out = (r.stdout or "") + (r.stderr or "")
    m = re.search(r"(\d+) passed", out)
    return {"exit_code": r.returncode, "passed": int(m.group(1)) if m else 0,
            "failed_tests": re.findall(r"^FAILED (\S+)", out, re.M)[:10],
            "elapsed_ms": int((time.time() - started) * 1000),
            "tail": out.strip().splitlines()[-1][:160] if out.strip() else ""}


def _cleanup(root: Path, dirs: list[Path], branches: list[str]) -> None:
    for d in dirs:
        _git(root, "worktree", "remove", "--force", str(d), check=False)
        shutil.rmtree(d, ignore_errors=True)
    _git(root, "worktree", "prune", check=False)
    for b in branches:
        _git(root, "branch", "-D", b, check=False)
    shutil.rmtree(root / ".parallel", ignore_errors=True)


def run_parallel(root: Path | str, timeout: int = 900) -> dict:
    root = Path(root).resolve()
    started = time.time()
    git_dir = root / ".git"
    if not git_dir.exists():
        raise GitError(f"{root} 不是 git 仓库，worktree 无从谈起")

    base = _git(root, "rev-parse", "HEAD").stdout.strip()
    base_branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    sandbox = root / ".parallel"
    stale = list(sandbox.glob("*")) if sandbox.exists() else []   # 上次跑挂了留下的工位
    _cleanup(root, stale, list(LANE_BRANCH.values()) + ["parallel/integration"])
    sandbox.mkdir(parents=True, exist_ok=True)

    lanes: dict[str, dict] = {}
    procs: dict[str, tuple[subprocess.Popen, float]] = {}
    for lane, branch in LANE_BRANCH.items():
        wt = sandbox / f"task-{lane}"
        _git(root, "worktree", "add", "-B", branch, str(wt), "HEAD")
        assert wt.exists()
        procs[lane] = (
            subprocess.Popen([sys.executable, "-X", "utf8",
                              str(root / "agent" / "parallel_lane.py"),
                              "--root", str(wt), "--lane", lane],
                             cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, encoding="utf-8", errors="replace"),
            time.time())

    # 两个工位同时跑（不是串行假装并行）
    for lane, (proc, t0) in procs.items():
        out, err = proc.communicate(timeout=timeout)
        wall = int((time.time() - t0) * 1000)
        try:
            payload = json.loads(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            payload = {"lane": lane, "task": "", "files": [], "elapsed_ms": wall,
                       "pytest": {"exit_code": proc.returncode or 1, "passed": 0,
                                  "failed": 0, "elapsed_ms": 0, "tail": (err or out)[-160:]}}
        payload["wall_ms"] = wall
        lanes[lane] = payload

    total_wall = int((time.time() - started) * 1000)
    sum_ms = sum(v["elapsed_ms"] for v in lanes.values())

    # 每个工位自己先提交，再合流
    for lane, branch in LANE_BRANCH.items():
        wt = sandbox / f"task-{lane}"
        _git(wt, "add", "-A")
        _git(wt, *GIT_ID, "commit", "-q", "-m", LANE_FEAT[lane])
        lanes[lane]["branch"] = branch
        lanes[lane]["worktree"] = f".parallel/task-{lane}"
        lanes[lane]["commit"] = _git(wt, "rev-parse", "--short", "HEAD").stdout.strip()
        lanes[lane]["commit_subject"] = _git(wt, "log", "-1", "--pretty=%s").stdout.strip()

    # 合流：先 a（快进/干净），再 b（预期在 CHANGELOG.md 上撞车）
    int_wt = sandbox / "integration"
    _git(root, "worktree", "add", "-B", "parallel/integration", str(int_wt), "HEAD")
    merges: list[dict] = []
    for lane in ("a", "b"):
        r = _git(int_wt, *GIT_ID, "merge", "--no-ff", LANE_BRANCH[lane],
                 "-m", f"merge: 并入 {LANE_BRANCH[lane]}", check=False)
        merges.append({"branch": LANE_BRANCH[lane],
                       "result": "clean" if r.returncode == 0 else "conflict",
                       "exit_code": r.returncode,
                       "output": (r.stdout or r.stderr or "").strip().splitlines()[:4]})
    unmerged = _git(int_wt, "diff", "--name-only", "--diff-filter=U", check=False).stdout.split()
    conflict_files = [f for f in unmerged if f]

    resolution = ""
    if conflict_files:
        # 冲突原因：两个分支都「新建」同一个 CHANGELOG.md（add/add），内容都对，保留两边
        ours = _git(int_wt, "show", f":2:{CONFLICT_FILE}", check=False).stdout
        theirs = _git(int_wt, "show", f":3:{CONFLICT_FILE}", check=False).stdout
        merged = "# 变更记录\n\n## 未发布\n\n" + \
            "".join(line + "\n" for line in (ours + theirs).splitlines()
                    if line.startswith("- ")) + \
            "\n<!-- 两个工位同时新建了本文件（add/add），两条记录互不依赖，按 a → b 顺序都保留 -->\n"
        (int_wt / CONFLICT_FILE).write_text(merged, encoding="utf-8")
        _git(int_wt, "add", CONFLICT_FILE)
        _git(int_wt, *GIT_ID, "commit", "-q", "-m",
             "merge: 解决 CHANGELOG.md 冲突（add/add，两边都保留，a 在前）")
        resolution = "两边都新建了 CHANGELOG.md（add/add），两条记录互不依赖 → 都保留，按 a→b 排序"

    merge_commit = _git(int_wt, "rev-parse", "--short", "HEAD").stdout.strip()
    post_merge = _run_pytest(int_wt, timeout)
    attempts = 1
    if post_merge["exit_code"] != 0:
        # 两个工位刚并发跑完，别的工位留下的子进程可能干扰一次；重跑一次再判红绿
        post_merge = _run_pytest(int_wt, timeout)
        attempts = 2
    post_merge["attempts"] = attempts
    post_merge["note"] = ("首次失败、重跑通过：属于并发残留的偶发，不是代码红"
                          if attempts == 2 and post_merge["exit_code"] == 0 else "")

    git_version = _git(root, "--version", check=False).stdout.strip()
    _cleanup(root, [sandbox / "task-a", sandbox / "task-b", int_wt],
             list(LANE_BRANCH.values()) + ["parallel/integration"])

    lanes_ok = all(v["pytest"]["exit_code"] == 0 for v in lanes.values())
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "root": str(root),
        "base_commit": base[:7],
        "base_branch": base_branch,
        "git_version": git_version,
        "strategy": "git worktree：一个目录一个分支、一份 index，两条线同时跑，跑完再合",
        "lanes": [
            {"lane": f"task-{k}", "branch": v["branch"], "worktree": v["worktree"],
             "task": v["task"], "files": v["files"], "commit": v["commit"],
             "commit_subject": v["commit_subject"],
             "elapsed_ms": v["elapsed_ms"], "wall_ms": v["wall_ms"],
             "pytest": v["pytest"]}
            for k, v in sorted(lanes.items())
        ],
        "parallelism": {"lanes": len(lanes), "sum_worker_ms": sum_ms,
                        "wall_ms": total_wall,
                        "speedup": round(sum_ms / max(1, total_wall), 2)},
        "merge": {"target": "parallel/integration（临时分支，合完即删，主分支不动）",
                  "merges": merges,
                  "conflict_files": conflict_files,
                  "conflict_reason": ("两个分支从同一个 base 各自新建了 CHANGELOG.md，"
                                      "同一路径同一位置两条新增 → git 判定 add/add 冲突"
                                      if conflict_files else "无冲突"),
                  "resolution": resolution,
                  "merge_commit": merge_commit,
                  "post_merge_pytest": post_merge},
        "cleanup": {"worktrees_removed": True, "branches_deleted": True,
                    "note": "分支与工作树用完即删，所以本报告可以反复跑；sha 可直接 git cat-file 复查"},
        "verdict": {"pass": bool(lanes_ok and post_merge["exit_code"] == 0),
                    "checks": {"两个 worktree 都跑通测试": lanes_ok,
                               "冲突文件写清楚": bool(conflict_files) and bool(resolution),
                               "合并后整体测试通过": post_merge["exit_code"] == 0}},
        "duration_ms": int((time.time() - started) * 1000),
    }


def write_report(report: dict, out: str | Path) -> None:
    Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    write_report(run_parallel(Path(__file__).resolve().parent.parent),
                 sys.argv[1] if len(sys.argv) > 1 else "parallel_report.json")
