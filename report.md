# report —— 架构 / 打包 / 取舍 / 再加一个工具

## 架构

```
ui/ (三栏)  ──SSE──▶  server/ (FastAPI)  ──▶  agent/loop (决策→动作→观察→再决策)
                                                │            │
                                       agent/providers    agent/tools
                                       (DeepSeek/mock)    read/write/edit/bash
                                                │            ▲
                                              mcp/client ◀──┘ mcp__ 前缀合并进注册表
                                                │
                                          MCP server 子进程 (stdio JSON-RPC)
```

三个关键决定：

1. **UI 和循环解耦**：循环产出统一的 Event 流，CLI、SSE、UI 消费同一种流。
   证据：`cli.py` 与桌面窗口跑的是同一个 `agent/loop.py`，关掉前端 `curl -N`
   照样能看到完整事件流。
2. **Key 不经过前端**：UI 只能 POST Key，存到用户目录；任何 GET 返回的都是掩码
   （`tests/test_config.py` 有断言）。前端直调模型是本作业明令禁止的事。
3. **工具少而硬**：四个工具各守一条语义 —— read 分页、write 原子、edit 唯一、
   bash 有超时。每条语义都有测试盯着。

## 打包

见 [build.md](build.md)。三个坑各有一段处理代码，不是文档话术。

## 取舍（什么没做，为什么）

- **没做多会话**：一次跑一个任务，第二个任务会被 409 拒绝。两周内做对「单会话的
  停」比做对「多会话的乱」值钱。
- **没做流式 diff 预览**：edit 的 diff 在工具卡片里展示，不做「确认后再改」。
  中断按钮已经给了后悔权，确认弹窗属于优秀档之外的加餐。
- **mock 不是玩具**：离线 mock 走的是同一条循环、同一套工具，CI 和断网演示都靠它。
  这也是「providers 抽层」的直接收益。

## 如果只能再加一个工具：grep

四工具已经很省，但如果必须加，我加 **grep**（内容搜索），理由：

1. bash 里的 `findstr`/`grep` 输出格式不可控，Windows/Unix 还不一致；
2. edit 的唯一性检查需要「这个字符串出现在哪几行」，read + 分页读大文件太浪费
   —— grep 直接给行号，是 edit 的前置依赖；
3. 它仍然是只读的，不扩大模型的破坏面。
