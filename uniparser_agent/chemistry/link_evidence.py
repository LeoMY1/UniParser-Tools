"""Phase 2a: LLM-link text units to molecules and fill local_context."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from uniparser_agent.chemistry.join import LogicalCompound
from uniparser_agent.chemistry.patent_chunks import (
    PatentChunk,
    build_patent_chunks,
    pack_patent_chunks,
)
from uniparser_agent.chemistry.prompts import (
    LINK_BATCH_CHAR_BUDGET,
    LOCAL_CONTEXT_MAX_CHARS,
    build_link_prompt,
)
from uniparser_agent.chemistry.text_units import TextUnit, build_text_units


ChatFn = Callable[[str, str], str]


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def parse_link_response(raw: str) -> list[dict[str, Any]]:
    data = json.loads(_strip_fences(raw))
    if isinstance(data, dict) and "links" in data:
        items = data["links"]
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError("LLM link response must be a list or {links: [...]}")
    if not isinstance(items, list):
        raise ValueError("links must be a list")
    return [x for x in items if isinstance(x, dict)]


_FACT_RE = re.compile(
    r"(?:收率|产率|yield|熔点|mp\b|℃|°C|反应|小时|分钟|IC\s*50|EC\s*50|"
    r"抑制率|聚集率|活力|viability|synergy|assay)",
    re.IGNORECASE,
)
_ACTIVITY_RE = re.compile(
    r"(?:IC\s*50|EC\s*50|Ki\b|Kd\b|抑制率|聚集率|活力|viability|synergy)",
    re.IGNORECASE,
)
_SPECTRAL_RE = re.compile(r"\b(?:[13]H|13C)?\s*NMR\b|HRMS|ESI|核磁|质谱", re.IGNORECASE)


def compress_spectral_unit(text: str) -> str:
    """Compress peaks inside one unit without consuming following units."""
    match = _SPECTRAL_RE.search(text)
    if not match or len(text) - match.start() < 80:
        return text
    prefix = text[: match.start()].rstrip()
    spectral_type = match.group(0)
    mass = re.search(
        r"(?:HRMS|高分辨[^:：]{0,12})[^。;\n]{0,260}"
        r"(?:calcd|calculated|理论值)[^。;\n]{0,160}"
        r"(?:found|实测值)[^。;\n]{0,80}",
        text,
        re.IGNORECASE,
    )
    pieces = [prefix] if prefix else []
    pieces.append(f"{spectral_type} [spectral peaks omitted]")
    if mass:
        pieces.append(mass.group(0).strip())
    return "\n".join(piece for piece in pieces if piece)


def _evidence_priority(unit: TextUnit, relation: str) -> tuple[int, int]:
    text = unit.text
    if relation == "activity" or unit.type == "table" or _ACTIVITY_RE.search(text):
        return (0, unit.order)
    if _FACT_RE.search(text):
        return (1, unit.order)
    if unit.type in {"molecule", "moleculegroup", "moleculeid", "title"}:
        return (2, unit.order)
    if _SPECTRAL_RE.search(text):
        return (4, unit.order)
    return (3, unit.order)


def _include_referenced_chunks(
    batch: list[PatentChunk],
    by_id: dict[str, PatentChunk],
) -> list[PatentChunk]:
    out = list(batch)
    included = {chunk.chunk_id for chunk in out}
    for chunk in list(batch):
        for reference in chunk.references:
            target = by_id.get(reference)
            if target and target.chunk_id not in included:
                out.append(target)
                included.add(target.chunk_id)
    return out


def _resolve_compound_key(mid: str, by_id: dict[str, LogicalCompound]) -> str | None:
    if mid in by_id:
        return mid
    for c in by_id.values():
        if c.label == mid or c.compound_id == mid:
            return c.compound_id
    return None


def merge_links(
    compounds: list[LogicalCompound],
    units: list[TextUnit],
    link_items: list[dict[str, Any]],
    *,
    max_chars: int = LOCAL_CONTEXT_MAX_CHARS,
) -> None:
    """Fill ``local_context`` and ``enrich_json.evidence_unit_ids`` from LLM links."""
    by_unit = {u.unit_id: u for u in units}
    by_id = {c.compound_id: c for c in compounds}
    # molecule_id -> ordered unique (unit_id, relation)
    linked: dict[str, list[tuple[str, str]]] = {c.compound_id: [] for c in compounds}
    seen_pair: set[tuple[str, str]] = set()

    for item in link_items:
        unit_id = str(item.get("unit_id") or "").strip()
        if not unit_id or unit_id not in by_unit:
            continue
        mol_ids = item.get("molecule_ids") or item.get("molecules") or []
        if not isinstance(mol_ids, list):
            continue
        relation = str(item.get("relation") or "other").strip()
        for mid in mol_ids:
            key = _resolve_compound_key(str(mid).strip(), by_id)
            if not key:
                continue
            pair = (key, unit_id)
            if pair in seen_pair:
                continue
            seen_pair.add(pair)
            linked[key].append((unit_id, relation))

    for c in compounds:
        linked_items = linked.get(c.compound_id, [])
        candidates = sorted(
            ((by_unit[uid], relation) for uid, relation in linked_items if uid in by_unit),
            key=lambda item: _evidence_priority(item[0], item[1]),
        )
        linked_ids = [uid for uid, _relation in linked_items]
        kept_ids: list[str] = []
        kept: list[tuple[TextUnit, str]] = []
        dropped: list[dict[str, str]] = []
        total = 0
        for unit, _relation in candidates:
            piece = compress_spectral_unit(unit.text)
            add = len(piece) + (1 if kept else 0)
            if total + add > max_chars:
                dropped.append({"unit_id": unit.unit_id, "reason": "context_budget"})
                continue
            kept.append((unit, piece))
            kept_ids.append(unit.unit_id)
            total += add
        kept.sort(key=lambda item: item[0].order)
        c.local_context = "\n".join(piece for _unit, piece in kept)
        prev = dict(c.enrich_json or {})
        prev["linked_unit_ids"] = linked_ids
        prev["evidence_unit_ids"] = kept_ids
        prev["dropped_unit_ids"] = dropped
        c.enrich_json = prev


def attach_evidence_via_llm(
    doc_id: str,
    compounds: list[LogicalCompound],
    pages_tree_doc: dict[str, Any],
    *,
    chat_fn: ChatFn,
) -> list[LogicalCompound]:
    """Build text units, LLM-link them to molecules, fill local_context."""
    if not compounds:
        return compounds

    units = build_text_units(pages_tree_doc)
    if not units:
        for c in compounds:
            c.local_context = ""
            prev = dict(c.enrich_json or {})
            prev["evidence_unit_ids"] = []
            prev["link_status"] = "no_text_units"
            c.enrich_json = prev
        return compounds

    chunks = build_patent_chunks(units)
    chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    batches = pack_patent_chunks(chunks, max_chars=LINK_BATCH_CHAR_BUDGET)
    all_links: list[dict[str, Any]] = []
    for batch in batches:
        linked_batch = _include_referenced_chunks(batch, chunk_by_id)
        system_prompt, user_content = build_link_prompt(doc_id, compounds, linked_batch)
        raw = ""
        last_err = ""
        items: list[dict[str, Any]] = []
        for _attempt in range(2):
            try:
                raw = chat_fn(system_prompt, user_content)
                items = parse_link_response(raw)
                break
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
                items = []
        if not items and last_err:
            # Leave this batch unlinked; continue other batches
            continue
        for item in items:
            mol_ids = item.get("molecule_ids") or []
            if isinstance(mol_ids, list):
                cleaned = [str(m).strip() for m in mol_ids if str(m).strip()]
                item = {**item, "molecule_ids": cleaned}
            all_links.append(item)

    merge_links(compounds, units, all_links)
    for c in compounds:
        prev = dict(c.enrich_json or {})
        prev.setdefault("evidence_unit_ids", [])
        prev["link_status"] = "ok" if prev.get("evidence_unit_ids") else "unlinked"
        c.enrich_json = prev
    return compounds
