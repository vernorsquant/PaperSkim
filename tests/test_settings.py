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
    assert s.queue_workers == 2  # default


def test_load_queue_workers(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cfg = tmp_path / "paperskim.toml"
    cfg.write_text('[openrouter]\napi_key = "k"\n\n[queue]\nworkers = 4\n')
    s = load_settings(config_path=cfg, data_dir=tmp_path / "d")
    assert s.queue_workers == 4
    # invalid values fall back to the default of 2
    cfg.write_text('[openrouter]\napi_key = "k"\n\n[queue]\nworkers = 0\n')
    assert load_settings(config_path=cfg).queue_workers == 2
    cfg.write_text('[openrouter]\napi_key = "k"\n\n[queue]\nworkers = "lots"\n')
    assert load_settings(config_path=cfg).queue_workers == 2


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


import httpx
import pytest
import respx

from backend.app.settings import validate_key

KEY_URL = "https://openrouter.ai/api/v1/key"


@respx.mock
def test_validate_key_valid():
    respx.get(KEY_URL).respond(200, json={"data": {"label": "my key"}})
    out = validate_key("good-key", client=httpx.Client())
    assert out["status"] == "valid"
    assert "my key" in out["message"]


@respx.mock
def test_validate_key_expired():
    respx.get(KEY_URL).respond(401, json={"error": {"message": "API key expired."}})
    out = validate_key("old-key", client=httpx.Client())
    assert out["status"] == "expired"
    assert "openrouter.ai/keys" in out["message"]


@respx.mock
def test_validate_key_invalid():
    respx.get(KEY_URL).respond(401, json={"error": {"message": "Invalid token"}})
    out = validate_key("bad-key", client=httpx.Client())
    assert out["status"] == "invalid"


@respx.mock
def test_validate_key_network_error_is_soft():
    respx.get(KEY_URL).mock(side_effect=httpx.ConnectError("no dns"))
    out = validate_key("some-key", client=httpx.Client())
    assert out["status"] == "error"


def test_validate_key_empty():
    assert validate_key("")["status"] == "invalid"
