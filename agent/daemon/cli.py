"""命令行入口：python -m agent.daemon run | resume | start | status

演示 kill -9 续跑：
    python -m agent.daemon run --task "修复 mean 对空列表的处理" --run-id demo --slow 0.5
    # 另开一个窗口，等它跑到第 3 步：Stop-Process -Id <pid> -Force
    python -m agent.daemon resume --run-id demo
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from ..gitutil import find_git
from .checkpoint import RunState, default_state_dir
from .runner import REPO, Daemon


def _daemon(args) -> Daemon:
    state_dir = Path(args.state_dir) if args.state_dir else default_state_dir()
    return Daemon(Path(args.workspace), state_dir=state_dir,
                  slow=getattr(args, "slow", 0.0),
                  hooks=getattr(args, "hooks", False),
                  routines_path=getattr(args, "routines", None),
                  watch_dir=getattr(args, "watch_dir", None),
                  allow_toast=not getattr(args, "no_toast", False))


def _reset(workspace: Path) -> None:
    """把演示 bug 放回去 —— 上一次跑完已经把它修好了。

    从 `git show HEAD:workspace/xxx` 取初始版本，而不是 checkout：
    工作区可能正被上一次运行改过，checkout 也会顺手抹掉别的改动。
    """
    git = find_git()
    names = ("stats.py", "test_stats.py")
    if git:
        ok = True
        for name in names:
            r = subprocess.run([git, "-C", str(REPO), "show", f"HEAD:workspace/{name}"],
                               capture_output=True, text=True, encoding="utf-8")
            if r.returncode != 0 or not r.stdout.strip():
                ok = False
                break
            (workspace / name).write_text(r.stdout, encoding="utf-8")
        if ok:
            print(f"[reset] 已从 HEAD 恢复：{workspace / 'stats.py'}")
            return
    for name in names:
        src, dst = REPO / "workspace" / name, workspace / name
        if src.resolve() != dst.resolve():
            shutil.copy(src, dst)
    print(f"[reset] 已恢复初始 bug：{workspace / 'stats.py'}")


def _print_events(gen, verbose: bool = True) -> None:
    for ev in gen:
        if ev.type == "step_begin":
            flag = "（续跑）" if ev.data.get("resumed") else ""
            print(f"\n[step {ev.data['step']}]{flag}")
        elif ev.type == "assistant_text":
            print(ev.data["delta"], end="", flush=True)
        elif ev.type == "tool_end" and verbose:
            mark = "ok" if ev.data["ok"] else "FAIL"
            print(f"\n  [{ev.data['tool']}] {mark} ({ev.data['elapsed_ms']}ms)")
            print("  " + ev.data["output"].replace("\n", "\n  ")[:400])
        elif ev.type == "final":
            print(f"\n\n=== 完成 ===\n{ev.data['text']}")
        elif ev.type == "stopped":
            print(f"\n=== 停止 === {ev.data['reason']}")
        elif ev.type == "error":
            print(f"\n=== 出错 === {ev.data['message']}", file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m agent.daemon",
                                 description="常驻能力：定时 / 事件 / 续跑 / 通知")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--workspace", default=str(REPO / "workspace"))
        p.add_argument("--state-dir", default=os.environ.get("AGENT_STATE_DIR"))
        p.add_argument("--no-toast", action="store_true")

    run = sub.add_parser("run", help="跑一个长任务（可被 kill，再 resume）")
    run.add_argument("--task", required=True)
    run.add_argument("--run-id", default=None)
    run.add_argument("--slow", type=float, default=0.0, help="每步睡多少秒，留出 kill 的窗口")
    run.add_argument("--steps", type=int, default=8)
    run.add_argument("--hooks", action="store_true")
    run.add_argument("--reset", action="store_true", help="先恢复演示 bug")
    common(run)

    res = sub.add_parser("resume", help="从 checkpoint 续跑")
    res.add_argument("--run-id", default=None)
    res.add_argument("--last", action="store_true")
    res.add_argument("--steps", type=int, default=10)
    common(res)

    start = sub.add_parser("start", help="常驻：定时 + 事件 + 通知")
    start.add_argument("--duration", type=float, default=20.0)
    start.add_argument("--routines", default=str(REPO / "routines.yaml"))
    start.add_argument("--watch-dir", default=None)
    start.add_argument("--slow", type=float, default=0.0)
    start.add_argument("--hooks", action="store_true")
    common(start)

    status = sub.add_parser("status", help="列出所有 run 的状态")
    common(status)

    args = ap.parse_args(argv)
    workspace = Path(args.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    if getattr(args, "reset", False):
        _reset(workspace)

    d = _daemon(args)
    if args.cmd == "run":
        state = RunState(run_id=args.run_id or f"demo_{int(os.getpid())}",
                         task=args.task, state_dir=str(d.state_dir))
        print(f"[run] {state.run_id}  state={state.path()}")
        _print_events(d._loop(args.steps).run(args.task, checkpoint=state))
        print(f"\n[状态] {state.status}  第 {state.step} 步  已执行 {state.executed_calls}")
    elif args.cmd == "resume":
        run_id = None if args.last else args.run_id
        if run_id is None:
            latest = RunState.latest(d.state_dir)
            run_id = latest.run_id if latest else None
        print(f"[resume] {run_id}")
        print(json.dumps(d.resume(run_id, args.steps), ensure_ascii=False, indent=2))
    elif args.cmd == "start":
        print(f"[start] {args.duration}s  routines={d.routines_path}  watch={d.watch_dir}")
        print(json.dumps(d.start(args.duration), ensure_ascii=False, indent=2))
    elif args.cmd == "status":
        runs = RunState.all_runs(d.state_dir)
        if not runs:
            print("(还没有 run)")
        for r in runs:
            print(f"{r.run_id:24} {r.status:8} step={r.step:<3} "
                  f"executed={len(r.executed_calls)}  {r.task[:40]}")


if __name__ == "__main__":
    main()
