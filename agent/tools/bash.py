"""bash 工具：stdout + stderr + exit_code 全返回，超时连进程树一起杀。

没有超时 → pip install 卡住，整个 agent 挂死 —— 这是万能工具的代价，必须守住。
输出过长会截断，防止把模型上下文撑爆。
"""
from __future__ import annotations

import subprocess
import tempfile
import time

from .base import guard, Tool, ToolContext

MAX_CHARS = 8000


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, timeout=10)
    except Exception:
        proc.kill()


class BashTool(Tool):
    name = "bash"
    description = (
        "在工作区目录执行一条 shell 命令，返回 stdout、stderr 和 exit_code；"
        "命令失败（非 0 退出码）也会正常返回，不会中断会话。"
        "搜索、Git、装依赖、跑测试都用它。command 必填，timeout 秒数默认 20、上限 120。"
    )
    schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的命令（工作区为当前目录）"},
            "timeout": {"type": "integer", "description": "超时秒数，默认 20，最多 120"},
        },
        "required": ["command"],
    }

    @guard
    def run(self, args: dict, ctx: ToolContext) -> dict:
        ctx.check_interrupt()
        command = str(args.get("command", "")).strip()
        if not command:
            return {"ok": False, "output": "command 为空"}
        timeout = min(120, max(1, int(args.get("timeout") or 20)))

        # 输出先落临时文件，避免管道缓冲区塞满导致死锁
        with tempfile.TemporaryFile(mode="w+b") as out_f, tempfile.TemporaryFile(mode="w+b") as err_f:
            started = time.time()
            proc = subprocess.Popen(command, shell=True, cwd=str(ctx.workspace),
                                    stdout=out_f, stderr=err_f, stdin=subprocess.DEVNULL)
            killed_reason = None
            while True:
                code = proc.poll()
                if code is not None:
                    break
                if ctx.interrupt.is_set():
                    _kill_tree(proc)
                    killed_reason = "用户中断"
                    break
                if time.time() - started > timeout:
                    _kill_tree(proc)
                    killed_reason = f"超时（{timeout}s）"
                    break
                time.sleep(0.1)
            proc.wait()
            elapsed = int((time.time() - started) * 1000)

            def _drain(f) -> str:
                f.seek(0)
                data = f.read().decode("utf-8", errors="replace")
                if len(data) > MAX_CHARS:
                    data = data[:MAX_CHARS] + f"\n……（输出过长，已截断，原始 {len(data)} 字符）"
                return data

            stdout, stderr = _drain(out_f), _drain(err_f)

        exit_code = proc.returncode
        parts = [f"exit_code={exit_code}"]
        if killed_reason:
            parts.append(f"（{killed_reason}，进程树已终止）")
        if stdout.strip():
            parts.append(f"--- stdout ---\n{stdout}")
        if stderr.strip():
            parts.append(f"--- stderr ---\n{stderr}")
        return {"ok": exit_code == 0 and killed_reason is None,
                "output": "\n".join(parts), "exit_code": exit_code, "elapsed_ms": elapsed}
