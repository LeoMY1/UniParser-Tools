"""Smoke tests for skills/uniparser-tools CLI scripts (no network)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2] / "skills" / "uniparser-tools"
PARSE_SCRIPT = SKILL_ROOT / "scripts" / "parse_document.py"
FETCH_SCRIPT = SKILL_ROOT / "scripts" / "fetch_by_token.py"


def _env_without_api_key() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k != "UNIPARSER_API_KEY"}


def _run_script(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        env=_env_without_api_key(),
        cwd=SKILL_ROOT,
        check=False,
    )


class TestSkillCliConfigError:
    def test_parse_document_without_api_key(self) -> None:
        result = _run_script(PARSE_SCRIPT, "--file-path", "/tmp/nonexistent.pdf")
        assert result.returncode == 1
        payload = json.loads(result.stderr.strip())
        assert payload["ok"] is False
        assert payload["error"]["code"] == "CONFIG_ERROR"

    def test_fetch_by_token_without_api_key(self) -> None:
        result = _run_script(FETCH_SCRIPT, "--token", "dummy-token")
        assert result.returncode == 1
        payload = json.loads(result.stderr.strip())
        assert payload["ok"] is False
        assert payload["error"]["code"] == "CONFIG_ERROR"
