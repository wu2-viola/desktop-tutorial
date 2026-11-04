"""配置层：API Key 只落用户目录，任何接口都不回传明文。

为什么不放仓库：.env 进了公开仓库就等于泄露 —— 删掉也没用，git 历史还在。
所以 Key 的唯一归宿是 Path.home()/.desktop-tutorial/config.json（不进任何 git）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".desktop-tutorial"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-chat",
}


def _read_file() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_config() -> dict:
    """合并优先级：环境变量 > 用户目录配置 > 默认值。返回值不含明文 Key。"""
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in _read_file().items() if k != "api_key"})
    cfg["base_url"] = os.environ.get("DEEPSEEK_BASE_URL", cfg["base_url"])
    cfg["model"] = os.environ.get("DEEPSEEK_MODEL", cfg["model"])
    cfg["has_key"] = bool(get_api_key())
    cfg["key_hint"] = mask_key(get_api_key())
    cfg.pop("api_key", None)
    return cfg


def get_api_key() -> str:
    """取 Key：环境变量优先，其次用户目录配置文件。"""
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    return str(_read_file().get("api_key", "") or "").strip()


def save_config(*, api_key: str | None = None, base_url: str | None = None,
                model: str | None = None) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = _read_file()
    if api_key is not None and api_key.strip():
        data["api_key"] = api_key.strip()
    if base_url:
        data["base_url"] = base_url.strip()
    if model:
        data["model"] = model.strip()
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    try:  # 用户目录之外的人不该读这个文件
        CONFIG_FILE.chmod(0o600)
    except OSError:
        pass


def mask_key(key: str) -> str:
    if not key:
        return ""
    return f"{key[:6]}****{key[-4:]}" if len(key) > 12 else "****"
