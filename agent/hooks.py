"""Hooks：写在代码里的硬约束（写在 AGENTS.md 里的只是建议）。

PreToolUse  —— 拦密钥文件、拦破坏性命令，**拒绝必须给替代方案**
PostToolUse —— write/edit 之后自动跑测试，只回注三行失败摘要（不是整段 traceback）
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SECRET_SUFFIX = (".pem", ".key")
DANGER_RULES = [
    (re.compile(r"\brm\s+-rf?\b", re.I),
     "拒绝执行破坏性删除。先 `git clean -nd` 看会删什么，或用 `git restore <file>` 撤销单个文件。"),
    (re.compile(r"git\s+push\b.*(?:--force|-f)\b", re.I),
     "拒绝强推。撤销已提交的改动用 `git revert <sha>`；找回文件用 `git restore <file>`。"),
    (re.compile(r"git\s+reset\s+--hard\b", re.I),
     "拒绝 `reset --hard`，会丢掉未提交改动。用 `git stash` 暂存，或 `git restore <file>` 只回滚个别文件。"),
]


def _is_secret_path(path: str) -> bool:
    name = Path(path).name
    return name == ".env" or name.endswith(SECRET_SUFFIX) or name.startswith(".env.")


class HookEngine:
    """一次运行一个实例；统计量给 custom_report.json 用。"""

    def __init__(self, workspace: Path, autotest_cmd: list[str] | None = None,
                 timeout: int = 90):
        self.workspace = Path(workspace)
        self.autotest_cmd = autotest_cmd or [sys.executable, "-m", "pytest", "-q"]
        self.timeout = timeout
        self.stats = {"runs": 0, "red": 0, "green": 0, "red_to_green": 0,
                      "injected_lines": 0, "last_status": None}

    # ---- PreToolUse ----
    def pre(self, tool: str, args: dict) -> dict | None:
        """返回 None 表示放行；返回 {"reason": ...} 表示拒绝。"""
        if tool in ("write", "edit"):
            path = str(args.get("path", ""))
            if _is_secret_path(path):
                return {"tool": tool, "path": path,
                        "reason": "密钥不入库，用环境变量（.env.example 只留名字，不写值）"}
        if tool == "bash":
            cmd = str(args.get("command", ""))
            for pattern, reason in DANGER_RULES:
                if pattern.search(cmd):
                    return {"tool": tool, "command": cmd, "reason": reason}
        return None

    # ---- PostToolUse ----
    def post(self, tool: str, args: dict) -> str | None:
        if tool not in ("write", "edit"):
            return None
        return self.run_tests()

    def run_tests(self) -> str | None:
        try:
            proc = subprocess.run(self.autotest_cmd, cwd=str(self.workspace),
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return "自动测试超时（90s），先停手检查是不是有死循环"
        out = (proc.stdout or "") + (proc.stderr or "")
        if "no tests ran" in out or proc.returncode == 5:
            return None                        # 没测试的目录不打扰模型
        if proc.returncode == 0:
            self.stats["runs"] += 1
            self.stats["green"] += 1
            if self.stats["last_status"] == "red":
                self.stats["red_to_green"] += 1
            self.stats["last_status"] = "green"
            return None

        self.stats["runs"] += 1
        self.stats["red"] += 1
        self.stats["last_status"] = "red"
        summary = self._summarize(out)
        self.stats["injected_lines"] += len(summary)
        return "自动测试红了（只回注三行，别抄整段 traceback）：\n" + "\n".join(summary)

    def _summarize(self, out: str) -> list[str]:
        """哪个用例 / 期望什么 / 实际什么 —— 三行封顶。"""
        failed = re.findall(r"^FAILED\s+(\S+)", out, re.M)
        case = failed[0] if failed else "（未解析到用例名）"
        msg = ""
        m = re.search(r"^E\s+(.+)$", out, re.M) or re.search(r"^FAILED .*? - (.+)$", out, re.M)
        if m:
            msg = m.group(1).strip()
        expect = self._expectation(case)
        return [f"红：{case}",
                f"期望：{expect}",
                f"实际：{msg or '见 pytest 输出'}"]

    def _expectation(self, case: str) -> str:
        """从测试源码里捞那条断言，作为「期望什么」。"""
        parts = case.split("::")
        if not parts or not parts[0].endswith(".py"):
            return "该用例的断言通过"
        f = self.workspace / parts[0]
        if not f.exists():
            return "该用例的断言通过"
        text = f.read_text(encoding="utf-8", errors="replace")
        fn = parts[-1]
        m = re.search(rf"def {re.escape(fn)}\(.*?\):(.*?)(?=\n    def |\Z)", text, re.S)
        if not m:
            return "该用例的断言通过"
        for line in m.group(1).splitlines():
            if "assert" in line:
                return line.strip().replace("self.assert", "assert ")[:120]
        return "该用例的断言通过"
