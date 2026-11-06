"""Settings: API key + paths. Config file (chmod 600) with env override."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

ENV_VAR = "OPENROUTER_API_KEY"

DEFAULT_CONFIG_PATH = Path("backend/paperskim.toml")
DEFAULT_DATA_DIR = Path("backend/data")


@dataclass
class Settings:
    api_key: str = ""
    data_dir: Path = DEFAULT_DATA_DIR
    config_path: Path = DEFAULT_CONFIG_PATH


def load_settings(
    config_path: Path | None = None, data_dir: Path | None = None
) -> Settings:
    cfg = config_path if config_path is not None else DEFAULT_CONFIG_PATH
    api_key = ""
    if cfg.is_file():
        with open(cfg, "rb") as f:
            data = tomllib.load(f)
        api_key = str(data.get("openrouter", {}).get("api_key", ""))
    env_key = os.environ.get(ENV_VAR, "")
    if env_key:
        api_key = env_key
    return Settings(
        api_key=api_key,
        data_dir=data_dir if data_dir is not None else DEFAULT_DATA_DIR,
        config_path=cfg,
    )


def save_api_key(key: str, config_path: Path | None = None) -> None:
    cfg = config_path if config_path is not None else DEFAULT_CONFIG_PATH
    cfg.parent.mkdir(parents=True, exist_ok=True)
    escaped = key.replace("\\", "\\\\").replace('"', '\\"')
    cfg.write_text(f'[openrouter]\napi_key = "{escaped}"\n', encoding="utf-8")
    cfg.chmod(0o600)


def masked_key(s: Settings) -> str:
    key = s.api_key
    if len(key) <= 8:
        return ""
    return f"{key[:4]}****{key[-4:]}"
