"""Glossary loading, auto-extraction, and prompt injection helpers."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class GlossaryEntry:
    source: str
    target: str


def _norm_lang(value: str | None) -> str:
    return (value or "").strip().lower().replace("-", "_")


def load_glossary_csv(
    path: str | Path,
    *,
    target_lang: str = "zh-CN",
) -> list[GlossaryEntry]:
    """Load glossary CSV with columns source,target[,tgt_lng]."""
    file_path = Path(path).expanduser().resolve()
    if not file_path.is_file():
        raise FileNotFoundError(f"Glossary not found: {file_path}")

    entries: list[GlossaryEntry] = []
    target_norm = _norm_lang(target_lang)
    with file_path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or "source" not in reader.fieldnames or "target" not in reader.fieldnames:
            raise ValueError("Glossary CSV must have source and target columns")
        for row in reader:
            source = (row.get("source") or "").strip()
            target = (row.get("target") or "").strip()
            if not source or not target:
                continue
            tgt_lng = (row.get("tgt_lng") or "").strip()
            if tgt_lng and _norm_lang(tgt_lng) != target_norm:
                continue
            entries.append(GlossaryEntry(source=source, target=target))
    return entries


def merge_glossaries(*groups: list[GlossaryEntry]) -> list[GlossaryEntry]:
    """Merge glossaries; later groups override earlier ones for the same source."""
    merged: dict[str, GlossaryEntry] = {}
    for group in groups:
        for entry in group:
            merged[entry.source] = entry
    # Longer sources first for matching.
    return sorted(merged.values(), key=lambda e: len(e.source), reverse=True)


def hit_glossary_entries(text: str, glossary: list[GlossaryEntry]) -> list[GlossaryEntry]:
    hits: list[GlossaryEntry] = []
    for entry in glossary:
        if entry.source and entry.source in text:
            hits.append(entry)
    return hits


def format_glossary_for_prompt(entries: list[GlossaryEntry]) -> str:
    if not entries:
        return ""
    lines = [f"- {e.source} => {e.target}" for e in entries]
    return "Glossary (must follow when applicable):\n" + "\n".join(lines)


def majority_vote_terms(pairs: list[tuple[str, str]]) -> list[GlossaryEntry]:
    by_src: dict[str, list[str]] = {}
    for src, tgt in pairs:
        src = src.strip()
        tgt = tgt.strip()
        if not src or not tgt:
            continue
        by_src.setdefault(src, []).append(tgt)
    entries: list[GlossaryEntry] = []
    for src, tgts in by_src.items():
        target = Counter(tgts).most_common(1)[0][0]
        entries.append(GlossaryEntry(source=src, target=target))
    return sorted(entries, key=lambda e: len(e.source), reverse=True)


def sample_units_for_term_extraction(units: list[Any], *, limit: int = 40) -> list[Any]:
    """Prefer titles and long paragraphs for term extraction."""
    titles = [u for u in units if u.translate and u.block_type in {"title", "documenttitle"}]
    paras = [u for u in units if u.translate and u.block_type not in {"title", "documenttitle"}]
    paras_sorted = sorted(paras, key=lambda u: len(u.text or ""), reverse=True)
    picked: list[Any] = []
    seen: set[str] = set()
    for u in titles + paras_sorted:
        if u.unit_id in seen:
            continue
        seen.add(u.unit_id)
        picked.append(u)
        if len(picked) >= limit:
            break
    return picked


def extract_glossary_with_llm(
    units: list[Any],
    *,
    chat_fn: Callable[..., str],
    target_lang: str = "zh-CN",
) -> list[GlossaryEntry]:
    sample = sample_units_for_term_extraction(units)
    if not sample:
        return []
    payload = [{"unit_id": u.unit_id, "text": u.text} for u in sample]
    system_prompt = (
        "You extract bilingual glossary terms for scientific PDF translation.\n"
        f"Target language: {target_lang}.\n"
        "Return ONLY a JSON array of objects with keys source and target.\n"
        "Focus on domain terms, model names, dataset names, and recurring technical phrases.\n"
        "Keep proper nouns consistent. Do not include full sentences."
    )
    user_content = json.dumps(payload, ensure_ascii=False, indent=2)
    raw = chat_fn(system_prompt=system_prompt, user_content=user_content)
    items = _extract_term_array(raw)
    pairs = [(str(item.get("source") or ""), str(item.get("target") or "")) for item in items]
    return majority_vote_terms(pairs)


def _extract_term_array(raw: str) -> list[dict[str, Any]]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            return []
        data = json.loads(match.group(0))
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def save_glossary(
    entries: list[GlossaryEntry],
    *,
    json_path: Path,
    csv_path: Path,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [{"source": e.source, "target": e.target} for e in entries]
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["source", "target"])
        writer.writeheader()
        for e in entries:
            writer.writerow({"source": e.source, "target": e.target})
