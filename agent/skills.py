"""技能系统：目录常驻、正文按需（渐进披露）。

- 启动只拼 name + description（catalog）
- 模型调 use_skill(name) 时正文才进上下文
- 触发靠 description 里的「触发语」，不靠文件名
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .metrics import token_estimate

_QUOTED = re.compile(r"[“\"]([^”\"]{1,40})[”\"]")
_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{2,}")


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path
    has_scripts: bool = False
    uses_mcp: bool = False
    triggers: list[str] = field(default_factory=list)


def _parse(text: str) -> tuple[dict, str]:
    """极简 front matter 解析：只认 name / description 两行，不引 YAML 依赖。"""
    if not text.startswith("---"):
        raise ValueError("SKILL.md 缺少 YAML 头（第一行必须是 ---）")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("SKILL.md 的 YAML 头没有闭合")
    meta: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, parts[2].lstrip("\n")


def load_skills(root: Path) -> list[Skill]:
    skills: list[Skill] = []
    if not root.exists():
        return skills
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        f = d / "SKILL.md"
        if not f.exists():
            continue
        meta, body = _parse(f.read_text(encoding="utf-8"))
        name = meta.get("name", d.name)
        if name != d.name:
            raise ValueError(f"技能名与目录不一致：{name} != {d.name}")
        desc = meta.get("description", "")
        if "Use this when" not in desc:
            raise ValueError(f"{name}: description 里必须有 Use this when 触发语")
        triggers = [t for t in _QUOTED.findall(desc) if t.strip()]
        skills.append(Skill(name=name, description=desc, body=body, path=d,
                            has_scripts=(d / "scripts").is_dir(),
                            uses_mcp="mcp__" in body or "mcp__" in desc,
                            triggers=triggers))
    return skills


def catalog_text(skills: list[Skill]) -> str:
    """常驻上下文的那张目录表：每个技能一行。"""
    lines = ["可用技能目录（先看 description 判断，需要时调 use_skill(name) 读取完整流程）："]
    for s in skills:
        lines.append(f"- {s.name}：{s.description}")
    return "\n".join(lines)


def full_text(skills: list[Skill]) -> str:
    """如果全部塞进上下文的对照值（作业里 disclosure_ratio 的分母）。"""
    out = []
    for s in skills:
        out.append(f"# {s.name}\n\n{s.description}\n\n{s.body}")
    return "\n\n".join(out)


def _bigrams(s: str) -> set[str]:
    s = re.sub(r"\s+", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def score(skill: Skill, query: str) -> int:
    """把 query 和技能的触发语对照打分：短语命中 3 分，中文二元组 1 分，英文词 2 分。"""
    q = query.lower()
    latin = {w.lower() for w in _LATIN.findall(skill.description)}
    s = 0
    for t in skill.triggers:
        tl = t.lower()
        if tl in q:
            s += 3
        s += sum(1 for bg in _bigrams(tl) if bg in q)
    s += 2 * sum(1 for w in latin if w in q)
    return s


def route(query: str, skills: list[Skill], threshold: int = 2) -> Skill | None:
    """description 驱动的路由：最高分且过阈值才命中，否则返回 None（闲聊不触发）。"""
    best, best_score = None, 0
    for skill in skills:
        sc = score(skill, query)
        if sc > best_score:
            best, best_score = skill, sc
    return best if best_score >= threshold else None


class UseSkillTool:
    """把技能正文按需注入上下文；它就是渐进披露的开关。"""

    name = "use_skill"
    description = ("按需加载一个技能的完整流程正文。先看系统提示里的技能目录，"
                   "判断当前任务命中某个技能的 description 后再调用，不要凭名字猜。")
    schema = {"type": "object",
              "properties": {"name": {"type": "string", "description": "技能名，如 run-tests"}},
              "required": ["name"]}

    def __init__(self, skills: list[Skill]):
        self.skills = {s.name: s for s in skills}

    def run(self, args: dict, ctx) -> dict:
        name = str(args.get("name", "")).strip()
        skill = self.skills.get(name)
        if skill is None:
            return {"ok": False,
                    "output": f"没有这个技能：{name}。可用：{', '.join(self.skills)}"}
        ctx.loaded_skills.add(name)
        return {"ok": True,
                "output": f"技能 {name} 已加载（正文 {token_estimate(skill.body)} token）\n\n{skill.body}"}

    def spec(self) -> dict:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description,
                             "parameters": self.schema}}
