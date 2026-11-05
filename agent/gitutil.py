"""找 git：PATH 里没有时，退回常见安装位置（GitHub Desktop 自带的那份也算）。

Windows 上很常见：git 装过但没进 PATH。功能不该因此静默失败，
找不到就返回 None，由调用方给出「装 git 或设 GIT 环境变量」的明确提示。
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path


def find_git() -> str | None:
    env = os.environ.get("GIT")
    if env and Path(env).exists():
        return env
    found = shutil.which("git")
    if found:
        return found

    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "cmd" / "git.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Git" / "cmd" / "git.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Git" / "cmd" / "git.exe",
        Path(r"D:\Git\cmd\git.exe"),
    ]
    for c in candidates:
        if c.is_file():
            return str(c)

    desktop = Path(os.environ.get("LOCALAPPDATA", "")) / "GitHubDesktop"
    if desktop.is_dir():
        for p in sorted(desktop.glob("app-*/resources/app/git/cmd/git.exe"), reverse=True):
            return str(p)
    return None
