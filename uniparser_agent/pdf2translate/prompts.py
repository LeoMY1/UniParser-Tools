"""Prompt builders for PDF block translation."""

from __future__ import annotations

import json
from typing import Any

from uniparser_agent.pdf2translate.glossary import GlossaryEntry, format_glossary_for_prompt


DEFAULT_TARGET_LANG = "zh-CN"


def build_translate_system_prompt(
    *,
    target_lang: str = DEFAULT_TARGET_LANG,
    source_lang: str | None = None,
    glossary_entries: list[GlossaryEntry] | None = None,
) -> str:
    src = source_lang.strip() if source_lang else "auto-detected source language"
    glossary_block = format_glossary_for_prompt(glossary_entries or [])
    parts = [
        "You are a professional document translator.\n"
        f"Translate each text unit into {target_lang}. Source language: {src}.\n"
        "Rules:\n"
        "1. Preserve meaning, tone, and technical terminology.\n"
        "2. Keep placeholders like <<EQ0>>, <<EQ1>> exactly unchanged (character-for-character).\n"
        "3. Do not translate or alter LaTeX, code, or placeholder tokens.\n"
        "4. Return ONLY a JSON array of objects with keys unit_id and translated_text.\n"
        "5. Include every input unit_id exactly once.\n"
        "6. Keep translations concise enough for the original layout when possible.\n"
        "7. Only translate the `text` field. `context_title` and `context_prev` are read-only "
        "hints for deixis and section continuity; never copy them into translated_text.\n"
        "8. translated_text must be a non-empty string for every unit.\n"
    ]
    if glossary_block:
        parts.append(glossary_block + "\n")
    return "".join(parts)


def build_translate_user_content(units: list[dict[str, str]]) -> str:
    return json.dumps(units, ensure_ascii=False, indent=2)


def build_context_fields(units: list[Any]) -> dict[str, dict[str, str]]:
    """Return unit_id -> {context_title?, context_prev?} for translatable units.

    Units are processed in reading order ``(page, order)``.
    """
    title_types = {"title", "documenttitle"}
    last_title: str | None = None
    last_prev_text: str | None = None
    out: dict[str, dict[str, str]] = {}

    ordered = sorted(units, key=lambda u: (u.page, u.order, u.unit_id))
    for unit in ordered:
        if unit.block_type in title_types and (unit.text or "").strip():
            last_title = unit.text.strip()

        if not unit.translate:
            continue

        ctx: dict[str, str] = {}
        if last_title:
            ctx["context_title"] = last_title
        if last_prev_text:
            ctx["context_prev"] = last_prev_text
        if ctx:
            out[unit.unit_id] = ctx

        if (unit.text or "").strip():
            last_prev_text = unit.text.strip()

    return out
