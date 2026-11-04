"""配置层断言：Key 只落用户目录，任何接口都不回传明文。"""
import json

import agent.config as config


def _use_tmp_home(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / ".desktop-tutorial")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / ".desktop-tutorial" / "config.json")


def test_save_load_roundtrip(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    config.save_config(api_key="sk-abcdef1234567890", model="deepseek-chat")
    assert config.get_api_key() == "sk-abcdef1234567890"
    assert config.CONFIG_FILE.exists()


def test_config_file_never_in_cwd(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    config.save_config(api_key="sk-secret-value-12345")
    assert not (tmp_path / "config.json").exists()          # 不落在“当前目录”
    assert "desktop-tutorial" in str(config.CONFIG_FILE)    # 只在用户目录


def test_env_overrides_file(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    config.save_config(api_key="sk-from-file-123456")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-env-654321")
    assert config.get_api_key() == "sk-from-env-654321"
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    assert config.get_api_key() == "sk-from-file-123456"


def test_load_config_never_leaks_plaintext(monkeypatch, tmp_path):
    _use_tmp_home(monkeypatch, tmp_path)
    config.save_config(api_key="sk-super-secret-key-999")
    cfg = config.load_config()
    dumped = json.dumps(cfg)
    assert "sk-super-secret-key-999" not in dumped          # 明文绝不出现在返回值里
    assert cfg["has_key"] is True
    assert "****" in cfg["key_hint"]


def test_mask_short_key(monkeypatch, tmp_path):
    assert config.mask_key("") == ""
    assert config.mask_key("sk-short") == "****"
