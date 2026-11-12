"""增量 F：评审器的规则与召回率考核。"""
from __future__ import annotations

from agent.review import evaluate, parse_diff, review_diff, strip_comment


def test_parse_diff_counts_new_lines() -> None:
    diff = ("--- /dev/null\n+++ b/a.py\n@@ -0,0 +1,3 @@\n+import os\n+\n+print(os)\n")
    added = parse_diff(diff)
    assert [a["line"] for a in added] == [1, 2, 3]
    assert all(a["file"] == "a.py" for a in added)


def test_parse_diff_only_keeps_added_lines() -> None:
    """评审只对新增行出意见；删掉的行和上下文行不进候选，但行号要跟着走。"""
    diff = ("--- a/b.py\n+++ b/b.py\n@@ -1,2 +1,2 @@\n-old = 1\n+new = 2\n keep = 3\n")
    added = parse_diff(diff)
    assert [a["code"] for a in added] == ["new = 2"]
    assert [a["line"] for a in added] == [1]


def test_strip_comment_keeps_string_hash() -> None:
    assert strip_comment('x = "a#b"  # 注释') == 'x = "a#b"'
    assert strip_comment("# 整行注释") == ""


def test_comment_mentioning_bug_is_not_a_comment_on_code() -> None:
    """注释里写 `== None` 不该被判成 bug（pr10 的考点）。"""
    diff = ("--- /dev/null\n+++ b/n.py\n@@ -0,0 +1,2 @@\n"
            "# 不要写 x == None\n+y = 1\n")
    assert review_diff(diff) == []


def test_each_rule_fires_on_its_pattern() -> None:
    cases = {
        "mutable-default": "def f(x, acc=[]):",
        "bare-except": "    except:",
        "eq-none": "    if v == None:",
        "open-no-with": "    f = open(path)",
        "division-by-zero": "    return total / len(nums)",
        "off-by-one": "        best = items[i] + items[i + 1]",
        "sql-injection": "    sql = f\"SELECT * FROM t WHERE a = '{x}'\"",
    }
    for kind, code in cases.items():
        diff = f"--- /dev/null\n+++ b/x.py\n@@ -0,0 +1,1 @@\n+{code}\n"
        if kind == "off-by-one":       # 需要上文里有 range(len(...))
            diff = ("--- /dev/null\n+++ b/x.py\n@@ -0,0 +1,2 @@\n"
                    "+    for i in range(len(items)):\n"
                    "+        best = items[i] + items[i + 1]\n")
        comments = review_diff(diff)
        assert [c["kind"] for c in comments] == [kind], (kind, comments)


def test_guarded_division_is_not_reported() -> None:
    diff = ("--- /dev/null\n+++ b/x.py\n@@ -0,0 +1,3 @@\n"
            "+    if not nums:\n"
            "+        raise ValueError('empty')\n"
            "+    return sum(nums) / len(nums)\n")
    assert review_diff(diff) == []


def test_corpus_meets_pass_line() -> None:
    report = evaluate()
    assert report["totals"]["bugs"] >= 8
    assert report["totals"]["recall"] >= 0.6
    assert report["totals"]["false_positives"] <= 3
    assert report["verdict"]["pass"] is True
    assert report["summary_comment"].startswith("### review 汇总")
