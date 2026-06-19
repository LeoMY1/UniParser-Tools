from __future__ import annotations

import os
from typing import Any

import click

from cli.core.credentials import read_api_key_from_config
from cli.core.defaults import UNIPARSER_BASE_URL
from cli.core.errors import config_error


def resolve_host() -> str:
    return UNIPARSER_BASE_URL.rstrip("/") + "/"


def resolve_api_key(ctx: click.Context) -> str | None:
    key = (ctx.obj or {}).get("api_key") or os.getenv("UNIPARSER_API_KEY") or read_api_key_from_config()
    return (key or "").strip() or None


def ctx_flag(ctx: click.Context, name: str) -> bool:
    return bool((ctx.obj or {}).get(name))


def make_client(ctx: click.Context):
    from uniparser_tools.api.clients import UniParserClient

    api_key = resolve_api_key(ctx)
    if not api_key:
        return None, config_error("No API key found. Run 'uniparser auth' to configure your API key.")
    try:
        import uniparser_tools  # noqa: F401
    except ImportError:
        return None, config_error(
            'uniparser_tools is not installed. Run: pip install "git+https://github.com/dptech-corp/UniParser-Tools.git"'
        )
    return UniParserClient(host=resolve_host(), api_key=api_key), None


def cli_options(ctx: click.Context) -> dict[str, Any]:
    return ctx.obj or {}
