import os
import stat

from backend.app.settings import Settings, load_settings, masked_key, save_api_key


def test_load_env_override(tmp_path, monkeypatch):
    # no config file anywhere; key must come from the env var
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key-123")
    s = load_settings(config_path=tmp_path / "nope.toml", data_dir=tmp_path / "d")
    assert s.api_key == "env-key-123"
    assert s.data_dir == tmp_path / "d"


def test_save_and_load(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cfg = tmp_path / "paperskim.toml"
    save_api_key("sk-or-v1-abcdef0123456789", config_path=cfg)
    assert cfg.exists()
    mode = stat.S_IMODE(cfg.stat().st_mode)
    assert mode & 0o077 == 0  # no group/other perms
    s = load_settings(config_path=cfg, data_dir=tmp_path / "d")
    assert s.api_key == "sk-or-v1-abcdef0123456789"


def test_masked():
    s = Settings(api_key="abcdwxyz9012", data_dir=None, config_path=None)
    m = masked_key(s)
    assert m == "abcd****9012"
    assert s.api_key not in m
    short = Settings(api_key="tiny", data_dir=None, config_path=None)
    assert masked_key(short) == ""
    empty = Settings(api_key="", data_dir=None, config_path=None)
    assert masked_key(empty) == ""
