from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path.home() / ".uniparser"
CONFIG_PATH = CONFIG_DIR / "config.yaml"


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.is_file():
        return {}
    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def read_api_key_from_config() -> str | None:
    key = load_config().get("api_key")
    if key is None:
        return None
    text = str(key).strip()
    return text or None


def save_api_key(api_key: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config = load_config()
    config["api_key"] = api_key.strip()
    CONFIG_PATH.write_text(
        yaml.safe_dump(config, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )


def mask_api_key(api_key: str) -> str:
    text = api_key.strip()
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}...{text[-4:]}"
