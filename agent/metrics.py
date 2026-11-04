"""token 估算 —— 所有报告里的数字都出自这里，保证「程序打印」而不是手写。

估算规则（写进 README 与报告，可复现）：
- 一个 CJK 字符算 1 token
- 一段连续 ASCII 字母数字按 4 字符 1 token 向上取整
这不是分词器，是一个稳定的相对度量：用来比较「目录」和「全文」的 25 倍差。
"""
from __future__ import annotations

import re

_CJK = re.compile(r"[\u4e00-\u9fff]")
_ASCII = re.compile(r"[A-Za-z0-9_]+")


def token_estimate(text: str) -> int:
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    words = sum(max(1, len(w) // 4) for w in _ASCII.findall(text))
    return max(1, cjk + words)
