# demo —— DeepSeek 真模型一次完整运行记录

命令：`python cli.py "mean 对空列表的处理有问题，改掉，改完跑测试验证"`
模型：`deepseek-chat`（流式），共 6 轮决策、11 次工具调用，其中 3 次失败后模型自行纠正。
以下为真实终端输出节选（原样保留，未改写模型行为）。

## 第 1 轮：先看现场 —— MCP 工具 + bash 失败自救

模型第一步没有直接改代码，而是调用了 **MCP 工具**统计工作区：

```
[mcp__demo__workspace_stats] ok (34ms)
工作区统计：文件 2 个，目录 0 个；Python 文件 2 个，共 56 行。
```

接着用 bash 列目录，第一次失败：

```
[bash] 失败 (248ms)
exit_code=255
--- stderr ---
'ls' is not recognized as an internal or external command
```

> Linux 命令在 Windows 上不存在 —— 工具把失败如实返回，模型下一轮自己纠正为 `dir`。
> 这正是「失败不中断会话」的设计意图。

## 第 2 轮：read 两个文件 + 先跑测试复现问题

```
[read] ok (0ms)      stats.py（看到第 6 行的 BUG 注释）
[read] ok (7ms)      test_stats.py（看到 test_mean_empty_raises 期望 ValueError）
```

```
先跑一遍测试确认当前失败，再改。
[bash] 失败 (444ms)
FAIL: test_mean_empty_raises ... AssertionError: ValueError not raised
```

> 先复现、再修改 —— 这是模型从系统提示词里的规则学到的规范流程。

## 第 3 轮：edit 修复（带最小 diff）

```
[edit] ok (6ms)
已替换 1 处。
@@ -5,3 +5,3 @@
     if not nums:
-        return 0            # BUG：空列表应当抛错，而不是静默返回 0
+        raise ValueError("mean() of empty sequence")
```

## 第 4 轮：bash 重跑测试 —— 6/6 全过

```
[bash] ok (522ms)   exit_code=0
Ran 6 tests in 0.002s   OK
```

## 第 5 轮：主动验证附带影响

模型注意到 `variance()` 内部调用 `mean()`，额外验证了空列表场景：
`variance([])` 现在在 `mean()` 处快速抛 `ValueError`，而不是走到 `sum(...)/0` 的
`ZeroDivisionError`。（这轮有一次多行 `-c` 在 Windows 下失败的自救，同属真实记录。）

## 第 6 轮：总结（final）

> **改了什么**：`stats.py` 第 5–6 行，`mean()` 的空列表分支从 `return 0` 改为
> `raise ValueError("mean() of empty sequence")`，与同文件 `median()` 保持一致。
> **怎么验证的**：改前复现 1 个用例失败，改后 6 个用例全部 OK，exit code 0。
> **附带影响已确认**：`variance()` 的空列表行为随之修正，并建议补一个契约测试。

## 本次运行证明的事

| 设计点 | 在这次运行里的体现 |
|---|---|
| 工具失败不中断会话 | `ls` / 多行 `-c` 两次失败，模型看到观察后自行纠正 |
| MCP 真实集成 | 第一步就调用了 `mcp__demo__workspace_stats` |
| edit 唯一性 + diff | 一次替换成功，返回最小 diff |
| 失败标红 / 证据链 | 先复现失败 → 修复 → 重跑全过 |
| token 用量可见 | 每轮打印 `[tokens] +输入/输出`，全程累计约 3200 输入 |
