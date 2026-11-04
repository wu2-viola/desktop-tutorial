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


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    import uvicorn
    from server.app import app as fastapi_app, init

    init(ROOT / "workspace", ROOT / "mcp.json")
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
