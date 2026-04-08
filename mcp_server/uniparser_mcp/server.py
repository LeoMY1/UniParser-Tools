"""FastMCP server: UniParser HTTP API tools.

传输层：默认 **stdio**（本地 MCP 子进程）；设为 **streamable-http** 时可作为 HTTP 服务被远程连接。

- ``UNIPARSER_BASE_URL`` / ``UNIPARSER_API_KEY``：从环境读取（建议 ``.cursor/mcp.json`` 的 ``env``）。
- ``UNIPARSER_MCP_TRANSPORT``：``stdio``（默认）、``sse``、``streamable-http``（别名 ``http`` / ``streamable_http``）。
- Streamable HTTP 监听地址：``FASTMCP_HOST``、``FASTMCP_PORT``（默认 ``127.0.0.1:8000``）、路径 ``FASTMCP_STREAMABLE_HTTP_PATH``（默认 ``/mcp``）。

trigger / get-result 默认项见 ``mcp_server/config.yaml``。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from mcp.server.fastmcp import FastMCP

from uniparser_tools.api.clients import UniParserClient
from uniparser_tools.common.constant import FormatFlag


mcp = FastMCP("UniParser")


def _config_yaml_path() -> Path:
    """包内（wheel/sdist）或与源码树中 ``mcp_server/config.yaml`` 同级。"""
    here = Path(__file__).resolve().parent
    for candidate in (here / "config.yaml", here.parent / "config.yaml"):
        if candidate.is_file():
            return candidate
    raise ValueError(
        f"未找到 config.yaml（已尝试: {here / 'config.yaml'}, {here.parent / 'config.yaml'}）"
    )


@lru_cache(maxsize=1)
def _yaml_config() -> dict[str, Any]:
    path = _config_yaml_path()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config.yaml 根节点必须是映射")
    return data


def _cfg_section(key: str) -> dict[str, Any]:
    v = _yaml_config().get(key)
    if not isinstance(v, dict):
        raise ValueError(f"config.yaml 中键 {key!r} 缺失或不是对象")
    return dict(v)


def _get_formatted_kwargs(merged: dict[str, Any]) -> dict[str, Any]:
    fmt = ("textual", "table", "molecule", "chart", "figure", "expression", "equation")
    out: dict[str, Any] = {}
    for k, v in merged.items():
        out[k] = FormatFlag(v) if k in fmt and isinstance(v, str) else v
    return out


def _client() -> UniParserClient:
    base = (os.environ.get("UNIPARSER_BASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get("UNIPARSER_API_KEY") or "").strip()
    if not base:
        raise ValueError(
            "未设置 UNIPARSER_BASE_URL（可在 .cursor/mcp.json 的 env 中配置）"
        )
    if not key:
        raise ValueError("未设置 UNIPARSER_API_KEY（可在 .cursor/mcp.json 的 env 中配置）")
    return UniParserClient(base, key)


def _trigger_error(trig: Any) -> str | None:
    if not isinstance(trig, dict):
        return str(trig)
    if not trig:
        return "{}"
    if trig.get("status") != "success":
        return json.dumps(trig, ensure_ascii=False)
    return None


async def _fetch_content(client: UniParserClient, trig: Any, token_seed: str) -> str:
    err = _trigger_error(trig)
    if err is not None:
        return err
    token = trig.get("token") if isinstance(trig, dict) else None
    if not token:
        token = client.to_token(token_seed)
    body = dict(_cfg_section("default_get_result"))
    body["token"] = token
    res = await asyncio.to_thread(client.get_formatted, **_get_formatted_kwargs(body))
    if res.get("status") == "error":
        return res.get("description", "获取结果失败")
    return res["content"]


@mcp.tool()
async def uniparser_health() -> str:
    """调用 UniParser 服务 ``GET /health``。"""
    try:
        r = await asyncio.to_thread(_client().health)
    except ValueError as e:
        return str(e)
    if r.get("status") == "error":
        return r.get("description", "健康检查失败")
    return r["status"]


@mcp.tool()
async def uniparser_version() -> str:
    """调用 UniParser 服务 ``GET /version``。"""
    try:
        r = await asyncio.to_thread(_client().version)
    except ValueError as e:
        return str(e)
    if r.get("status") == "error":
        return r.get("description", "版本检查失败")
    return r["version"]


@mcp.tool()
async def uniparser_parse_file(file_path: str) -> str:
    """本机 PDF：``trigger-file-async`` → ``get-result``，返回 ``content`` 文本。"""
    try:
        client = _client()
    except ValueError as e:
        return str(e)
    trig = await asyncio.to_thread(
        client.trigger_file,
        file_path,
        token=None,
        **_cfg_section("default_trigger_file"),
    )
    return await _fetch_content(client, trig, file_path)


@mcp.tool()
async def uniparser_parse_url(url: str) -> str:
    """公网 PDF：``trigger-url-async`` → ``get-result``，返回 ``content`` 文本。"""
    try:
        client = _client()
    except ValueError as e:
        return str(e)
    trig = await asyncio.to_thread(
        client.trigger_url,
        url,
        token=None,
        **_cfg_section("default_trigger_url"),
    )
    return await _fetch_content(client, trig, url)


def _resolve_mcp_transport() -> Literal["stdio", "sse", "streamable-http"]:
    raw = (os.environ.get("UNIPARSER_MCP_TRANSPORT") or "stdio").strip().lower()
    if raw in ("http", "streamable-http", "streamable_http"):
        return "streamable-http"
    if raw == "sse":
        return "sse"
    if raw == "stdio":
        return "stdio"
    raise ValueError(
        f"UNIPARSER_MCP_TRANSPORT 无效: {raw!r}，应为 stdio、sse 或 streamable-http"
    )


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    # stdio 传输时 stdout 仅用于 MCP JSON-RPC，调试信息必须写到 stderr
    mcp.run(transport=_resolve_mcp_transport())
