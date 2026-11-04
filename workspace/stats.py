"""演示工作区：故意留了一个 bug，供智能体现场修复。"""


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
