"""reviewer 子 agent：只读工具 + 固定清单 + 只回最后一条消息。

它存在的唯一理由写在一行里：主上下文只增加「结论」，不增加「过程」。
"""
from __future__ import annotations

import re
from pathlib import Path

from .metrics import token_estimate
from .providers import Provider
from .tools import BashTool, ReadTool, Tool
from .types import Event, Message

REVIEW_CHECKLIST = """检查清单（五条，逐条给结论，无问题写「无」）：
1. 有没有改到不该改的文件（配置、生成物、别人的模块）
2. 有没有新增依赖（requirements / pyproject 的改动）
3. 有没有 except: pass 或裸 except
4. 测试有没有覆盖新分支（改了逻辑但没改测试）
5. diff 里有没有调试残留（print( / TODO / breakpoint(）"""

REVIEWER_SYSTEM = f"""你是只读的代码审查者。你只能读文件和看 git diff，不能改代码。
{REVIEW_CHECKLIST}

只输出最后一份结论：五条各一行 + 「问题总数：N」。不要复述 diff，不要解释过程。
"""


class DiffOnlyBash(Tool):
    """reviewer 的 bash：只放行 git diff / git status / git log。"""

    name = "bash"
    description = "只读 bash：仅允许 git diff / git status / git log 三类命令。"
    schema = {"type": "object",
              "properties": {"command": {"type": "string"}},
              "required": ["command"]}

    def __init__(self):
        self.inner = BashTool()

    def run(self, args: dict, ctx) -> dict:
        cmd = str(args.get("command", "")).strip()
        if not re.match(r"^git\s+(diff|status|log)\b", cmd):
            return {"ok": False,
                    "output": "reviewer 只能执行 git diff / git status / git log，"
                              "改代码请回到主 agent。"}
        return self.inner.run(args, ctx)


def find_issues(diff_text: str) -> dict:
    """真实扫描一份 diff，返回五条清单的结论。给离线策略与测试共用。"""
    added = [l[1:] for l in diff_text.splitlines() if l.startswith("+") and not l.startswith("+++")]
    files = [l[6:].strip() for l in diff_text.splitlines() if l.startswith("+++ b/")]
    issues: dict[str, list[str]] = {k: [] for k in
                                    ("scope", "deps", "except_pass", "tests", "debug")}
    for f in files:
        if f.startswith(("dist/", "build/")) or f.endswith(".env") or "__pycache__" in f:
            issues["scope"].append(f)
    for i, line in enumerate(added):
        nxt = added[i + 1].strip() if i + 1 < len(added) else ""
        if re.search(r"except[^:]*:\s*pass\b", line) or \
                (re.search(r"\bexcept\b[^:]*:", line) and nxt == "pass"):
            issues["except_pass"].append(line.strip())
        if re.search(r"\bprint\(|TODO|breakpoint\(", line):
            issues["debug"].append(line.strip())
    dep_files = [f for f in files if Path(f).name in
                 ("requirements.txt", "requirements-dev.txt", "pyproject.toml")]
    if dep_files:
        issues["deps"].append(", ".join(dep_files))
    changed_code = [f for f in files if f.endswith((".py", ".js", ".ts")) and not f.startswith("tests/")]
    changed_test = [f for f in files if "test" in Path(f).name]
    if changed_code and not changed_test:
        issues["tests"].append(f"改了 {len(changed_code)} 个代码文件但没改测试")
    return issues


def render_review(issues: dict) -> str:
    def first(key: str) -> str:
        return issues[key][0] if issues[key] else "无"

    lines = [f"1. 改到不该改的文件：{first('scope')}",
             f"2. 新增依赖：{first('deps')}",
             f"3. except: pass：{first('except_pass')}",
             f"4. 测试覆盖：{first('tests')}",
             f"5. 调试残留：{first('debug')}"]
    total = sum(len(v) for v in issues.values())
    return "\n".join(lines) + f"\n问题总数：{total}"


class ScriptedReviewerProvider(Provider):
    """离线 review 策略：读 diff → 按清单扫描 → 只吐结论。

    它不是「假模型」，是一条确定性策略：同样的 diff 得到同样的结论，
    方便把 main_context_delta 这类数字固定下来。
    """

    name = "review-policy"

    def stream_chat(self, messages: list[Message], tools: list[dict]):
        last = next((m for m in reversed(messages) if m.role == "user"), None)
        diff = last.content if last else ""
        text = render_review(find_issues(diff))
        yield Event("assistant_done", {"message": Message(role="assistant", content=text)})


class ReviewerTool(Tool):
    name = "spawn_reviewer"
    description = ("派一个只读的 reviewer 子 agent 审阅改动：它有自己的上下文，"
                   "只回五条清单结论 + 问题总数，中间过程不进主上下文。"
                   "可选参数 diff：直接审一段给定的 diff（不传就审工作区的 git diff）。")
    schema = {"type": "object",
              "properties": {"diff": {"type": "string",
                                      "description": "可选，直接给一段 diff 文本"}}}

    def __init__(self, provider: Provider, workspace: Path, model_name: str = ""):
        self.provider = provider
        self.workspace = Path(workspace)
        self.model_name = model_name
        self.stats = {"runs": 0, "issues_found": 0,
                      "main_context_delta": 0, "subagent_tokens": 0}

    def run(self, args: dict, ctx) -> dict:
        from .loop import AgentLoop

        if args.get("diff"):
            diff_text = str(args["diff"])
        else:
            res = BashTool().run({"command": "git diff HEAD"}, ctx)
            diff_text = res.get("output", "")

        task = f"审阅下面这份 diff，按五条清单给结论：\n\n{diff_text[:20000]}"
        nested = AgentLoop(self.provider,
                           {"read": ReadTool(), "bash": DiffOnlyBash()},
                           self.workspace, max_steps=4,
                           enable_skills=False, enable_hooks=False,
                           enable_reviewer=False, system_prompt=REVIEWER_SYSTEM)
        final_text, usage = "", 0
        for ev in nested.run(task):
            if ev.type == "final":
                final_text = ev.data["text"]
            elif ev.type == "turn_usage":
                usage += ev.data["prompt_tokens"] + ev.data["completion_tokens"]

        sub_tokens = usage or token_estimate(REVIEWER_SYSTEM + task + final_text)
        delta = token_estimate(final_text)
        self.stats["runs"] += 1
        self.stats["issues_found"] += _count_issues(final_text)
        self.stats["main_context_delta"] = delta
        self.stats["subagent_tokens"] = sub_tokens
        return {"ok": True, "output": final_text,
                "main_context_delta": delta, "subagent_tokens": sub_tokens}


def _count_issues(text: str) -> int:
    m = re.search(r"问题总数：(\d+)", text)
    if m:
        return int(m.group(1))
    return sum(1 for line in text.splitlines() if re.match(r"^\d\. ", line) and "：无" not in line)
