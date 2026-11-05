"""增量 C 断言：落盘原子、续跑不重放、定时不惊群、事件去重、通知有通道。"""
import json
import shutil
import time
from pathlib import Path

import pytest

from agent.daemon.checkpoint import DONE, RunState
from agent.daemon.notify import notify
from agent.daemon.routines import Routine, Scheduler, parse_routines
from agent.daemon.runner import Daemon
from agent.daemon.scripted import ScriptedLongProvider
from agent.daemon.watch import DirectoryWatcher
from agent.inspect import cmd_daemon
from agent.loop import AgentLoop
from agent.tools import BUILTIN_TOOLS

REPO = Path(__file__).resolve().parent.parent
TASK = "修复 mean 对空列表的处理"


@pytest.fixture()
def ws(tmp_path):
    for f in ("stats.py", "test_stats.py"):
        shutil.copy(REPO / "workspace" / f, tmp_path / f)
    return tmp_path


# ---------------- checkpoint ----------------
def test_checkpoint_atomic_roundtrip(tmp_path):
    state = RunState(run_id="r1", task=TASK, state_dir=str(tmp_path))
    state.messages = [{"role": "user", "content": "hi"}]
    state.step = 3
    state.executed_calls = ["s1"]
    state.save()
    back = RunState.load(tmp_path, "r1")
    assert back.step == 3 and back.executed_calls == ["s1"]
    assert back.state_dir == str(tmp_path)
    assert state.messages == back.messages
    assert not (tmp_path / "r1.json.tmp").exists()      # 原子写不留半成品


def test_checkpoint_latest(tmp_path):
    for rid, step in (("a", 1), ("b", 5)):
        s = RunState(run_id=rid, task="t", step=step, state_dir=str(tmp_path))
        s.save()
        time.sleep(0.01)
    assert RunState.latest(tmp_path).run_id == "b"
    assert [r.run_id for r in RunState.all_runs(tmp_path)] == ["a", "b"]


# ---------------- 定时 ----------------
def test_parse_routines_ok():
    routines = parse_routines(
        'routines:\n'
        '  - name: a\n'
        '    every_seconds: 5\n'
        '    skill: review-diff\n'
        '    task: "审一下"\n'
        '  - name: b\n'
        '    at: "09:30"\n'
        '    task: "跑测试"\n')
    assert [r.name for r in routines] == ["a", "b"]
    assert routines[0].every_seconds == 5 and routines[1].at == "09:30"


def test_parse_routines_rejects_unknown_field():
    with pytest.raises(ValueError):
        parse_routines('routines:\n  - name: a\n    cron: "* * * * *"\n')


def test_scheduler_no_stampede_and_interval():
    r = Routine(name="a", task="t", every_seconds=60)
    s = Scheduler([r], clock=lambda: 1000.0)
    assert s.due(now=1000.5) == []                     # 启动不立刻跑
    assert [x.name for x in s.due(now=1061)] == ["a"]
    assert s.due(now=1061.5) == []                     # 周期内不重复


def test_scheduler_at_once_per_day():
    at = "09:30"
    r = Routine(name="b", task="t", at=at)
    s = Scheduler([r], clock=lambda: 0)
    today = time.strftime("%Y-%m-%d")
    now = time.mktime(time.strptime(f"{today} {at}", "%Y-%m-%d %H:%M"))
    assert [x.name for x in s.due(now=now)] == ["b"]
    assert s.due(now=now + 30) == []                    # 同一分钟只触发一次


# ---------------- 事件 ----------------
def test_watcher_detects_modified_and_created(tmp_path):
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    watcher = DirectoryWatcher(tmp_path)
    assert watcher.poll() == []                         # 启动先拍快照

    target.write_text("x = 2222\n", encoding="utf-8")     # 长度与 mtime 至少变一个
    time.sleep(0.05)
    events = watcher.poll()
    assert any(e["path"] == "a.py" and e["event"] == "modified" for e in events)

    (tmp_path / "b.py").write_text("y = 1\n", encoding="utf-8")
    assert any(e["event"] == "created" for e in watcher.poll())
    assert watcher.consume() is not None


def test_watcher_queue_dedups_same_path(tmp_path):
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    watcher = DirectoryWatcher(tmp_path)
    for i in range(3):
        target.write_text(f"x = {i}\n", encoding="utf-8")
        time.sleep(0.02)
        watcher.poll()
    assert len(watcher.queue) == 1                      # 同一个文件只留最新一条


# ---------------- 通知 ----------------
def test_notify_falls_back_to_log(tmp_path):
    result = notify("标题", "正文", allow_toast=False, log_path=tmp_path / "n.log")
    assert result["ok"] and "log" in result["channels"]
    assert "正文" in (tmp_path / "n.log").read_text(encoding="utf-8")


# ---------------- 续跑与幂等 ----------------
def test_resume_continues_without_replay(ws, tmp_path):
    state_dir = tmp_path / "state"
    state = RunState(run_id="r1", task=TASK, state_dir=str(state_dir))
    loop = AgentLoop(ScriptedLongProvider(), BUILTIN_TOOLS, ws, max_steps=8,
                     enable_skills=False, enable_hooks=False, enable_reviewer=False)

    tools = 0
    gen = loop.run(TASK, checkpoint=state)
    for ev in gen:
        if ev.type == "tool_end":
            tools += 1
            if tools == 2:
                break                                       # 模拟 kill -9
    gen.close()
    assert state.step >= 1
    killed = len(state.executed_calls)
    assert killed <= 2

    resumed = RunState.load(state_dir, "r1")
    for _ in loop.run(TASK, checkpoint=resumed):
        pass
    assert resumed.status == DONE
    assert len(resumed.executed_calls) == 5
    assert len(set(resumed.executed_calls)) == 5          # 一个调用只执行一次
    assert len(resumed.executed_calls) - killed == 5 - killed


def test_resume_is_idempotent(ws, tmp_path):
    daemon = Daemon(ws, state_dir=tmp_path / "state", allow_toast=False)
    first = daemon.run_task(TASK, run_id="i1", max_steps=8)
    assert first["status"] == DONE
    again = daemon.resume("i1")
    assert again["resumed"] is False and "幂等" in again["reason"]
    assert again["executed_calls"] == 5


def test_fire_routine_runs_skill_script(ws, tmp_path):
    daemon = Daemon(ws, state_dir=tmp_path / "state", allow_toast=False)
    result = daemon.fire_routine(Routine(name="audit", task="审一下", skill="review-diff"))
    assert result["action"] == "script" and result["ok"] is True
    assert daemon.stats["triggers_fired"] == 1


def test_daemon_report(tmp_path):
    report = cmd_daemon(str(tmp_path / "daemon_report.json"), allow_toast=False)
    diag = {k: report[k] for k in ("killed_at_step", "killed_executed", "resume_from_step",
                                   "run_returncode", "kill_diag")}
    assert report["triggers_fired"] >= 3, diag
    assert report["resume_from_step"] >= 2, diag
    assert report["idempotent"] is True
    assert report["replayed_tools"] == 0
    assert report["executed_calls"] == 5
    assert report["notify_fired"] is True
    assert json.loads((tmp_path / "daemon_report.json").read_text(encoding="utf-8")) == report
