"""Chemistry library configuration."""

from __future__ import annotations

import os
from pathlib import Path


DEFAULT_DB_PATH = Path.home() / ".uniparser-agent" / "chemistry.db"


def default_db_path() -> Path:
    raw = os.environ.get("UNIPARSER_AGENT_DB")
    if raw:
        return Path(raw).expanduser().resolve()
    return DEFAULT_DB_PATH.resolve()
