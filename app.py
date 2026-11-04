"""pywebview 桌面入口：双击出窗口，有标题栏 —— 不是 localhost 网页。

打包后找不到 ui/ 是正常现象：资源用 sys._MEIPASS 定位；可写目录一律 Path.home()。
"""
from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if getattr(sys, "frozen", False):          # PyInstaller 解包目录
    ROOT = Path(getattr(sys, "_MEIPASS", ROOT))

sys.path.insert(0, str(ROOT))


def _run_as_mcp_server() -> None:
    """打包模式下内置 MCP server 的入口：DesktopAgent.exe --mcp-server。

    --windowed 的 exe 没有控制台流，但父进程给了管道句柄 —— 把 stdio
    重新接到这些句柄上，协议照常按行收发。
    """
    import ctypes
    import io
    import msvcrt

    def _reopen(std_no: int, mode: str):
        handle = ctypes.windll.kernel32.GetStdHandle(-10 if mode == "r" else -11)
        if handle and handle != -1:
            fd = msvcrt.open_osfhandle(handle, 0)
            return io.TextIOWrapper(io.FileIO(fd, mode), encoding="utf-8")
        return sys.stdin if mode == "r" else sys.stdout

    try:
        sys.stdin = _reopen(0, "r")
        sys.stdout = _reopen(0, "w")
    except Exception:
        pass
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    from mcp.demo_server import main as server_main
    server_main()
    sys.exit(0)


if "--mcp-server" in sys.argv:
    _run_as_mcp_server()


def _prepare_workspace() -> Path:
    """工作区放用户目录（可写）；首次运行把演示文件拷过去。"""
    import shutil
    home_ws = Path.home() / ".desktop-tutorial" / "workspace"
    home_ws.mkdir(parents=True, exist_ok=True)
    src = ROOT / "workspace"
    if src.exists():
        for f in src.iterdir():
            if f.is_file() and not (home_ws / f.name).exists():
                shutil.copy(f, home_ws / f.name)
    return home_ws


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    import uvicorn
    from server.app import app as fastapi_app, init

    init(_prepare_workspace(), ROOT / "mcp.json")
    port = _free_port()
    config = uvicorn.Config(fastapi_app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()

    deadline = time.time() + 15
    import urllib.request
    while time.time() < deadline:            # 等后端就绪再开窗口
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1)
            break
        except Exception:
            time.sleep(0.2)

    import webview
    webview.create_window("Desktop Agent — 桌面智能体",
                          f"http://127.0.0.1:{port}/", width=1280, height=800)
    webview.start()


if __name__ == "__main__":
    main()
