# build —— 怎么打的包

两种打法的取舍：

| 方式 | 启动耗时 | 交付形态 | 适用 |
|---|---|---|---|
| `--onefile` | **20–30 秒**（每次都要解 7000+ 个文件） | 单个 exe | 发下载链接 |
| `--onedir` | 2–4 秒 | 一个文件夹（exe + `_internal/`） | 现场演示、日常使用 |

```bash
# 单文件（发布用）
pyinstaller --noconfirm --clean --onefile --windowed --name DesktopAgent ^
  --add-data "ui;ui" --add-data "workspace;workspace" --add-data "mcp.json;." ^
  --add-data "skills;skills" --add-data "AGENTS.md;." --add-data "docs;docs" app.py

# 免解包（演示用，启动快）
pyinstaller --noconfirm --clean --onedir --windowed --name DesktopAgent ^
  --add-data "ui;ui" --add-data "workspace;workspace" --add-data "mcp.json;." ^
  --add-data "skills;skills" --add-data "AGENTS.md;." --add-data "docs;docs" ^
  --exclude-module matplotlib --exclude-module IPython --exclude-module jedi ^
  --exclude-module parso --exclude-module pandas app.py
```

`--onefile` 每次双击都要先把 74MB 解到 `%TEMP%\_MEIxxxxxx`，杀软再逐个扫一遍，
界面上表现为「双击没反应」——它其实在解包，25 秒后才出窗口。演示请用 `--onedir`。

## 三个坑

### 坑 1：打包后找不到 ui/

`--onefile` 运行时把资源解到临时目录，路径要用 `sys._MEIPASS` 拿，
代码里不能写相对路径 `ui/index.html`。
本项目的处理：`app.py` 里 `ROOT = Path(getattr(sys, "_MEIPASS", ...))`，
`server/app.py` 挂静态目录也基于同一规则推导。

### 坑 2：--windowed 的 exe 没有控制台流

第一个受害者是 uvicorn 自己的日志：`uvicorn/logging.py` 的 `DefaultFormatter`
会调 `sys.stderr.isatty()`，而 `--windowed` 下 `sys.stderr` 是 `None`，
启动即 `AttributeError: 'NoneType' object has no attribute 'isatty'` ——
窗口还没出来就变成一个 "Unhandled exception in script" 对话框，看起来像「双击没反应」。

解决：`app.py:_ensure_streams()` 先把 `None` 换成 `os.devnull`，
再给 `uvicorn.Config` 传 `log_config=None`，绕开 `logging.dictConfig`。
另外 `_run()` 会把未捕获异常写进 `~/.desktop-tutorial/crash.log`，
以后远程排障不用再靠猜。

内置 MCP demo server 在打包后以 `DesktopAgent.exe --mcp-server` 模式运行，
但 `--windowed` 会让 `sys.stdout` 变成 NullWriter —— 协议应答直接消失，MCP 超时。
解决：用 `GetStdHandle` + `msvcrt.open_osfhandle` 把 stdio 重新接到父进程给的管道句柄上
（见 `app.py:_run_as_mcp_server`）。

### 坑 3：可写目录

解包目录是只读的，`workspace/` 演示文件首次运行时拷到
`Path.home()/.desktop-tutorial/workspace`（见 `app.py:_prepare_workspace`）。
规则：资源读 `sys._MEIPASS`，写入一律 `Path.home()`。

## 验证

打包后必做三件事：

1. 双击 exe，出窗口（不是控制台一闪而过）
2. `DesktopAgent.exe --mcp-server` 管道下能应答 `tools/list`（MCP 在包里也是活的）
3. 跑一次离线任务，read → edit → bash 三张卡片都出现
