"""完成通知：Windows 真弹 toast，失败/非 Windows 降级写日志。

返回的 channels 是证据 —— 报告里的 notify_fired 只有在真的走通某个通道时才为 true。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path
from xml.sax.saxutils import escape

from .checkpoint import default_state_dir

TOAST_PS = """[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('<toast><visual><binding template="ToastText02"><text id="1">{title}</text><text id="2">{body}</text></binding></visual></toast>')
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Desktop Agent').Show($toast)
"""


def _toast(title: str, body: str) -> bool:
    if sys.platform != "win32":
        return False
    script = TOAST_PS.format(title=escape(title[:60]), body=escape(body[:180]))
    tmp = Path(tempfile.mkdtemp(prefix="toast-")) / "toast.ps1"
    tmp.write_text(script, encoding="utf-8-sig")
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(tmp)],
            capture_output=True, timeout=15)
        return proc.returncode == 0
    except Exception:
        return False


def notify(title: str, body: str, allow_toast: bool = True,
           log_path: Path | None = None) -> dict:
    channels: list[str] = []
    if allow_toast and _toast(title, body):
        channels.append("windows-toast")
    p = Path(log_path or (default_state_dir() / "notifications.log"))
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {title} | {body}\n")
    channels.append("log")
    return {"ok": bool(channels), "channels": channels, "log": str(p)}
