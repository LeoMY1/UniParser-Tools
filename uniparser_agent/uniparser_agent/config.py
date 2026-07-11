from __future__ import annotations

import os
from pathlib import Path


DEFAULT_BASE_URL = "https://uniparser.dp.tech"
DEFAULT_DB_PATH = Path.home() / ".uniparser-agent" / "chemistry.db"


def get_api_key() -> str:
    key = (os.environ.get("UNIPARSER_API_KEY") or "").strip()
    if not key:
        raise ValueError("UNIPARSER_API_KEY is not set.")
    return key


def get_base_url() -> str:
    return (os.environ.get("UNIPARSER_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")


def default_db_path() -> Path:
    raw = os.environ.get("UNIPARSER_AGENT_DB")
    if raw:
        return Path(raw).expanduser().resolve()
    return DEFAULT_DB_PATH.resolve()
