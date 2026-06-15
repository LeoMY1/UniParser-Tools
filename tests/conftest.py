"""Shared pytest fixtures for the UniParser-Tools test suite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def demo_pdf_path(repo_root: Path) -> Path:
    path = repo_root / "demo_file.pdf"
    assert path.is_file(), f"demo_file.pdf missing at {path}"
    return path


@pytest.fixture(scope="session")
def demo_img_path() -> Path:
    path = TESTS_DIR / "demo_img.png"
    assert path.is_file(), f"demo_img.png missing at {path}"
    return path


@pytest.fixture(scope="session")
def api_key() -> str | None:
    return os.environ.get("UNIPARSER_TEST_API_KEY")


@pytest.fixture(scope="session")
def api_host() -> str | None:
    return os.environ.get("UNIPARSER_TEST_HOST")


@pytest.fixture(scope="session")
def live_client(api_key: str | None, api_host: str | None):
    """Real UniParserClient, only when API creds are in env. Skip otherwise."""
    if not api_key or not api_host:
        pytest.skip("Live API tests require UNIPARSER_TEST_API_KEY and UNIPARSER_TEST_HOST env vars")
    from uniparser_tools.api.clients import UniParserClient

    return UniParserClient(host=api_host, api_key=api_key)
