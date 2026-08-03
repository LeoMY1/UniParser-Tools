"""Group atomic text units by patent structure before LLM linking."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from uniparser_agent.chemistry.text_units import TextUnit


@dataclass
class PatentChunk:
    chunk_id: str
    section_type: str
    section_title: str = ""
    example_no: str = ""
    claim_no: str = ""
    page_start: int = 0
    page_end: int = 0
    unit_ids: list[str] = field(default_factory=list)
    units: list[TextUnit] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    parent_chunk_id: str = ""
    part: int = 0

    @property
    def char_count(self) -> int:
        return sum(len(unit.text) + 64 for unit in self.units)

    def append(self, unit: TextUnit) -> None:
        self.units.append(unit)
        self.unit_ids.append(unit.unit_id)
        if not self.page_start:
            self.page_start = unit.page
        self.page_end = max(self.page_end, unit.page)
        for ref in _example_references(unit.text):
            if ref not in self.references:
                self.references.append(ref)


_SECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("technical_field", re.compile(r"^(?:#+\s*)?技术领域\s*$")),
    ("background", re.compile(r"^(?:#+\s*)?背景技术\s*$")),
    ("invention", re.compile(r"^(?:#+\s*)?(?:发明内容|发明概述)\s*$")),
    ("drawings", re.compile(r"^(?:#+\s*)?附图说明\s*$")),
    ("embodiments", re.compile(r"^(?:#+\s*)?(?:具体实施方式|具体实施例)\s*$")),
    ("claims", re.compile(r"^(?:#+\s*)?权利要求(?:书)?\s*$")),
)
_EXAMPLE_RE = re.compile(
    r"^\s*(?:#+\s*)?(?:\[\d+\]\s*)?(实施例|制备例|实验例)\s*([0-9０-９]+)",
    re.IGNORECASE,
)
_CLAIM_RE = re.compile(r"^\s*([0-9０-９]+)[.、]\s*(?:一种|根据|如权利要求)")
_ASSAY_RE = re.compile(
    r"(?:活性|药效|测定|测试|assay|IC\s*50|EC\s*50|抑制率|聚集率|"
    r"细胞活力|细胞毒|协同|Ki\b|Kd\b)",
    re.IGNORECASE,
)
_REFERENCE_RE = re.compile(
    r"(?:方法同|按照|参照|同)(?:上述)?(?:实施例|制备例|实验例)\s*([0-9０-９]+)",
    re.IGNORECASE,
)


def _ascii_digits(value: str) -> str:
    return value.translate(str.maketrans("０１２３４５６７８９", "0123456789"))


def _section_heading(text: str) -> str | None:
    normalized = text.strip()
    for section_type, pattern in _SECTION_PATTERNS:
        if pattern.match(normalized):
            return section_type
    return None


def _example_match(text: str) -> tuple[str, str] | None:
    match = _EXAMPLE_RE.search(text[:160])
    if not match:
        return None
    return match.group(1), _ascii_digits(match.group(2))


def _claim_match(text: str) -> str | None:
    match = _CLAIM_RE.match(text[:200])
    return _ascii_digits(match.group(1)) if match else None


def _example_references(text: str) -> list[str]:
    return [f"example:{_ascii_digits(match.group(1))}" for match in _REFERENCE_RE.finditer(text)]


def _new_chunk(
    index: int,
    section_type: str,
    *,
    title: str = "",
    example_no: str = "",
    claim_no: str = "",
) -> PatentChunk:
    suffix = example_no or claim_no or str(index)
    return PatentChunk(
        chunk_id=f"{section_type}:{suffix}",
        section_type=section_type,
        section_title=title,
        example_no=example_no,
        claim_no=claim_no,
    )


def build_patent_chunks(units: list[TextUnit]) -> list[PatentChunk]:
    """Build section/example/claim chunks while preserving atomic units."""
    chunks: list[PatentChunk] = []
    current: PatentChunk | None = None
    top_section = "front_matter"
    top_title = ""

    def flush() -> None:
        nonlocal current
        if current and current.units:
            chunks.append(current)
        current = None

    for unit in units:
        text = unit.text.strip()
        heading = _section_heading(text)
        if heading:
            flush()
            top_section = heading
            top_title = text
            current = _new_chunk(
                len(chunks),
                top_section,
                title=top_title,
            )
            current.append(unit)
            continue

        example = _example_match(text)
        if example:
            flush()
            _kind, number = example
            current = _new_chunk(
                len(chunks),
                "example",
                title=text[:240],
                example_no=number,
            )
            current.append(unit)
            continue

        claim_no = _claim_match(text)
        if claim_no and top_section not in {"embodiments", "example"}:
            flush()
            top_section = "claims"
            current = _new_chunk(
                len(chunks),
                "claim",
                title=text[:240],
                claim_no=claim_no,
            )
            current.append(unit)
            continue

        if current is None:
            current = _new_chunk(
                len(chunks),
                top_section,
                title=top_title,
            )

        if unit.type != "table" and _ASSAY_RE.search(text):
            if current.section_type != "assay":
                flush()
                current = _new_chunk(
                    len(chunks),
                    "assay",
                    title=text[:240],
                )
            current.append(unit)
            continue

        if unit.type == "table" and current.section_type == "assay":
            current.append(unit)
            continue

        # A table and its local assay description form an explicit assay chunk.
        if unit.type == "table" and (
            _ASSAY_RE.search(text) or any(_ASSAY_RE.search(u.text) for u in current.units[-3:])
        ):
            if current.units:
                context_units = current.units[-3:]
                current.units = current.units[:-3]
                current.unit_ids = [u.unit_id for u in current.units]
                if current.units:
                    flush()
                else:
                    current = None
                assay = _new_chunk(
                    len(chunks),
                    "assay",
                    title=context_units[0].text[:240] if context_units else "assay table",
                )
                for context_unit in context_units:
                    assay.append(context_unit)
                assay.append(unit)
                chunks.append(assay)
                current = _new_chunk(
                    len(chunks),
                    top_section,
                    title=top_title,
                )
                continue

        current.append(unit)

    flush()
    return chunks


def split_oversized_chunk(
    chunk: PatentChunk,
    *,
    max_chars: int,
) -> list[PatentChunk]:
    """Split only between TextUnits; preserve parent metadata in every part."""
    if chunk.char_count <= max_chars:
        return [chunk]

    def split_table_unit(unit: TextUnit) -> list[TextUnit]:
        rows = unit.text.splitlines()
        headers = rows[: min(2, len(rows))]
        table_units: list[TextUnit] = []
        current = list(headers)
        size = sum(len(row) + 1 for row in current)
        for row in rows[len(headers) :]:
            if len(current) > len(headers) and size + len(row) + 1 > max_chars:
                table_units.append(replace(unit, text="\n".join(current)))
                current = list(headers)
                size = sum(len(header) + 1 for header in headers)
            current.append(row)
            size += len(row) + 1
        if current:
            table_units.append(replace(unit, text="\n".join(current)))
        return table_units

    spectral_pattern = re.compile(r"\b(?:[13]H|13C)?\s*NMR\b|HRMS|ESI", re.IGNORECASE)

    def compact_spectral(unit: TextUnit) -> TextUnit:
        match = spectral_pattern.search(unit.text)
        if not match or len(unit.text) - match.start() < 200:
            return unit
        prefix = unit.text[: match.start()].rstrip()
        text = "\n".join(part for part in (prefix, f"{match.group(0)} [spectral peaks omitted]") if part)
        return replace(unit, text=text)

    split_units: list[TextUnit] = []
    for unit in chunk.units:
        if unit.type == "table" and len(unit.text) + 64 > max_chars:
            split_units.extend(split_table_unit(unit))
        else:
            split_units.append(compact_spectral(unit))
    parts: list[PatentChunk] = []
    current_units: list[TextUnit] = []
    size = 0
    for unit in split_units:
        cost = len(unit.text) + 64
        if current_units and size + cost > max_chars:
            parts.append(
                replace(
                    chunk,
                    chunk_id=f"{chunk.chunk_id}:part{len(parts) + 1}",
                    unit_ids=[u.unit_id for u in current_units],
                    units=list(current_units),
                    parent_chunk_id=chunk.chunk_id,
                    part=len(parts) + 1,
                    page_start=current_units[0].page,
                    page_end=current_units[-1].page,
                )
            )
            current_units = []
            size = 0
        current_units.append(unit)
        size += cost
    if current_units:
        parts.append(
            replace(
                chunk,
                chunk_id=f"{chunk.chunk_id}:part{len(parts) + 1}",
                unit_ids=[u.unit_id for u in current_units],
                units=list(current_units),
                parent_chunk_id=chunk.chunk_id,
                part=len(parts) + 1,
                page_start=current_units[0].page,
                page_end=current_units[-1].page,
            )
        )
    return parts


def pack_patent_chunks(
    chunks: list[PatentChunk],
    *,
    max_chars: int,
) -> list[list[PatentChunk]]:
    """Pack whole structural chunks without mixing section types."""
    expanded = [part for chunk in chunks for part in split_oversized_chunk(chunk, max_chars=max_chars)]
    batches: list[list[PatentChunk]] = []
    current: list[PatentChunk] = []
    current_type = ""
    size = 0
    for chunk in expanded:
        incompatible = bool(current and chunk.section_type != current_type)
        over_budget = bool(current and size + chunk.char_count > max_chars)
        if incompatible or over_budget:
            batches.append(current)
            current = []
            size = 0
        if not current:
            current_type = chunk.section_type
        current.append(chunk)
        size += chunk.char_count
    if current:
        batches.append(current)
    return batches
