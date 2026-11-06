"""Settings: API key + paths. Config file (chmod 600) with env override + live key checks."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

import httpx

ENV_VAR = "OPENROUTER_API_KEY"

DEFAULT_CONFIG_PATH = Path("backend/paperskim.toml")
DEFAULT_DATA_DIR = Path("backend/data")

KEY_CHECK_URL = "https://openrouter.ai/api/v1/key"


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


def validate_key(api_key: str, client: httpx.Client | None = None) -> dict:
    """Live-check an OpenRouter key.

    Returns {"status": "valid"|"expired"|"invalid"|"error", "message": str}.
    "error" means we could not determine validity (network) — callers may
    choose to save anyway.
    """
    if not api_key or not api_key.strip():
        return {"status": "invalid", "message": "API key is empty"}
    own = client is None
    c = client if client is not None else httpx.Client(timeout=15)
    try:
        r = c.get(KEY_CHECK_URL, headers={"Authorization": f"Bearer {api_key}"})
        if r.status_code == 200:
            label = ""
            try:
                label = str((r.json().get("data") or {}).get("label") or "")
            except ValueError:
                pass
            msg = "key is valid" + (f" ({label})" if label else "")
            return {"status": "valid", "message": msg}
        detail = ""
        try:
            detail = str((r.json().get("error") or {}).get("message") or "")
        except ValueError:
            pass
        if r.status_code == 401:
            if "expired" in detail.lower():
                return {
                    "status": "expired",
                    "message": "API key expired — create a new one at "
                    "openrouter.ai/keys and paste it here.",
                }
            return {
                "status": "invalid",
                "message": f"OpenRouter rejected this key ({detail or '401 Unauthorized'}).",
            }
        return {
            "status": "error",
            "message": f"could not verify key (HTTP {r.status_code}) {detail}".strip(),
        }
    except httpx.HTTPError as e:
        return {"status": "error", "message": f"could not reach OpenRouter: {e}"}
    finally:
        if own:
            c.close()
