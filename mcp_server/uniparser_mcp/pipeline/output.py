"""Persist parse artifacts to disk."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from uniparser_mcp.config import get_output_root


def default_output_dir(source_stem: str) -> Path:
    return (get_output_root() / source_stem).expanduser().resolve()


def resolve_output_dir(
    source_stem: str,
    output_dir: str | None,
    *,
    overwrite: bool,
) -> tuple[Path, str | None]:
    out = Path(output_dir).expanduser().resolve() if output_dir else default_output_dir(source_stem)
    if out.exists() and not overwrite:
        return out, "DIR_EXISTS"
    if out.exists() and overwrite:
        shutil.rmtree(out)
    return out, None


def write_trigger_meta(
    out_dir: Path,
    *,
    token: str,
    input_type: str,
    input_value: str,
    trigger_kwargs: dict | None = None,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    meta_path = out_dir / "trigger_meta.json"
    payload: dict[str, Any] = {
        "token": token,
        "input_type": input_type,
        "input": input_value,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }
    if trigger_kwargs is not None:
        payload["trigger_kwargs"] = trigger_kwargs
    meta_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta_path


def save_stage_error(out_dir: Path, filename: str, payload: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / filename).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def save_parse_results(
    *,
    out_dir: Path,
    source_stem: str,
    pages_tree: dict,
    formatted: dict,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = source_stem or "document"

    pages_tree_path = out_dir / "pages_tree.json"
    pages_tree_path.write_text(
        json.dumps(pages_tree, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    md_path = out_dir / f"{stem}.md"
    content = formatted.get("content", "")
    md_path.write_text(content, encoding="utf-8")

    meta = {k: v for k, v in formatted.items() if k != "content"}
    formatted_meta_path = out_dir / "formatted_meta.json"
    formatted_meta_path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    return {
        "output_dir": str(out_dir),
        "pages_tree_path": str(pages_tree_path),
        "markdown_path": str(md_path),
        "formatted_meta_path": str(formatted_meta_path),
        "content_chars": len(content),
        "content": content,
    }
