"""Structured MCP errors."""

from __future__ import annotations

from pathlib import Path

from uniparser_mcp.schemas import ErrorDetail, ErrorResult


def config_error(message: str) -> ErrorResult:
    return ErrorResult(error=ErrorDetail(code="CONFIG_ERROR", message=message))


def input_error(message: str) -> ErrorResult:
    return ErrorResult(error=ErrorDetail(code="INPUT_ERROR", message=message))


def dir_exists_error(output_dir: Path) -> ErrorResult:
    return ErrorResult(
        error=ErrorDetail(
            code="DIR_EXISTS",
            message=(f"Output directory already exists: {output_dir}. Re-run with overwrite=true to replace it."),
            output_dir=str(output_dir),
        )
    )


def parse_error(stage: str, result: dict) -> ErrorResult:
    return ErrorResult(
        error=ErrorDetail(
            code="PARSE_ERROR",
            message=result.get("description") or result.get("message") or str(result),
            stage=stage,
            token=result.get("token"),
        )
    )
