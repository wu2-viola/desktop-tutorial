# trace —— 一次完整运行记录

命令：`python cli.py --offline "修复 mean 对空列表的处理"`（离线 mock，断网可复现）。
真实终端输出原样粘贴，含一次「先失败、再自救」的过程。

## 第 0 步：启动

```
[MCP] demo: ok ['mcp__demo__workspace_stats', 'mcp__demo__note_add']
[provider] 离线 mock（未配置 Key）
```

## 第 1 步：read —— 先看原文，不瞎猜

```
先看一下现状。
[read] ok (2ms)
     1\t"""演示工作区：故意留了一个 bug，供智能体现场修复。"""
     4\tdef mean(nums):
     5\t    if not nums:
     6\t        return 0            # BUG：空列表应当抛错，而不是静默返回 0
    ...
```

## 第 2 步：第一次 edit —— 失败（唯一性检查拒绝）

早期开发中，mock 给的 old 是 `        return 0`，而文件里空格数不同：

```
[edit] 失败 (8ms)
找不到要替换的字符串（0 次）。先 read 确认原文，注意空格与缩进。
```

模型按观察纠正上下文后重试，成功：

```
把空列表静默返回 0 改成抛错。
[edit] ok (45ms)
已替换 1 处。
@@ -5,3 +5,3 @@
     if not nums:
-        return 0            # BUG：空列表应当抛错，而不是静默返回 0
+        raise ValueError("mean() of empty sequence")
     total = 0
```

> 这就是 edit 唯一性检查的价值：错了就明说，绝不猜。

## 第 3 步：bash —— 跑测试拿证据

```
跑测试验证。
[bash] ok (1243ms)
exit_code=0
--- stdout ---
......                                                                   [100%]

6 passed in 0.04s
```

## 第 4 步：总结

```
修好了：mean 对空列表抛 ValueError，不再静默返回 0；全部测试通过。
=== 完成 ===
```

## 另一条护栏的真实记录：兜圈子

同一调用连续 3 次会直接叫停（事件流里是 `stopped`）：

```
data: {"type": "stopped", "reason": "同一调用连续 3 次判定为兜圈子，直接叫停"}
```

步数到上限同理：`步数上限（12 步）已到，先停给你看`。

## 用真模型复现

设置里配好 DeepSeek Key 后，同一条命令把 `--offline` 去掉即可：

```
python cli.py "修复 mean 对空列表的处理"
```

（真实模型的轨迹每次都不同 —— 这正是演示时值得现场跑的原因。）
