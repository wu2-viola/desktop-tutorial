"""并行工位的工人：在一个 worktree 目录里干一件独立的活，然后自己跑测试。

被 agent/parallel.py 用绝对路径调起（每个 worktree 一份独立的 cwd），
所以这里只用标准库，不 import agent 包 —— 它跑的是那一侧分支自己的代码。

    python parallel_lane.py --root <worktree> --lane a|b
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

LANES = {
    "a": {
        "task": "新增 agent/slugify.py（标题转 slug）并配测试",
        "module": "agent/slugify.py",
        "test": "tests/test_slugify.py",
        "changelog": "- feat(parallel-a): 新增 `slugify`，把标题转成 URL slug（去除非字母数字、折叠连字符）",
        "code": '''"""把标题转成 URL 安全的 slug（并行工位 A 的活）。"""
from __future__ import annotations

import re


def slugify(text: str) -> str:
    """小写、非字母数字折叠成 -、去掉首尾 -。"""
    folded = re.sub(r"[^a-z0-9]+", "-", text.strip().lower())
    return folded.strip("-")
''',
        "tests": '''from agent.slugify import slugify


def test_slugify_basic() -> None:
    assert slugify("Hello World") == "hello-world"


def test_slugify_strips_punctuation() -> None:
    assert slugify("  Agent: 可验证 & 代码评审!!  ") == "agent"


def test_slugify_collapses_runs() -> None:
    assert slugify("a --- b___c") == "a-b-c"
''',
    },
    "b": {
        "task": "新增 agent/chunk.py（按固定大小切分序列）并配测试",
        "module": "agent/chunk.py",
        "test": "tests/test_chunk.py",
        "changelog": "- feat(parallel-b): 新增 `chunk`，把序列按固定大小切分（批处理用）",
        "code": '''"""把序列按固定大小切块（并行工位 B 的活）。"""
from __future__ import annotations

from typing import Iterable, Sequence, TypeVar

T = TypeVar("T")


def chunk(items: Sequence[T], size: int) -> list[Sequence[T]]:
    """切成每块 size 个，最后一块可以不满。size <= 0 直接报错，不静默返回空。"""
    if size <= 0:
        raise ValueError("size must be positive")
    return [items[i:i + size] for i in range(0, len(items), size)]


def flatten(chunks: Iterable[Sequence[T]]) -> list[T]:
    """分块的反操作：合回去。"""
    out: list[T] = []
    for c in chunks:
        out.extend(c)
    return out
''',
        "tests": '''import pytest

from agent.chunk import chunk, flatten


def test_chunk_sizes() -> None:
    assert chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_chunk_rejects_bad_size() -> None:
    with pytest.raises(ValueError):
        chunk([1], 0)


def test_flatten_roundtrip() -> None:
    data = list(range(7))
    assert flatten(chunk(data, 3)) == data
''',
    },
}


def apply(root: Path, lane: str) -> list[str]:
    spec = LANES[lane]
    (root / "agent").mkdir(parents=True, exist_ok=True)
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / spec["module"]).write_text(spec["code"], encoding="utf-8")
    (root / spec["test"]).write_text(spec["tests"], encoding="utf-8")
    (root / "CHANGELOG.md").write_text(
        "# 变更记录\n\n## 未发布\n\n" + spec["changelog"] + "\n", encoding="utf-8")
    return [spec["module"], spec["test"], "CHANGELOG.md"]


def run_tests(root: Path) -> dict:
    started = time.time()
    r = subprocess.run([sys.executable, "-X", "utf8", "-m", "pytest", "tests", "-q"],
                       cwd=str(root), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=900)
    out = (r.stdout or "") + (r.stderr or "")
    m = re.search(r"(\d+) passed", out)
    f = re.search(r"(\d+) failed", out)
    return {"exit_code": r.returncode, "passed": int(m.group(1)) if m else 0,
            "failed": int(f.group(1)) if f else 0,
            "failed_tests": re.findall(r"^FAILED (\S+)", out, re.M)[:10],
            "elapsed_ms": int((time.time() - started) * 1000),
            "tail": out.strip().splitlines()[-1][:160] if out.strip() else ""}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--lane", required=True, choices=sorted(LANES))
    args = ap.parse_args()
    root = Path(args.root).resolve()
    started = time.time()
    files = apply(root, args.lane)
    tests = run_tests(root)
    print(json.dumps({"lane": args.lane, "task": LANES[args.lane]["task"], "files": files,
                      "pytest": tests, "elapsed_ms": int((time.time() - started) * 1000)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
