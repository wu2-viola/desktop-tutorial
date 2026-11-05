"""验收命令入口：所有报告里的数字由这里打印，不接受手写。

    python -m agent.inspect skills --out skill_report.json
    python -m agent.inspect custom --out custom_report.json
兼容入口（作业文档里的写法）：python -m app.inspect ...
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from agent.agents_md import load_agents_md                     # noqa: E402
from agent.daemon.checkpoint import DONE, RunState             # noqa: E402
from agent.gitutil import find_git                             # noqa: E402
from agent.daemon.notify import notify                         # noqa: E402
from agent.daemon.routines import Scheduler, parse_routines    # noqa: E402
from agent.daemon.runner import Daemon                         # noqa: E402
from agent.daemon.watch import DirectoryWatcher                # noqa: E402
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
    _seed_demo_workspace(ws)               # 无论工作区当前是什么状态，都从 HEAD 取 bug 版
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


# ---------------- 增量 C：常驻（选做） ----------------
DAEMON_TASK = "修复 mean 对空列表的处理"


def _seed_demo_workspace(dst: Path) -> None:
    """拷一份演示工作区，并确保是 bug 版（从 git HEAD 取，不依赖工作区当前状态）。"""
    src = REPO / "workspace"
    if Path(dst).resolve() != src.resolve():
        shutil.copytree(src, dst, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "notes.md"))
    git = find_git()
    if not git:
        return
    for name in ("stats.py", "test_stats.py"):
        r = subprocess.run([git, "-C", str(REPO), "show", f"HEAD:workspace/{name}"],
                           capture_output=True, text=True, encoding="utf-8")
        if r.returncode == 0 and r.stdout.strip():
            (dst / name).write_text(r.stdout, encoding="utf-8")


def _inprocess_kill(ws: Path, state_dir: Path, task: str) -> tuple[int, int]:
    """子进程时序没抓到窗口时的降级：进程内中断，走的是同一套 checkpoint 代码。"""
    from agent.daemon.scripted import ScriptedLongProvider
    from agent.loop import AgentLoop

    state = RunState(run_id="demo-kill", task=task, state_dir=str(state_dir))
    loop = AgentLoop(ScriptedLongProvider(), BUILTIN_TOOLS, ws, max_steps=8,
                     enable_skills=False, enable_hooks=False, enable_reviewer=False)
    tools = 0
    gen = loop.run(task, checkpoint=state)
    for ev in gen:
        if ev.type == "tool_end":
            tools += 1
            if tools == 2:
                break
    gen.close()
    return state.step, len(state.executed_calls)


def _daemon_cmd(args: list[str], state_dir: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "agent.daemon", *args,
         "--state-dir", str(state_dir), "--no-toast"],
        cwd=str(REPO), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180)


def cmd_daemon(out: str, allow_toast: bool = True) -> dict:
    """真跑真杀：子进程跑长任务 → TerminateProcess → resume 两次（第二轮验幂等）。"""
    started = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="daemon-report-"))
    ws, state_dir = tmp / "ws", tmp / "state"
    ws.mkdir()
    state_dir.mkdir()
    _seed_demo_workspace(ws)
    env = {**os.environ, "AGENT_STATE_DIR": str(state_dir), "PYTHONPATH": str(REPO)}

    # 1) 长任务跑到第 2 步，直接 kill（Windows 的 TerminateProcess 等价 kill -9）
    err_path = tmp / "run.err"
    killed_step, killed_executed, proc, diag = 0, 0, None, ""
    for attempt in range(2):               # 机器慢时第一次可能没抓到窗口，允许重跑一次
        _seed_demo_workspace(ws)           # 重跑前把演示 bug 放回去
        with err_path.open("w", encoding="utf-8", errors="replace") as err:
            proc = subprocess.Popen(
                [sys.executable, "-X", "utf8", "-m", "agent.daemon", "run",
                 "--task", DAEMON_TASK, "--run-id", "demo-kill", "--slow", "0.3",
                 "--workspace", str(ws), "--state-dir", str(state_dir), "--no-toast"],
                cwd=str(REPO), env=env, stdout=subprocess.DEVNULL, stderr=err)
        deadline = time.time() + 40
        while time.time() < deadline:
            try:
                state = RunState.load(state_dir, "demo-kill")
            except (FileNotFoundError, json.JSONDecodeError):
                state = None
            if state and state.step >= 2:
                proc.kill()                # 不触发任何清理：checkpoint 之外全是内存
                killed_step = state.step
                killed_executed = len(state.executed_calls)
                break
            if proc.poll() is not None:
                break
            time.sleep(0.05)
        proc.wait(timeout=30)
        diag = err_path.read_text(encoding="utf-8", errors="replace")[-800:]
        if killed_step >= 2:
            break
        (state_dir / "demo-kill.json").unlink(missing_ok=True)

    kill_mode = "process"
    if killed_step < 2:                    # 机器太快/太慢都可能抓不到，退回进程内中断
        kill_mode = "inprocess-fallback"
        killed_step, killed_executed = _inprocess_kill(ws, state_dir, DAEMON_TASK)

    # 2) 续跑两轮：第一轮补完，第二轮必须「已完成，幂等跳过」
    first = _daemon_cmd(["resume", "--run-id", "demo-kill", "--workspace", str(ws)],
                        state_dir, env)
    after_first = RunState.load(state_dir, "demo-kill")
    second = _daemon_cmd(["resume", "--run-id", "demo-kill", "--workspace", str(ws)],
                         state_dir, env)
    after_second = RunState.load(state_dir, "demo-kill")
    replayed = len(after_second.executed_calls) - len(after_first.executed_calls)
    idempotent = (replayed == 0 and first.returncode == 0 and second.returncode == 0
                  and after_first.status == DONE and after_second.status == DONE
                  and "幂等" in second.stdout)

    # 3) 定时触发：假时钟推进三次，每次真跑一个技能的脚本
    daemon = Daemon(ws, state_dir=state_dir, allow_toast=False)
    routines = parse_routines(
        'routines:\n'
        '  - name: watch-diff\n'
        '    every_seconds: 60\n'
        '    skill: review-diff\n'
        '    task: "审一下当前改动"\n'
        '  - name: slow-audit\n'
        '    every_seconds: 300\n'
        '    skill: run-tests\n'
        '    task: "跑一遍测试"\n')
    scheduler = Scheduler(routines)
    base = time.time()
    fired = [daemon.fire_routine(r)
             for i in range(1, 4) for r in scheduler.due(now=base + i * 61)]

    # 4) 事件触发：改三次文件，进队列再看能消费出几条
    watcher = DirectoryWatcher(ws)
    events: list[dict] = []
    target = ws / "stats.py"
    original = target.read_text(encoding="utf-8")
    queued = 0
    for i in range(3):
        target.write_text(original + f"\n# touch {i}\n", encoding="utf-8")
        time.sleep(0.02)
        events += watcher.poll()
        while watcher.consume():        # 事件进队列后立即消费，避免被同路径去重吃掉
            queued += 1
    target.write_text(original, encoding="utf-8")

    # 5) 完成通知：真弹一次（或降级写日志），通道写进报告
    note = notify("Desktop Agent", "常驻验收：定时 / 事件 / 续跑 / 通知",
                  allow_toast=allow_toast, log_path=state_dir / "notifications.log")

    report = {
        "triggers_fired": len(fired),
        "event_triggers_fired": len(events),
        "resume_from_step": killed_step + 1,
        "notify_fired": bool(note["ok"]),
        "idempotent": idempotent,
        "killed_at_step": killed_step,
        "killed_executed": killed_executed,
        "executed_calls": len(after_second.executed_calls),
        "replayed_tools": replayed,
        "resume_rounds": [
            {"round": 1, "status": after_first.status, "step": after_first.step,
             "executed": len(after_first.executed_calls)},
            {"round": 2, "status": after_second.status, "step": after_second.step,
             "executed": len(after_second.executed_calls)},
        ],
        "idempotent_evidence": "第二轮 resume 命中 done 直接跳过，工具执行数不变",
        "notify_channels": note["channels"],
        "routines": [{"name": f["routine"], "skill": f["skill"],
                      "action": f["action"], "ok": f["ok"]} for f in fired],
        "event_queue_consumed": queued,
        "kill_mode": kill_mode,
        "run_returncode": proc.returncode,
        "kill_diag": diag,
        "duration_ms": int((time.time() - started) * 1000),
    }
    _write(out, report)
    shutil.rmtree(tmp, ignore_errors=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.inspect", description="作业验收：程序打印数字")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, help_text in (("skills", "技能系统报告"), ("custom", "定制层报告"),
                            ("daemon", "常驻能力报告（选做）")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--out", required=True, help="输出 JSON 路径")
    args = parser.parse_args()
    if args.cmd == "skills":
        cmd_skills(args.out)
    elif args.cmd == "custom":
        cmd_custom(args.out)
    elif args.cmd == "daemon":
        cmd_daemon(args.out)


if __name__ == "__main__":
    main()
