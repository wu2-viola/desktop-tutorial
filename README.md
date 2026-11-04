# Desktop Agent — 桌面智能体

一个双击出窗口的桌面智能体：接 DeepSeek，带 read / write / edit / bash 四个工具，
能挂 MCP server，工具调用全程可见、可中断。课程大作业「做一个你自己的 Cursor」。

![三栏界面截图占位：运行后补](docs/img/ui.png)

## 三步启动（安装包版，推荐）

1. 到 [Releases](../../releases) 下载 `DesktopAgent.exe`
2. 双击 —— 出窗口（有标题栏，不是 localhost 网页）
3. 右上 ⚙ 设置 → 粘贴 DeepSeek API Key → 保存（Key 存在用户目录，不入仓库）

## 三步启动（源码版）

```bash
git clone https://github.com/wu2-viola/desktop-tutorial.git
cd desktop-tutorial
pip install -r requirements.txt
python app.py        # 出桌面窗口；或 python cli.py --offline "任务" 看终端事件流
```

没配 Key 也能跑：自动切到离线 mock，走完整的 决策→动作→观察→再决策 循环。

## 它能干什么

在右侧输入「mean 对空列表处理有问题，改掉」，你会看到：

- 左栏浏览 `workspace/`，中栏看文件（带行号）
- 右栏工具卡片一条条摊开：read → edit（diff 绿加红减）→ bash 跑测试
- 失败标红（edit 不唯一时会被拒绝并列出行号），随时点 ■ 停止
- MCP 工具带紫色徽章，一眼分清它来自哪个 server

## 目录结构

```
desktop-tutorial/
├── README.md          本文件
├── .gitignore         .env / dist / __pycache__ 进不来
├── .env.example       只有 key 的名字，没有值
├── mcp.json           MCP server 配置（路径不写死）
├── pyproject.toml     版本钉死
├── agent/             循环 + 四个工具 + 配置层 + 模型适配层
├── server/            FastAPI：/api/tree /api/file /api/run/stream(SSE)
├── ui/                三栏界面（index.html / app.js / style.css）
├── mcp/               stdio JSON-RPC 客户端 + 最小 demo server
├── workspace/         演示工作区（stats.py 故意留了 bug）
├── tests/             45 条断言
└── docs/              trace.md / build.md / report.md
```

## 截图

| 三栏界面 | 工具调用与 diff | 失败与中断 |
|---|---|---|
| ![screenshot-1](docs/img/ui.png) | ![screenshot-2](docs/img/diff.png) | ![screenshot-3](docs/img/fail.png) |

> 截图在演示录制时补齐（Win+Shift+S），放到 `docs/img/` 即可。

## 更多

- [docs/trace.md](docs/trace.md) —— 一次完整运行记录（含失败与恢复）
- [docs/build.md](docs/build.md) —— 怎么打的包，三个坑
- [docs/report.md](docs/report.md) —— 架构 / 打包 / 取舍 / 再加一个工具
