"""把演示工作区恢复到「带 bug」的初始状态（冒烟/演示会把它修掉）。

    python tests/restore_demo_bug.py [workspace 目录]
"""
import sys
from pathlib import Path

BUGGY = '''"""演示工作区：故意留了一个 bug，供智能体现场修复。"""


def mean(nums):
    if not nums:
        return 0            # BUG：空列表应当抛错，而不是静默返回 0
    total = 0
    for n in nums:
        total += n
    return total / len(nums)


def variance(nums):
    m = mean(nums)
    return sum((x - m) ** 2 for x in nums) / len(nums)


def median(nums):
    s = sorted(nums)
    n = len(s)
    if n == 0:
        raise ValueError("median() of empty sequence")
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2
'''

target = Path(sys.argv[1] if len(sys.argv) > 1
              else Path(__file__).resolve().parent.parent / "workspace") / "stats.py"
target.write_text(BUGGY, encoding="utf-8")
print(f"已恢复初始 bug：{target}")
