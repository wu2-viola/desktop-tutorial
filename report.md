# report —— 增量作业（v1.1–v1.3）

数字全部来自 `python -m app.inspect skills|custom|daemon --out *.json`，不手写。

## 一、技能：preload 和 on-demand 的真实差价

**做法**：`skills/<名字>/SKILL.md`，YAML 头里 `name` + `description`（含 `Use this when` 触发语）。
启动只把「目录」拼进 system prompt；模型调 `use_skill(name)` 时正文才注入。

**三种形态都做了**：

| 技能 | 形态 | 为什么是这个形态 |
|---|---|---|
| `run-tests` | 纯提示词 | 步骤就是知识，没有可跑的代码 |
| `review-diff` | 提示词 + `scripts/collect_diff.py` | 「把 diff 收窄到 400 行」写死在脚本里比写死在提示词里可靠 |
| `fetch-issue` | 提示词 + MCP（`mcp__demo__issue_get`） | issue 正文只能从外部拿，技能不该自己造数据 |

**数字**（`skill_report.json`）：

- 目录 `catalog_tokens = 181`，全文 `full_tokens = 1407`，`disclosure_ratio = 7.8`
- 8 条触发试验全部符合预期（6 条正例 + 2 条负例「天气」「写诗」）
- `false_positive = 0` —— 负例没有误触发，靠的是「描述驱动 + 阈值」，不是文件名匹配

如果把三个技能常驻，每轮都要多付约 1400 token；按一次任务 6 轮算，就是 8000+ token
的纯浪费。**渐进披露省掉的是「用不上的正文」，不是「用不上的能力」。**

路由实现在 `agent/skills.py:route()`：从 description 的触发语里抽中文二元组和英文词，
短语命中 3 分、英文词 2 分、二元组 1 分，阈值 2 分。它不是模型，是**可复现的判据**——
试验表能重跑，才敢说 `false_positive = 0`。

## 二、定制：AGENTS.md 是软的，hooks 是硬的

**AGENTS.md 两层**（`agents_md.json`）：

- `layers = ["global", "project"]`，`bytes = 2564`（拆开规则：>300 行就拆）
- 全局层：`~/.desktop-tutorial/AGENTS.md`（跨项目偏好），缺失时回落仓库自带
  `docs/agents-global.md`，保证换台机器 clone 下来仍是两层
- 项目层：从工作区往上找最近的 `AGENTS.md`（最多 5 层），本仓库根目录那份

它是「地图不是文档」：路径 → 职责，命令 → 怎么跑，坑 → 别踩。
写「写代码要优雅」等于没写；写「`python -m pytest tests -q`，不要 `-v`」才可执行。

**三个 hook 都在代码里**（`custom_report.json`）：

| Hook | 规则 | 拒绝时给的替代方案 |
|---|---|---|
| PreToolUse | 写 `.env` / `*.pem` / `*.key` | 「密钥不入库，用环境变量」 |
| PreToolUse | `rm -rf` | 「先 `git clean -nd` 看会删什么，或 `git restore <file>`」 |
| PreToolUse | `git push --force` / `git reset --hard` | 「`git revert <sha>` / `git stash` / `git restore <file>`」 |
| PostToolUse | write/edit 之后自动跑测试 | 只回三行：哪个用例 / 期望 / 实际 |

**自动测试真跑过两轮红绿**：`runs=4, red=2, green=2, red_to_green=2, injected_lines=6`
（每次红回注 3 行，`6 = 3 × 2`）。这不是模拟：`agent/inspect.py:_autotest_scenario`
把 workspace 拷到临时目录，真调 edit 工具、真跑 pytest。

**reviewer 子 agent**：只读（read + `git diff`），固定五条清单，只回最后一条消息。

- `subagent_tokens = 329`（它读了整份 diff）
- `main_context_delta = 56`（主上下文只多了结论）
- `issues_found = 5`，与 `docs/sample-review.diff` 里植入的 5 处问题一一对应

**取舍**：hooks 只做确定性、可枚举的规则。复杂的「这段代码安不安全」交给 reviewer，
因为 hook 该是硬约束，不是第二个模型。

**这一节里两个真实的判断错误**（不是「我早就想到了」）：

1. 一开始让 PostToolUse 用 `pytest -v` 拿失败详情。结果工具卡片被几十行 PASSED 撑满，
   主上下文反而看不到 `FAILED`。改成 `-q --tb=line` + 只回三行摘要，`injected_lines`
   才稳定在 `3 × 红次数`。
2. reviewer 第一版把「审阅过程 + diff 片段」一起回给主 agent，`main_context_delta`
   直接飙到 800+，等于没隔离。改成「只回最后一条消息（五条结论 + 问题总数）」后
   降到 56 —— 子 agent 的价值在于**过程不进主上下文**，不在于它多聪明。

## 三、常驻（选做增量 C）

作业要求四选二，这里四个都做了：

| 能力 | 实现 | 证据字段 |
|---|---|---|
| 崩溃续跑 | 每步 turn 原子落盘 checkpoint，`executed_calls` 保证幂等 | `resume_from_step: 3`、`replayed_tools: 0` |
| 定时触发 | `routines.yaml`（`every_seconds` / 每日 `at`），到点跑一个 skill | `triggers_fired: 3` |
| 事件触发 | 轮询目录变化 → 队列 → 消费（标准库，不引 watchdog） | `event_triggers_fired: 3` |
| 完成通知 | Windows toast + 日志双通道 | `notify_fired: true`、`notify_channels: [windows-toast, log]` |

`daemon_report.json` 的实测数字：杀在 `step=2`、当时只执行了 1 个工具；`resume` 从
**第 3 步**继续，补完 4 个调用，总数 5 且 `replayed_tools = 0`；第二次 `resume` 命中
`done` 直接跳过（`idempotent: true`）。整个验收 6.6 秒，不靠人手点。

**三段真实的翻车，正好是这道题的全部难点**：

1. **provider 有状态 = 续跑变重播**。`MockProvider` 用 `self._turn` 计步，进程重启后
   归零，resume 会从第 1 幕重新演一遍。改成 `ScriptedLongProvider`：第几幕只看
   `messages` 里有几条 tool 结果 —— **状态在消息里，不在 provider 里**。
2. **`read_paths` 没落盘 = 续跑后第一次 edit 被自己的护栏拦下**。v1.0 的硬护栏要求
   「edit 前必须 read」，但那是 `ToolContext` 的内存字段。重启后它空了，edit 直接红。
   修法：resume 时扫历史里的 `read` 调用 + 对应 tool 结果，把 `read_paths` 重建出来。
   护栏不能因为「重启」而失效，也不能因为「重启」而误伤。
3. **幂等跳过误伤了兜圈子判定**。第一版 resume 用 `if call.id in executed: continue`，
   结果同进程里模型重复发起同一个 id 也被跳过 —— `LoopDetected` 永远不触发，
   `test_loop` 直接红。改成 `skip_once`：**只跳「上个进程执行过」的那一次**，
   同进程内的重复仍交给兜圈子判定。

**取舍**：`routines.yaml` 用 30 行迷你解析器，不引 pyyaml —— 只认四个字段，
认不出来就报错，而不是静默忽略。cron 全语法不做：`every_seconds` + 每日 `at`
已经覆盖「定时跑 skill」，多出来的表达力换不来收益。

## 四、取舍与不做

- **技能只做三个**：三个形态（纯提示词 / 带脚本 / 走 MCP）已经覆盖了所有写法，
  再加第四个只是复制粘贴，不增长信息。
- **reviewer 用离线策略做验收数字**：`ScriptedReviewerProvider` 是确定性策略，
  同样 diff 得同样结论，所以 `main_context_delta` 可复现。真实使用时换成 DeepSeek，
  子 agent 结构不变（界面里点「技能」开关跑一次就能看到）。
- **开关默认开**：`ENABLE_SKILLS=0` / `ENABLE_HOOKS=0` / `ENABLE_SUBAGENT=0` 一键关掉，
  用来演示「有了它 / 没它」的差别 —— 说不出差别的功能，等于没做。
- **没做更大的常驻件**：分布式队列、系统托盘、多机抢占。当前的 daemon 是单机单进程，
  够演「关掉终端还能被唤醒」，不够演「一个团队共享一个常驻 agent」——后者要先解决
  锁与租约，不是这次作业的范围。

## 附：v1.0 基线报告（架构 / 打包 / 取舍 / 再加一个工具）

### 架构

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

### 打包

见 [docs/build.md](docs/build.md)。三个坑各有一段处理代码，不是文档话术。

### 取舍（v1.0 阶段）

- **没做多会话**：一次跑一个任务，第二个任务会被 409 拒绝。两周内做对「单会话的
  停」比做对「多会话的乱」值钱。
- **没做流式 diff 预览**：edit 的 diff 在工具卡片里展示，不做「确认后再改」。
  中断按钮已经给了后悔权，确认弹窗属于优秀档之外的加餐。
- **mock 不是玩具**：离线 mock 走的是同一条循环、同一套工具，CI 和断网演示都靠它。

### 如果只能再加一个工具：grep

1. bash 里的 `findstr`/`grep` 输出格式不可控，Windows/Unix 还不一致；
2. edit 的唯一性检查需要「这个字符串出现在哪几行」，read + 分页读大文件太浪费
   —— grep 直接给行号，是 edit 的前置依赖；
3. 它仍然是只读的，不扩大模型的破坏面。
