"""增量 F：让它审自己 —— review 子命令 + 召回率/误报的算法化考核。

评审器是规则型的：每条意见都能追到 diff 的哪一行、哪条规则，可复现、不花 token。
语料是 `docs/review/corpus.json`：12 个 PR，其中 10 个埋了已知 bug、4 个是干净的，
所以「召回」与「误报」都能算出来，而不是自我表扬。

    python -m app.inspect review --out review_report.json
    python cli.py review                      # 智能体入口的同名子命令
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPUS = REPO / "docs" / "review" / "corpus.json"
SUMMARY_PATH = REPO / "docs" / "review" / "summary_comment.md"
LINE_TOLERANCE = 2          # 意见落在 bug 行 ±2 行内算命中（评审允许指到邻近行）


# ---------------- diff 解析 ----------------
def parse_diff(text: str) -> list[dict]:
    """返回新增行：[{file, line(新文件行号), code}]，非新增行不进候选。"""
    out: list[dict] = []
    cur, lineno = "", 0
    for raw in text.splitlines():
        if raw.startswith("+++ "):
            cur = raw[4:].strip()
            cur = cur[2:] if cur.startswith("b/") else cur
            continue
        if raw.startswith("--- ") or raw.startswith("diff --git"):
            continue
        m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
        if m:
            lineno = int(m.group(1))
            continue
        if not cur or raw.startswith("-"):
            continue
        if raw.startswith("+"):
            code = strip_comment(raw[1:])
            out.append({"file": cur, "line": lineno, "code": code})
            lineno += 1
        else:                                    # 上下文行
            lineno += 1
    return out


def strip_comment(line: str) -> str:
    """去掉行尾注释：注释里写 `x == None` 不该被当成 bug。"""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote and line[i - 1] != "\\":
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return line[:i].rstrip()
    return line.rstrip()


# ---------------- 规则 ----------------
def _guarded(prev: list[str]) -> bool:
    joined = " ".join(prev[-4:])
    return bool(re.search(r"if not |len\([^)]*\)\s*==\s*0|==\s*0|<= 0|raise ", joined))


RULES = [
    {"kind": "mutable-default",
     "message": "可变默认参数（list/dict/set）会在调用间共享，改成 None 再在函数里初始化",
     "hit": lambda c, p, n: bool(re.search(r"def \w+\(.*=\s*(\[\]|\{\}|set\(\))", c))},
    {"kind": "bare-except",
     "message": "裸 except 会连 KeyboardInterrupt 一起吞掉，写明确的异常类型",
     "hit": lambda c, p, n: bool(re.match(r"\s*except\s*:", c))},
    {"kind": "swallowed-error",
     "message": "except 里直接 pass，错误被吞：至少记日志或返回明确的失败结果",
     "hit": lambda c, p, n: bool(re.match(r"\s*except\b[^:]*:", c)) and n.strip() == "pass"},
    {"kind": "eq-none",
     "message": "判断空值用 `is None` / `is not None`，`== None` 对自定义 __eq__ 会失灵",
     "hit": lambda c, p, n: bool(re.search(r"[=!]=\s*None", c))},
    {"kind": "open-no-with",
     "message": "open 没有配 with：异常路径下句柄不会关，改成 `with open(...) as f`",
     "hit": lambda c, p, n: "open(" in c and "with " not in c and "with(" not in c},
    {"kind": "division-by-zero",
     "message": "除数是 len()，空输入会 ZeroDivisionError：先判空再除",
     "hit": lambda c, p, n: bool(re.search(r"/\s*len\(", c)) and not _guarded(p)},
    {"kind": "off-by-one",
     "message": "range(len(x)) 里取 [i + 1]，最后一个下标越界：range(len(x) - 1) 或 zip(x, x[1:])",
     "hit": lambda c, p, n: bool(re.search(r"\[\s*i\s*\+\s*1\s*\]", c))
     and any(re.search(r"range\(len\(", x) for x in p[-3:])},
    {"kind": "sql-injection",
     "message": "f-string 拼 SQL，参数没走占位符：改成参数化查询",
     "hit": lambda c, p, n: bool(re.search(r"f[\"'].*(SELECT|INSERT|UPDATE|DELETE)\b.*\{", c, re.I))},
]


def review_diff(text: str, pr_id: str = "") -> list[dict]:
    added = parse_diff(text)
    comments: list[dict] = []
    for i, item in enumerate(added):
        prev = [x["code"] for x in added[max(0, i - 4):i]]
        nxt = added[i + 1]["code"] if i + 1 < len(added) else ""
        for rule in RULES:
            if rule["hit"](item["code"], prev, nxt):
                comments.append({"pr": pr_id, "file": item["file"], "line": item["line"],
                                 "kind": rule["kind"], "message": rule["message"],
                                 "quote": item["code"].strip()[:120]})
                break                              # 一行只报一条最相关的
    return comments


# ---------------- 考核 ----------------
def evaluate(corpus_path: Path | str = CORPUS) -> dict:
    corpus_path = Path(corpus_path)
    data = json.loads(corpus_path.read_text(encoding="utf-8"))
    started = time.time()
    prs, hits, fps, comments_total, bugs_total = [], 0, 0, 0, 0

    for pr in data["prs"]:
        comments = review_diff(pr["diff"], pr["id"])
        comments_total += len(comments)
        bugs = []
        for bug in pr.get("bugs", []):
            match = next((c for c in comments
                          if c["file"] == bug["file"]
                          and abs(c["line"] - bug["line"]) <= LINE_TOLERANCE), None)
            bugs.append({**bug, "hit": bool(match),
                         "hit_by": match["kind"] if match else None,
                         "hit_line": match["line"] if match else None})
        bugs_total += len(bugs)
        hits += sum(1 for b in bugs if b["hit"])
        matched = {id(b) for b in bugs if b["hit"]}
        fp = []
        for c in comments:
            ok = any(c["file"] == b["file"] and abs(c["line"] - b["line"]) <= LINE_TOLERANCE
                     for b in bugs)
            if not ok:
                fp.append(c)
        fps += len(fp)
        prs.append({"id": pr["id"], "title": pr["title"], "clean": not bugs,
                    "comments": comments, "bugs": bugs,
                    "false_positives": [{"file": c["file"], "line": c["line"],
                                         "kind": c["kind"]} for c in fp],
                    "bug_count": len(bugs),
                    "hit_count": len(matched)})

    recall = round(hits / bugs_total, 3) if bugs_total else 0.0
    precision = round(hits / comments_total, 3) if comments_total else 0.0
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "corpus": str(corpus_path),
        "reviewer": {"type": "rule-based", "rules": [r["kind"] for r in RULES],
                     "line_tolerance": LINE_TOLERANCE,
                     "note": "规则型：每条意见可追到 diff 行号与规则名，可复现、不花 token"},
        "prs": prs,
        "totals": {"prs": len(prs), "clean_prs": sum(1 for p in prs if p["clean"]),
                   "bugs": bugs_total, "hits": hits, "recall": recall,
                   "comments": comments_total, "false_positives": fps,
                   "precision": precision},
        "verdict": {"pass": bool(bugs_total and recall >= 0.6 and fps <= 3),
                    "checks": {"召回 ≥ 60%": recall >= 0.6,
                               "误报 ≤ 3 条": fps <= 3}},
        "duration_ms": int((time.time() - started) * 1000),
    }
    report["summary_comment"] = summary_comment(report)
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(report["summary_comment"], encoding="utf-8")
    return report


def summary_comment(report: dict) -> str:
    t = report["totals"]
    missed = [f"{p['id']}（{b['file']}:{b['line']} {b['kind']}）"
              for p in report["prs"] for b in p["bugs"] if not b["hit"]]
    fps = [f"{p['id']}（{f['file']}:{f['line']} {f['kind']}）"
           for p in report["prs"] for f in p["false_positives"]]
    lines = [
        f"### review 汇总：{t['bugs']} 个已知 bug 命中 {t['hits']}，"
        f"召回 {t['recall'] * 100:.0f}%；误报 {t['false_positives']} 条",
        "",
        f"- 语料：{t['prs']} 个 PR（{t['bugs']} 个 bug 埋在 "
        f"{t['prs'] - t['clean_prs']} 个 PR 里，{t['clean_prs']} 个干净），"
        f"共出 {t['comments']} 条意见，精确率 {t['precision'] * 100:.0f}%",
        f"- 漏掉：{'、'.join(missed) if missed else '无'}",
        f"- 误报：{'、'.join(fps) if fps else '无'}",
        "- 结论：" + ("及格线（召回 ≥ 60%、误报 ≤ 3）通过" if report["verdict"]["pass"]
                     else "未过及格线，规则要补"),
        "- 局限：规则型评审只认模式，认不出语义 bug（比如「逻辑对但业务错」）——"
        "这类得靠人，或者把模型接进来当第二层。",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    out = "review_report.json"
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
    report = evaluate()
    Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    print(report["summary_comment"])
    print(json.dumps({"totals": report["totals"], "verdict": report["verdict"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
