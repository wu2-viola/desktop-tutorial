# build —— 怎么打的包

一条命令（Windows）：

```bash
pyinstaller --noconfirm --clean --onefile --windowed --name DesktopAgent ^
  --add-data "ui;ui" --add-data "workspace;workspace" --add-data "mcp.json;." app.py
```

产出 `dist/DesktopAgent.exe`（单文件，双击出窗口）。

## 三个坑

### 坑 1：打包后找不到 ui/

`--onefile` 运行时把资源解到临时目录，路径要用 `sys._MEIPASS` 拿，
代码里不能写相对路径 `ui/index.html`。
本项目的处理：`app.py` 里 `ROOT = Path(getattr(sys, "_MEIPASS", ...))`，
`server/app.py` 挂静态目录也基于同一规则推导。

### 坑 2：--windowed 的 exe 没有控制台流

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
