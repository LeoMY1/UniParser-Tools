"""Shared pytest fixtures for the UniParser-Tools test suite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent


def _load_test_dotenv() -> None:
    configured_path = os.environ.get("UNIPARSER_DOTENV_PATH")
    dotenv_path = Path(configured_path).expanduser() if configured_path else REPO_ROOT / ".env"
    if dotenv_path.is_file():
        load_dotenv(dotenv_path=dotenv_path, override=False)


_load_test_dotenv()


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def demo_pdf_path(repo_root: Path) -> Path:
    path = repo_root / "demo_file.pdf"
    if not path.is_file():
        pytest.skip(f"demo_file.pdf missing at {path}")
    return path


@pytest.fixture(scope="session")
def demo_img_path() -> Path:
    path = TESTS_DIR / "demo_img.png"
    assert path.is_file(), f"demo_img.png missing at {path}"
    return path


@pytest.fixture(scope="session")
def api_key() -> str | None:
    return os.environ.get("UNIPARSER_TEST_API_KEY") or os.environ.get("UNIPARSER_API_KEY")


@pytest.fixture(scope="session")
def api_host() -> str | None:
    return os.environ.get("UNIPARSER_TEST_HOST") or os.environ.get("UNIPARSER_BASE_URL") or "https://uniparser.dp.tech"


@pytest.fixture(scope="session")
def live_client(api_key: str | None, api_host: str | None):
    """Real UniParserClient, skipped when no API credential is configured."""
    if not api_key or not api_host:
        pytest.skip("Live API tests require UNIPARSER_TEST_API_KEY or UNIPARSER_API_KEY")
    from uniparser_tools.api.clients import UniParserClient

    with UniParserClient(host=api_host, api_key=api_key) as client:
        yield client
