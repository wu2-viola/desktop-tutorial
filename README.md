# Desktop Agent：桌面智能体课程作业

## 1. 项目简介

Desktop Agent 是一个基于 Python、pywebview 和 DeepSeek 模型接口开发的桌面智能体课程项目，双击即出窗口（有标题栏的桌面应用，不是 localhost 网页）。

项目将大语言模型与本地工具结合，智能体按「决策 → 动作 → 观察 → 再决策」循环工作，工具调用全程可见、可中断。

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

### 2.4 MCP 工具调用

已实现真实 MCP 客户端（stdio JSON-RPC）：自动启动 `mcp.json` 中配置的 server，
发现其工具并以 `mcp__server__tool` 命名合并进注册表。仓库自带一个最小
MCP server（`workspace_stats` / `note_add`）作为集成示例。

## 3. 安全机制

1. **工作区路径限制**：所有文件操作校验路径，拒绝越出工作区。
2. **edit 前必须 read**：本会话没读过的文件拒绝修改，杜绝基于臆测的编辑；
   替换目标出现多次时同样拒绝并列出行号，绝不猜测。
3. **bash 超时**：默认 20 秒（上限 120），超时连同进程树一起终止。
4. **循环护栏**：步数上限、token 预算、同一调用连续 3 次判定兜圈子并叫停。
5. **中断**：工具执行与模型调用均可被用户中断。
6. **密钥保护**：API Key 只保存在用户目录（`~/.desktop-tutorial/config.json`），
   任何接口只返回掩码；`.gitignore` 排除 `.env`、`dist` 等敏感内容。

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

## 9. 打包

```bash
pyinstaller --noconfirm --onefile --windowed --name DesktopAgent ^
  --add-data "ui;ui" --add-data "workspace;workspace" --add-data "mcp.json;." app.py
```

产出 `dist/DesktopAgent.exe`，双击出窗口。详细步骤与踩坑见 [docs/build.md](docs/build.md)。

## 10. 项目目录结构

```text
desktop-tutorial/
├── app.py              # pywebview 桌面应用入口
├── cli.py              # 命令行入口（与桌面共用同一智能体循环）
├── agent/              # 智能体循环、四个工具、配置层、模型适配层
├── server/             # FastAPI 后端（SSE 事件流）
├── ui/                 # 三栏界面
├── mcp/                # MCP 客户端与示例 server
├── workspace/          # 演示工作区（stats.py 故意留了一个 bug）
├── tests/              # 自动化测试（45 项）
├── report.md           # 项目报告（架构 / 打包 / 取舍 / 再加一个工具）
├── docs/               # 运行记录（trace.md / demo-run.md）与打包说明（build.md）
└── mcp.json            # MCP server 配置
```

## 11. 项目当前状态与后续改进

当前版本已实现桌面交互界面、DeepSeek 流式对话、四个受限本地工具、真实 MCP
集成、循环护栏、自动化测试与 Windows 独立安装包。

后续可完善：上下文压缩（长会话 token 增长）、多会话支持、edit 确认弹窗、
更多模型的适配。

## 12. 课程项目说明

本项目用于展示桌面智能体的基础架构设计、模型接口接入、本地工具封装、
MCP 协议集成、工具调用安全控制和自动化测试等内容。
