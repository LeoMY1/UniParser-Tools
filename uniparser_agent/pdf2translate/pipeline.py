"""End-to-end PDF translation pipeline: UniParser → translate → overlay render."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from uniparser_agent.llm import LLMConfig
from uniparser_agent.output_dir import create_unique_output_dir, resolve_output_dir
from uniparser_agent.parse.service import load_pages_tree, parse_document
from uniparser_agent.pdf2translate.layout_adapter import adapt_pages_tree_file
from uniparser_agent.pdf2translate.prompts import DEFAULT_TARGET_LANG
from uniparser_agent.pdf2translate.renderer import build_page_rect_map, render_translated_pdf
from uniparser_agent.pdf2translate.translator import (
    TranslateLLMClient,
    TranslateStats,
    translate_units,
)


def _resolve_output_dir(output_dir: str | Path | None) -> Path:
    preferred = resolve_output_dir(output_dir, default=Path.cwd() / "translate_out")
    return create_unique_output_dir(preferred)


def _write_units_jsonl(units: list[Any], path: Path) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for unit in units:
            fh.write(json.dumps(unit.to_dict(), ensure_ascii=False, indent=None) + "\n")


def _count_status(units: list[Any]) -> dict[str, int]:
    counts = {
        "total": len(units),
        "translated": 0,
        "skipped": 0,
        "failed": 0,
        "overflow": 0,
        "pending": 0,
    }
    for unit in units:
        key = unit.status if unit.status in counts else "failed"
        counts[key] = counts.get(key, 0) + 1
    return counts


def run_translate_pipeline(
    pdf_path: str,
    *,
    target_lang: str = DEFAULT_TARGET_LANG,
    source_lang: str | None = None,
    pages_tree_path: str | None = None,
    output_dir: str | None = None,
    font: str | None = None,
    debug_layout: bool = False,
    glossary_path: str | None = None,
    auto_glossary: bool = True,
    translator_client: TranslateLLMClient | None = None,
    llm_config: LLMConfig | None = None,
) -> dict[str, Any]:
    """Run PDF in-place visual translation.

    Requires a local PDF. ``pages_tree_path`` skips UniParser parse when provided.
    Target language defaults to ``zh-CN``.
    """
    lang = (target_lang or DEFAULT_TARGET_LANG).strip() or DEFAULT_TARGET_LANG

    src_pdf = Path(pdf_path).expanduser().resolve()
    if not src_pdf.is_file():
        raise FileNotFoundError(f"PDF not found: {src_pdf}")
    if src_pdf.suffix.lower() != ".pdf":
        raise ValueError(f"Input must be a local PDF file, got: {src_pdf}")

    started = time.time()
    cached_tree_bytes: bytes | None = None
    if pages_tree_path:
        tree_src = Path(pages_tree_path).expanduser().resolve()
        if not tree_src.is_file():
            raise FileNotFoundError(f"pages_tree not found: {tree_src}")
        load_pages_tree(tree_src)
        cached_tree_bytes = tree_src.read_bytes()

    out = _resolve_output_dir(output_dir)
    parse_dir = out / "parse"
    parse_meta: dict[str, Any] = {}

    if pages_tree_path:
        assert cached_tree_bytes is not None
        parse_dir.mkdir(parents=True, exist_ok=True)
        dest_tree = parse_dir / "pages_tree.json"
        dest_tree.write_bytes(cached_tree_bytes)
        tree_path = dest_tree
        parse_meta = {"mode": "pages_tree", "pages_tree_path": str(tree_path)}
    else:
        parse_result = parse_document(str(src_pdf), output_dir=str(parse_dir))
        tree_path = Path(parse_result["pages_tree_path"])
        parse_meta = {
            "mode": "parse",
            "source": str(src_pdf),
            "token": parse_result.get("token", ""),
            "pages_tree_path": parse_result["pages_tree_path"],
            "markdown_path": parse_result.get("markdown_path", ""),
        }

    load_pages_tree(tree_path)
    page_rect_map = build_page_rect_map(src_pdf)

    units_path = out / "translate_units.jsonl"
    units = adapt_pages_tree_file(tree_path, units_path, page_rect_map=page_rect_map)

    llm = translator_client or TranslateLLMClient(config=llm_config)
    translate_stats = TranslateStats()
    translate_started = time.time()
    translate_units(
        units,
        target_lang=lang,
        source_lang=source_lang.strip() if source_lang else None,
        client=llm,
        glossary_path=glossary_path,
        auto_glossary=auto_glossary,
        output_dir=out,
        stats_out=translate_stats,
    )
    translate_elapsed = time.time() - translate_started
    _write_units_jsonl(units, units_path)

    translated_pdf = out / "translated.pdf"
    debug_pdf = out / "layout_debug.pdf" if debug_layout else None
    render_started = time.time()
    render_stats = render_translated_pdf(
        src_pdf,
        units,
        translated_pdf,
        fontfile=font if font and Path(font).expanduser().is_file() else None,
        fontname="china-s" if not (font and Path(font).expanduser().is_file()) else "custom",
        debug_layout=debug_layout,
        debug_output_path=debug_pdf,
    )
    # Re-write units after render status updates (overflow/failed_draw).
    _write_units_jsonl(units, units_path)
    render_elapsed = time.time() - render_started

    status_counts = _count_status(units)
    paths = {
        "output_dir": str(out),
        "pages_tree": str(tree_path),
        "translate_units": str(units_path),
        "translated_pdf": str(translated_pdf),
        "source_pdf": str(src_pdf),
    }
    if debug_layout and render_stats.get("debug_layout_path"):
        paths["layout_debug_pdf"] = render_stats["debug_layout_path"]
    paths.update(translate_stats.paths)

    meta: dict[str, Any] = {
        "parse": parse_meta,
        "languages": {
            "target_lang": lang,
            "source_lang": source_lang.strip() if source_lang else None,
        },
        "glossary": {
            "auto_enabled": translate_stats.auto_glossary_enabled,
            "manual_path": glossary_path,
            "manual_entries": translate_stats.glossary_manual,
            "auto_entries": translate_stats.glossary_auto,
            "total_entries": translate_stats.glossary_total,
        },
        "llm": llm.meta(),
        "counts": {
            **status_counts,
            "empty_rejected": translate_stats.empty_rejected,
            "item_retries": translate_stats.item_retries,
            "schema_failures": translate_stats.schema_failures,
        },
        "render": {
            "drawn": render_stats.get("drawn", 0),
            "overflow": render_stats.get("overflow", 0),
            "skipped_draw": render_stats.get("skipped_draw", 0),
            "failed_draw": render_stats.get("failed_draw", 0),
            "pages": render_stats.get("pages", 0),
        },
        "timing": {
            "translate_elapsed_sec": round(translate_elapsed, 2),
            "render_elapsed_sec": round(render_elapsed, 2),
            "total_elapsed_sec": round(time.time() - started, 2),
        },
        "paths": paths,
    }
    meta_path = out / "run_meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    meta["paths"]["run_meta"] = str(meta_path)
    return meta
