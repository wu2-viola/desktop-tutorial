"""增量 D：readiness 体检 —— 把「凭什么信它」变成机器能检查的东西。

九根柱子各有一个可复现的检查，分数由程序打印（不是手写）：

    python -m app.inspect readiness --out readiness_report.json

九根：样式与校验 / 构建系统 / 测试 / 文档 / 开发环境 / 可观测性 / 安全 / 任务发现 / 产品与实验
五级：L1 能跑 → L2 写下来了 → L3 标准化（自动检查 + 强制执行）→ L4 优化过 → L5 不用管
等级不是平均分的别名：每级都有必须过闸的判据，闸不过就停在下一级（跳级是最常见的自欺）。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

PILLARS: list[tuple[str, str, str, str]] = [
    ("style", "样式与校验", "这写得合规吗？",
     "加 ruff 配置并把 `ruff check` 放进 CI（第 12 行那个 job 里加一步）"),
    ("build", "构建系统", "编得过吗？",
     "在 pyproject.toml 补 [build-system]，并让 CI 跑一次可执行文件打包脚本"),
    ("tests", "测试", "跑得对吗？",
     "加一条 CI 必跑的 `python -m pytest tests -q`，红了就拦住合并"),
    ("docs", "文档", "我们这儿是怎么做的？",
     "在 docs/ 补一份索引：路径→职责、命令→怎么跑、坑→别踩"),
    ("devenv", "开发环境", "我能复现吗？",
     "补 .python-version 与 .env.example，让新人 clone 完命令抄下来就能跑"),
    ("observability", "可观测性", "刚才到底发生了什么？",
     "把工具调用的 step/tokens/耗时落到结构化日志，出问题能倒查"),
    ("security", "安全", "能上线吗？",
     "把 .gitignore 补上 *.pem/*.p12，并加一条提交前密钥扫描"),
    ("discovery", "任务发现", "下一步该干什么？",
     "把待办写进仓库（issues 模板或 docs/todo.md），别只活在脑子里"),
    ("product", "产品与实验", "这有用吗？",
     "补一份带数字的验收记录（每项功能一条实测），别只有功能清单"),
]

LEVELS: list[tuple[str, str]] = [
    ("L5", "不用管：派活、验收、合并全程不需要人"),
    ("L4", "优化过：反馈够快，撑得住长时间独跑（后台的门槛）"),
    ("L3", "标准化：检查是自动的，而且被强制执行"),
    ("L2", "写下来了：能带新人跑通，命令抄下来就能用"),
    ("L1", "能跑：代码能跑起来，检查靠人手动点"),
]


# ---------------- 基础探测 ----------------
def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _glob(root: Path, pattern: str) -> list[Path]:
    return [p for p in root.glob(pattern) if p.is_file()]


def _py_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for sub in ("agent", "app", "server", "mcp", "ui", "tests"):
        out += [p for p in (root / sub).rglob("*.py")] if (root / sub).is_dir() else []
    out += [p for p in (root.glob("*.py"))]
    return [p for p in out if "__pycache__" not in str(p)]


def run_test_command(root: Path, timeout: int = 900) -> dict:
    """「一条命令跑测试」——真跑，不是声明。"""
    cmd = [sys.executable, "-m", "pytest", "tests", "-q"]
    started = time.time()
    try:
        r = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        code, out = r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        code, out = 124, "timeout"
    except OSError as exc:                      # 没装 pytest 也算「跑不起来」
        code, out = 127, str(exc)
    m = re.search(r"(\d+) passed", out)
    f = re.search(r"(\d+) failed", out)
    e = re.search(r"(\d+) error", out)
    return {
        "command": "python -m pytest tests -q",
        "ok": code == 0,
        "exit_code": code,
        "passed": int(m.group(1)) if m else 0,
        "failed": int(f.group(1)) if f else 0,
        "errors": int(e.group(1)) if e else 0,
        "elapsed_ms": int((time.time() - started) * 1000),
        "tail": out.strip().splitlines()[-1][:200] if out.strip() else "",
    }


# ---------------- 九根柱子 ----------------
def _pillar_style(root: Path) -> tuple[int, list[str]]:
    ev, score = [], 0
    pyproject = _read(root / "pyproject.toml")
    has_cfg = bool(re.search(r"\[tool\.(ruff|black|flake8)", pyproject)) or any(
        (root / n).exists() for n in ("ruff.toml", ".ruff.toml", ".flake8", ".editorconfig"))
    score += 40 if has_cfg else 0
    ev.append(f"{'+' if has_cfg else '-'}40 校验配置："
              f"{'pyproject/[tool.ruff] 等存在' if has_cfg else '没有任何 lint/format 配置'}")

    py = _py_files(root)
    r = subprocess.run([sys.executable, "-m", "compileall", "-q", *[str(p) for p in py]],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = r.returncode == 0
    score += 40 if ok else 0
    ev.append(f"{'+' if ok else '-'}40 真跑一遍语法校验（compileall，{len(py)} 个 .py）："
              f"{'全过' if ok else '有文件编不过'}")

    ci = _read(root / ".github/workflows/ci.yml")
    ci_style = bool(re.search(r"ruff|flake8|lint|compileall", ci))
    score += 20 if ci_style else 0
    ev.append(f"{'+' if ci_style else '-'}20 CI 里强制跑样式检查")
    return score, ev


def _pillar_build(root: Path) -> tuple[int, list[str]]:
    ev, score = [], 0
    pyproject = _read(root / "pyproject.toml")
    has_bs = "[build-system]" in pyproject or (root / "setup.py").exists()
    score += 40 if has_bs else 0
    ev.append(f"{'+' if has_bs else '-'}40 有 [build-system]/setup.py："
              f"{'有' if has_bs else '没有，只能当脚本跑，装不了'}")

    entry = [n for n in ("app.py", "cli.py", "DesktopAgent.spec") if (root / n).exists()]
    score += 30 if entry else 0
    ev.append(f"{'+' if entry else '-'}30 入口/打包配置：{entry or '无'}")

    r = subprocess.run([sys.executable, "-m", "compileall", "-q", str(root / "agent"),
                        str(root / "app")], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    ok = r.returncode == 0
    score += 30 if ok else 0
    ev.append(f"{'+' if ok else '-'}30 包能整体编译通过")
    return score, ev


def _pillar_tests(root: Path, test_run: dict) -> tuple[int, list[str]]:
    ev, score = [], 0
    files = _glob(root, "tests/test_*.py")
    score += min(40, int(len(files) * 40 / 10))
    ev.append(f"+{min(40, int(len(files) * 40 / 10))} 测试文件 {len(files)} 个（≥10 个满分）")

    score += 40 if test_run["ok"] else 0
    ev.append(f"{'+' if test_run['ok'] else '-'}40 一条命令跑测试：exit={test_run['exit_code']}、"
              f"{test_run['passed']} passed、{test_run['elapsed_ms']}ms")

    ci = _read(root / ".github/workflows/ci.yml")
    ci_test = "pytest" in ci
    score += 20 if ci_test else 0
    ev.append(f"{'+' if ci_test else '-'}20 CI 每次 push 都跑测试（强制执行）")
    return score, ev


def _pillar_docs(root: Path) -> tuple[int, list[str]]:
    ev, score = [], 0
    readme = _read(root / "README.md")
    pts = 40 if len(readme) >= 6000 else 25 if len(readme) >= 2500 else 0
    score += pts
    ev.append(f"+{pts} README {len(readme)} 字节")

    docs = _glob(root, "docs/**/*")
    pts = 30 if len(docs) >= 5 else 15 if docs else 0
    score += pts
    ev.append(f"+{pts} docs/ 下 {len(docs)} 份材料")

    agents = (root / "AGENTS.md").exists()
    score += 30 if agents else 0
    ev.append(f"{'+' if agents else '-'}30 AGENTS.md（地图给模型，也给新人）")
    return score, ev


def _pillar_devenv(root: Path) -> tuple[int, list[str]]:
    ev, score = [], 0
    req = (root / "requirements.txt").exists(), (root / "requirements-dev.txt").exists()
    pts = 40 if all(req) else 20 if any(req) else 0
    score += pts
    ev.append(f"+{pts} requirements{'(+dev)' if all(req) else ''} 存在")

    pinned = bool(re.search(r"requires-python", _read(root / "pyproject.toml"))) or \
        (root / ".python-version").exists()
    score += 30 if pinned else 0
    ev.append(f"{'+' if pinned else '-'}30 Python 版本被钉住")

    env = (root / ".env.example").exists()
    score += 30 if env else 0
    ev.append(f"{'+' if env else '-'}30 .env.example 给了配置样板")
    return score, ev


def _pillar_observability(root: Path) -> tuple[int, list[str]]:
    ev, score = [], 0
    calls = sum(len(re.findall(r"\blogging\.\w+\(|logger\.\w+\(", _read(p)))
                for p in _py_files(root) if (root / "agent") in p.parents or p.parent == root / "agent")
    pts = 40 if calls >= 5 else 20 if calls else 0
    score += pts
    ev.append(f"+{pts} 代码里 {calls} 处结构化日志调用")

    reports = _glob(root, "*_report.json")
    pts = 30 if len(reports) >= 3 else 15 if reports else 0
    score += pts
    ev.append(f"+{pts} 程序产出的报告 {len(reports)} 份：{[p.name for p in reports]}")

    metrics = (root / "agent/metrics.py").exists()
    score += 30 if metrics else 0
    ev.append(f"{'+' if metrics else '-'}30 有独立的指标/计数模块")
    return score, ev


def _pillar_security(root: Path) -> tuple[int, list[str]]:
    ev, score = [], 0
    gi = _read(root / ".gitignore")
    covered = [n for n in (".env", "*.key", "*.pem") if n in gi]
    pts = 40 if len(covered) == 3 else 20 if covered else 0
    score += pts
    ev.append(f"+{pts} .gitignore 覆盖 {covered or '无'}（要 .env/*.key/*.pem 三样）")

    denied = False
    try:
        from agent.hooks import HookEngine
        denied = bool(HookEngine(root / "workspace").pre("write", {"path": ".env"}))
    except Exception as exc:                    # noqa: BLE001 - 体检不该因为被测代码崩了就停
        ev.append(f"-0 hook 探测异常：{exc}")
    score += 40 if denied else 0
    ev.append(f"{'+' if denied else '-'}40 代码层真拦住了写 .env（hook 实测）")

    secret = re.compile(r"(sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16})")
    src = [p for p in _py_files(root) if "tests" not in p.relative_to(root).parts]
    hits = [p.relative_to(root).as_posix() for p in src if secret.search(_read(p))]
    pts = 20 if not hits else 0
    score += pts
    ev.append(f"+{pts} 源码里没有硬编码密钥"
              f"{'' if not hits else '：' + str(hits)}（tests/ 里的假 key 是夹具，不算）")
    return score, ev


def _pillar_discovery(root: Path) -> tuple[int, list[str]]:
    ev, score = [], 0
    agents = _read(root / "AGENTS.md")
    has_map = (root / "AGENTS.md").exists() and ("命令" in agents or "```" in agents)
    score += 40 if has_map else 0
    ev.append(f"{'+' if has_map else '-'}40 AGENTS.md 写清了路径→职责、命令→怎么跑")

    todo = any((root / n).exists() for n in ("routines.yaml", "docs/todo.md", "TODO.md"))
    score += 30 if todo else 0
    ev.append(f"{'+' if todo else '-'}30 待办/常规任务落在仓库里")

    readme = _read(root / "README.md")
    has_cmds = len(re.findall(r"```bash", readme)) >= 3
    score += 30 if has_cmds else 0
    ev.append(f"{'+' if has_cmds else '-'}30 README 有可直接抄的验收命令清单")
    return score, ev


def _pillar_product(root: Path) -> tuple[int, list[str]]:
    ev, score = [], 0
    report = _read(root / "report.md")
    pts = 40 if len(report) >= 4000 else 20 if report else 0
    score += pts
    ev.append(f"+{pts} report.md {len(report)} 字节（带取舍与数字）")

    reports = _glob(root, "*_report.json") + _glob(root, "docs/**/*.json")
    pts = 30 if len(reports) >= 3 else 15 if reports else 0
    score += pts
    ev.append(f"+{pts} 实测证据 {len(reports)} 份 JSON")

    media = _glob(root, "docs/screenshots/*")
    pts = 30 if media else 0
    score += pts
    ev.append(f"{'+' if media else '-'}30 演示素材 {len(media)} 个（截图/录屏）")
    return score, ev


# ---------------- 定级 ----------------
def decide_level(total: int, flags: dict[str, bool]) -> tuple[str, list[str]]:
    """等级看闸，不看平均分；闸不过就停在下一级。"""
    why: list[str] = []
    if total >= 90 and flags.get("autonomy"):
        return "L5", ["总分≥90", "派活/验收/合并有自动化证据"]
    if (total >= 85 and flags.get("tests_ok") and flags.get("fast")
            and flags.get("long_run") and flags.get("o11y")):
        return "L4", ["总分≥85", "一条命令跑测试为真", "测试 < 120s（反馈够快）",
                      "有 checkpoint 续跑（撑得住长时间独跑）", "可观测性 ≥ 75（出事能倒查）"]
    if total >= 75 and flags.get("tests_ok") and flags.get("ci_test") and flags.get("ci_style"):
        return "L3", ["总分≥75", "一条命令跑测试为真", "CI 强制跑测试", "CI 强制跑样式/构建检查"]
    if total >= 55 and flags.get("tests_ok"):
        return "L2", ["总分≥55", "一条命令跑测试为真"]
    why.append("总分不足或测试跑不通")
    return "L1", why


def scan(root: Path | str = REPO, run_tests: bool = True) -> dict:
    root = Path(root).resolve()
    started = time.time()
    test_run = run_test_command(root) if run_tests else {
        "command": "python -m pytest tests -q", "ok": False, "exit_code": -1,
        "passed": 0, "failed": 0, "errors": 0, "elapsed_ms": 0, "tail": "skipped"}

    scores = {
        "style": _pillar_style(root),
        "build": _pillar_build(root),
        "tests": _pillar_tests(root, test_run),
        "docs": _pillar_docs(root),
        "devenv": _pillar_devenv(root),
        "observability": _pillar_observability(root),
        "security": _pillar_security(root),
        "discovery": _pillar_discovery(root),
        "product": _pillar_product(root),
    }
    pillars = []
    for pid, name, question, advice in PILLARS:
        score, evidence = scores[pid]
        pillars.append({"id": pid, "name": name, "question": question,
                        "score": int(score), "evidence": evidence, "advice": advice})

    total = int(round(sum(p["score"] for p in pillars) / len(pillars)))
    ci = _read(root / ".github/workflows/ci.yml")
    flags = {
        "tests_ok": test_run["ok"],
        "ci_test": "pytest" in ci,
        "ci_style": bool(re.search(r"ruff|flake8|lint|compileall", ci)),
        "fast": 0 < test_run["elapsed_ms"] < 120_000,
        "long_run": (root / "agent/daemon/checkpoint.py").exists(),
        "o11y": scores["observability"][0] >= 75,
        "autonomy": any((root / ".github/workflows").glob("*auto*")),
    }
    level, why = decide_level(total, flags)

    gaps = sorted(pillars, key=lambda p: (p["score"], -len(p["advice"])))[:3]
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "root": str(root),
        "pillars": [{k: p[k] for k in ("id", "name", "question", "score", "evidence")}
                    for p in pillars],
        "scores": {p["id"]: p["score"] for p in pillars},
        "total": total,
        "level": level,
        "level_reason": why,
        "levels": [{"level": k, "meaning": v} for k, v in LEVELS],
        "one_command_test": test_run,
        "top_gaps": [{"pillar": p["name"], "id": p["id"], "score": p["score"],
                      "advice": p["advice"]} for p in gaps],
        "flags": flags,
        "duration_ms": int((time.time() - started) * 1000),
    }


def write_report(report: dict, out: str | Path) -> None:
    Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    write_report(scan(), sys.argv[1] if len(sys.argv) > 1 else "readiness_report.json")
