# Desktop Agent：桌面智能体课程作业

## 1. 项目简介

Desktop Agent 是一个基于 Python、pywebview 和 DeepSeek 模型接口开发的桌面智能体课程项目，双击即出窗口（有标题栏的桌面应用，不是 localhost 网页）。

项目将大语言模型与本地工具结合，智能体按「决策 → 动作 → 观察 → 再决策」循环工作，工具调用全程可见、可中断。

## 界面截图

| 主界面（三栏） | 工具调用过程 | 工具卡片特写 |
|---|---|---|
| ![主界面](docs/screenshots/01-main.png) | ![工具调用](docs/screenshots/02-tools.png) | ![卡片](docs/screenshots/03-cards.png) |

图 2 是一次真实运行：中间是对话与结论（markdown 渲染、输入框常驻），右侧 trace 栏逐条显示每个工具调用的成功/失败与耗时；`docs/screenshots/demo.mp4` 是三任务的完整演示录屏（修复 bug → 跑测试并总结 → 审查改动，真模型一镜到底）。

增量作业另有六段演示录屏 `docs/screenshots/demo_增量.mp4`：三技能三形态、渐进披露开关对比、hook 拦截、红灯回注（red_to_green）、reviewer 上下文隔离、kill -9 续跑——全部由 `cli.py` / `python -m app.inspect` 真实输出逐段生成。

## 2. 主要功能

### 2.1 桌面交互界面

- 三栏布局：左侧资源浏览、中间代码查看（带行号）、右侧对话与工具调用
- 工具调用逐条展示（含 diff 绿加红减、失败标红）
- 随时中断正在运行的任务；API Key 通过界面设置，不经过前端存储

### 2.2 DeepSeek 模型接入

通过 OpenAI 兼容接口流式调用 DeepSeek 模型。未配置 Key 时自动切换离线 mock，仍可走完整循环（演示与 CI 均不依赖网络）。

### 2.3 本地工具

| 工具 | 功能 |
|---|---|
| `read` | 按行读取工作区文件，大文件自动分页，图片走多模态块 |
| `write` | 覆盖写入，自动建父目录，临时文件 + rename 原子写 |
| `edit` | 精确字符串替换，old 不唯一时拒绝并列出行号，返回最小 diff |
| `bash` | 在工作区执行命令，返回 stdout/stderr/exit_code，超时杀进程树 |

### 2.4 技能系统（渐进披露）

`skills/` 下每个技能一个文件夹，`SKILL.md` 的 YAML 头写 `name` + `description`（含触发语）。

- 启动时**只注入目录**（名字 + 一句话描述），正文不进上下文
- 模型判断命中后调 `use_skill(name)`，正文才注入
- 三种形态都有实例：纯提示词（`run-tests`）、带脚本（`review-diff` + `scripts/collect_diff.py`）、
  走 MCP（`fetch-issue` + `mcp__demo__issue_get`）
- 目录 181 token，全文 1407 token，比值 7.8（`skill_report.json`）

### 2.5 定制层

- **AGENTS.md 两层注入**：全局（`~/.desktop-tutorial/AGENTS.md`）+ 项目（工作区往上找最近一份），
  内容是「地图」不是文档：路径→职责、命令→怎么跑、坑→别踩
- **三个 hook（代码级）**：写 `.env`/`*.pem`/`*.key` 拒绝；`rm -rf`、`git push --force`、
  `git reset --hard` 拒绝并给替代方案；write/edit 之后自动跑测试，只回注三行失败摘要
- **reviewer 子 agent**：只读工具 + 五条固定清单，只回最后一条结论
  （实测 `subagent_tokens=329`，主上下文只增加 56）

### 2.6 MCP 工具调用

已实现真实 MCP 客户端（stdio JSON-RPC）：自动启动 `mcp.json` 中配置的 server，
发现其工具并以 `mcp__server__tool` 命名合并进注册表。仓库自带一个最小
MCP server（`workspace_stats` / `note_add`）作为集成示例。

### 2.7 常驻能力（选做增量 C）

- **崩溃续跑**：每一步 turn 落盘 checkpoint（原子写），进程被 `kill -9` 后 `resume` 从断点继续，
  已执行过的工具调用不会重放（`executed_calls` 幂等）
- **定时触发**：`routines.yaml`（`every_seconds` / `at`），到点跑一个 skill
- **事件触发**：轮询目录变化进队列（标准库实现，不引 watchdog）
- **完成通知**：Windows toast + 日志双通道

```bash
python -m app.inspect daemon --out daemon_report.json
```

## 3. 安全机制

1. **工作区路径限制**：所有文件操作校验路径，拒绝越出工作区。
2. **edit 前必须 read**：本会话没读过的文件拒绝修改，杜绝基于臆测的编辑；
   替换目标出现多次时同样拒绝并列出行号，绝不猜测。
3. **bash 超时**：默认 20 秒（上限 120），超时连同进程树一起终止。
4. **循环护栏**：步数上限、token 预算、同一调用连续 3 次判定兜圈子并叫停。
5. **中断**：工具执行与模型调用均可被用户中断。
6. **密钥保护**：API Key 只保存在用户目录（`~/.desktop-tutorial/config.json`），
   任何接口只返回掩码；`.gitignore` 排除 `.env`、`dist` 等敏感内容。
7. **hook 兜底**：即使模型被提示词说动，PreToolUse 也会在代码层拒绝写密钥文件与破坏性命令。
8. **写完就验**：PostToolUse 在每次 write/edit 后自动跑测试，红了只回三行，逼模型面对证据。

## 4. 环境要求

- 操作系统：Windows
- Python：3.12+（开发环境 3.12）
- 桌面界面：pywebview（内置 Edge WebView2）
- 模型接口：DeepSeek OpenAI 兼容接口

## 5. 安装依赖

在项目根目录运行：

```bash
python -m pip install -r requirements.txt
```

## 6. 配置 DeepSeek 模型

两种方式任选：

- **界面配置（推荐）**：启动后点右上角 ⚙ 设置，粘贴 API Key 保存。
- **环境变量**：参考 `.env.example`，设置 `DEEPSEEK_API_KEY`、
  `DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL` 后启动。

**安全提示：不要将 API Key 或 `.env` 上传到 GitHub。** Key 只保存在本地用户目录，任何接口都不会明文回传。

## 7. 启动桌面应用

```bash
python app.py
```

无需界面时也可用命令行运行同一智能体：

```bash
python cli.py --offline "修复 mean 对空列表的处理"
```

## 8. 运行自动化测试

```bash
python -m pytest tests -q
```

共 45 项断言，覆盖文件读写、edit 唯一性检查、bash 超时、循环护栏（步数/预算/兜圈子/中断）、
MCP 协议交互、配置层密钥不泄露及 server 接口行为。每次 push 由 GitHub Actions 自动执行。

## 9. 验收命令（作业：数字必须由程序打印）

```bash
python -m app.inspect skills --out skill_report.json
python -m app.inspect custom --out custom_report.json
python -m app.inspect daemon --out daemon_report.json   # 选做
python -m app.inspect readiness --out readiness_report.json   # 增量 D
python -m app.inspect parallel  --out parallel_report.json    # 增量 E
python -m app.inspect review    --out review_report.json      # 增量 F
```

- `skill_report.json`：技能清单、目录/全文 token、`disclosure_ratio`、8 条触发试验、误触发数
- `custom_report.json`：AGENTS.md 层数与字节、被 hook 拒绝的尝试、自动测试红绿统计、
  reviewer 的问题数与上下文增量
- `daemon_report.json`：定时/事件触发次数、`resume_from_step`（证明不是从第 1 步重来）、
  `notify_fired`、`idempotent` 与 `replayed_tools`
- `readiness_report.json`：九根柱子逐项得分与证据、总分、等级、最该补的三条
- `parallel_report.json`：两个 worktree 分支、各自耗时、冲突文件与解决方式、合并后测试
- `review_report.json`：逐条 bug 是否命中、误报数、召回率、一条汇总评论

### 9.1 常驻演示：kill -9 之后从第 3 步继续

```powershell
# 终端 A：跑一个 5 步的长任务（--slow 只是留出 kill 的窗口）
python -m agent.daemon run --task "修复 mean 对空列表的处理" --run-id demo --slow 0.8 --reset

# 终端 B：等它报完 [step 3] 后直接杀（Windows 的 TerminateProcess，没有清理机会）
Stop-Process -Id <python 的 pid> -Force

# 终端 A：从断点续跑，输出里能看到 resume_from_step
python -m agent.daemon resume --run-id demo
```

实测：杀在 `step=2`、已执行 1 个调用；续跑 `resume_from_step=3`，补完剩下 4 个调用，
5 个调用一个没重放；第二次 `resume` 命中 `done` 直接跳过。

## 10. 能力开关

| 环境变量 | 作用 | 关掉后的现象 |
|---|---|---|
| `ENABLE_SKILLS=0` | 不加载技能 | 工具表少 `use_skill`，system prompt 里没有技能目录 |
| `ENABLE_HOOKS=0` | 不装 hook | 不再拦 `.env`/`rm -rf`，写完也不自动跑测试 |
| `ENABLE_SUBAGENT=0` | 不注册 reviewer | 工具表少 `spawn_reviewer` |

界面上也有「技能 / 钩子」两个勾选框，可以直接对比开关前后的工具调用轮数。

## 11. 打包

```bash
pyinstaller --noconfirm --onefile --windowed --name DesktopAgent ^
  --add-data "ui;ui" --add-data "workspace;workspace" --add-data "mcp.json;." app.py
```

产出 `dist/DesktopAgent.exe`，双击出窗口。详细步骤与踩坑见 [docs/build.md](docs/build.md)。

## 12. 项目目录结构

```text
desktop-tutorial/
├── app.py              # pywebview 桌面应用入口
├── cli.py              # 命令行入口（与桌面共用同一智能体循环）
├── AGENTS.md           # 项目地图（注入 system prompt 的项目层）
├── report.md           # 报告：技能 / 定制 / 取舍
├── agent/              # 循环、四个工具、技能系统、hooks、子 agent、验收命令
│   ├── daemon/         # 常驻：checkpoint 续跑 / routines 定时 / watch 事件 / notify
│   ├── readiness.py    # 增量 D：九根柱子体检、定级（scan/decide_level）
│   ├── parallel.py     # 增量 E：worktree 双工位编排 + 合流
│   ├── parallel_lane.py# 增量 E：工位里干活并自测的脚本
│   └── review.py       # 增量 F：review 子命令、规则评审、召回考核
├── app/                # 验收命令兼容入口（python -m app.inspect）
├── skills/             # 技能目录：run-tests / review-diff / fetch-issue
├── routines.yaml       # 定时触发表（到点跑哪个 skill）
├── server/             # FastAPI 后端（SSE 事件流）
├── ui/                 # 三栏界面（含技能 / 钩子开关）
├── mcp/                # MCP 客户端与示例 server（含 issue 工具）
├── workspace/          # 演示工作区（stats.py 故意留了一个 bug）
├── tests/              # 自动化测试（82 项）
├── docs/               # 运行记录 / 打包说明 / 全局 AGENTS.md / 样例 diff
├── skill_report.json   # 技能验收报告（程序打印）
├── custom_report.json  # 定制层验收报告（程序打印）
├── daemon_report.json  # 常驻验收报告（选做，程序打印）
├── readiness_report.json  # 增量 D：九根柱子体检（程序打印）
├── parallel_report.json   # 增量 E：双工位并行与合流（程序打印）
├── review_report.json     # 增量 F：评审召回/误报考核（程序打印）
├── docs/review/           # 增量 F：PR 语料 + 汇总评论
└── mcp.json            # MCP server 配置
```

## 13. 项目当前状态与后续改进

- **v1.0**：桌面窗口、四工具、MCP、安装包
- **v1.1**：技能系统（渐进披露 + 三种形态 + 触发试验）
- **v1.2**：定制层（AGENTS.md 两层、三个 hook、reviewer 子 agent、界面开关）
- **v1.3**：常驻（checkpoint 续跑 + routines 定时 + 目录事件 + 通知，选做增量 C）
- **v1.4**：可验证（readiness 体检、CI 双闸 ruff+pytest、`[build-system]`，增量 D）
- **v1.5**：并行（worktree 双工位，增量 E）与评审（review 子命令 + 真值语料，增量 F）

未做：多机分布式队列、系统托盘常驻、cron 全语法。当前 `routines.yaml` 只支持
`every_seconds` 与每日 `at` 两种写法 —— 够覆盖「定时跑 skill」的需求，不值得为 cron 引依赖。

## 14. 课程项目说明

本项目用于展示桌面智能体的基础架构设计、模型接口接入、本地工具封装、
MCP 协议集成、工具调用安全控制和自动化测试等内容。

## 15. 第三单元增量：验得动 / 派得出 / 审得住（D / E / F）

三件都是跑得起来的实现，不是要求清单：三份 JSON 在仓库根目录，每个数字都能用一条命令重跑（见 §9）。
**仍是同一个仓库，没有推倒重来。**

### 15.1 增量 D（20 分）：给它一个可验证的仓库

```bash
python -m app.inspect readiness --out readiness_report.json
```

`agent/readiness.py`：

- **九根柱子各一到三项可复现的检查**：先看有没有配置，再真跑一遍，最后看 CI 有没有强制。
  样式与校验（`ruff check`）、构建（`[build-system]` + 整体编译）、测试（真跑 pytest）、文档、
  开发环境、可观测性、安全（真调 hook 拦 `.env` 写入）、任务发现、产品与实验。
- **分数不是估的**：每根柱子的加分项逐条写进 `pillars[].evidence`，例如
  `+40 一条命令跑测试：exit=0、110 passed、51s`。
- **定级看闸，不看平均分**（`decide_level`）：L3 = 总分 ≥ 75 + 一条命令跑测试为真 + CI 强制 lint +
  CI 强制测试；L4 再加「测试 < 120s」与「可观测性 ≥ 75」；闸不过就停在下一级 —— 跳级是最常见的自欺。
- **`top_gaps` 固定三条**：分数最低的三根柱子 + 具体怎么补。

体检的正确用法是「测 → 补 → 再测」。第一次 **76 分 / L1**，短板集中在样式 40、构建/测试/安全 60；
补完再测到 **96 分 / L3**（见 §15.4）。**没补的是可观测性**（结构化日志仍是 0 处）——
报告里它会一直出现在 `top_gaps` 里，不装作有。

### 15.2 增量 E（15 分）：开两个工位跑一次

```bash
python -m app.inspect parallel --out parallel_report.json
```

`agent/parallel.py` 真做的事：

1. `git worktree add -B parallel/task-a .parallel/task-a HEAD`（B 同理）—— 两个目录、两份 index
2. 两个工人 `Popen` **同时**起（不是串行假装并行），各改一件互不相干的事：
   A 加 `agent/slugify.py`、B 加 `agent/chunk.py`，各自带测试；两边都新建了 `CHANGELOG.md`
3. 每个工位先自己跑 `pytest tests -q`，绿了才提交
4. 合流到临时分支 `parallel/integration`：A 干净，B 在 `CHANGELOG.md` 上撞车 ——
   add/add 冲突：同一路径、同一位置、两边都是「新建」，git 没有可自动合并的基准
5. 解决冲突（两条记录互不依赖，按 a→b 都保留）后再跑一遍全量测试
6. 删 worktree、删分支：**主分支不动**，所以这个演示可以反复跑，不会把演示垃圾留进仓库

### 15.3 增量 F（25 分）：让它审自己

```bash
python -m app.inspect review --out review_report.json   # 等价：python cli.py review
```

- 语料 `docs/review/corpus.json`：12 个待审 PR，其中 8 个埋了 10 处已知 bug，4 个干净（用来量误报）
- `agent/review.py` 8 条规则：可变默认参数、裸 `except`、吞异常、`== None`、`open` 没配 `with`、
  除零、`[i + 1]` 越界、f-string 拼 SQL；每条意见给到 `文件:行号 + 为什么`
- 判定口径：文件一致且行号在 ±2 内算命中；**召回 = 命中 / 已知 bug 数**，
  **误报 = 落在真值之外的评论数**（含干净 PR 上的任何评论）
- 「一条汇总评论」落盘到 `docs/review/summary_comment.md`，可直接粘到 PR 上

### 15.4 实测（数字全部来自上面三条命令的输出）

| 交付 | 关键数字 | 及格线 | 结果 |
|---|---|---|---|
| `readiness_report.json` | **96 分 / L3**；一条命令跑测试 exit=0、**110 passed / 71.5s**；九项里八项满分，可观测性 60 | 等级 ≥ L3 且一条命令跑测试为真 | ✅ |
| `parallel_report.json` | A 81.7s、B 68.9s，两条线同时跑墙钟 **83.8s（1.8×）**；冲突文件 `CHANGELOG.md`（add/add）；合并后 **101 passed** | 两个 worktree 都跑通测试、冲突原因写清 | ✅ |
| `review_report.json` | 12 个 PR / **10 个已知 bug 命中 10**（召回 100%）；10 条意见里**误报 0**（精确率 100%） | 召回 ≥ 60%、误报 ≤ 3 | ✅ |

### 15.5 总分构成（100 分 + 10 分加分）

| 项 | 增量 | 分值 |
|---|---|---|
| A 技能 | 渐进披露 / 三形态 / 触发试验 | 35 → **20** |
| B 定制 | AGENTS.md / hook / reviewer | 30 → **15** |
| D 可验证 | readiness 体检 | **20** |
| E 并行 | worktree 双工位 | **15** |
| F 评审 | review 子命令 + 召回率 | **25** |
| C 常驻 | checkpoint 续跑（选做） | +10（加分，不变） |

旧的没有作废，只是让位给了新的三件；三份 JSON 正好对应三讲：验得动、派得出、审得住。
