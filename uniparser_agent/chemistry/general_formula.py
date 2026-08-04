"""Extract the CN-patent Markush general-formula analysis table."""

from __future__ import annotations

import base64
import html
import json
import re
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Iterator

from PIL import Image, ImageChops, ImageOps

from uniparser_agent.chemistry.patent_structure import BlockResolver
from uniparser_agent.llm import LLMConfig, OpenAICompatLLM, resolve_llm_config


SCHEMA_VERSION = "2.0"
TABLE_NAME = "general_formula_analysis"
CONTEXT_NODE_ID = "description.invention_summary"
CHUNK_TARGET_CHARS = 12_000
CHUNK_OVERLAP_CHARS = 800

TABLE_COLUMNS = (
    "doc_id",
    "formula_id",
    "formula_label",
    "formula_name",
    "formula_role",
    "structure_image",
    "markush_smiles",
    "variable_definition_text",
    "evidence_locations",
)

FORMULA_ROLES = frozenset({"target_compound", "starting_material", "intermediate", "unknown"})
_TEXT_TYPES = frozenset(
    {
        "documenttitle",
        "imagecaption",
        "keyvalue",
        "moleculeid",
        "paragraph",
        "tablecaption",
        "text",
        "title",
    }
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

GENERAL_FORMULA_SYSTEM_PROMPT = """You extract Markush general-formula facts from the invention-summary section of a chemistry patent.
Return STRICT JSON only, without markdown fences:
{
  "results": [
    {
      "formula_id": "F001",
      "formula_name": "string or empty",
      "formula_role": "target_compound|starting_material|intermediate|unknown",
      "evidence_unit_ids": ["p8_b13"],
      "definition_fragments": [
        {
          "text": "plain-text variable or parameter definition",
          "evidence_unit_ids": ["p8_b18"]
        }
      ]
    }
  ]
}
Rules:
- Use only the supplied invention-summary context chunk.
- Treat any structure notation from UniParser as read-only evidence.
- Never generate, repair, normalize, or return SMILES.
- Return a formula only when the chunk contains supporting evidence for it.
- Keep formula_id exactly as supplied. Never create formula ids.
- Preserve general, preferred, and more-preferred definition levels when present.
- Include R/Ar/X variables and m/n parameters in definition_fragments.
- evidence_unit_ids must be selected from allowed_unit_ids.
- Do not extract examples or claims.
"""


ChatFn = Callable[[str, str], str]


@dataclass
class FormulaOccurrence:
    page_index: int
    block_index: int
    top_block: int | None
    molecule_block: int | None
    order: int
    label: str | None
    source: str | None
    confidence: float
    in_invention_summary: bool

    @property
    def location_key(self) -> tuple[int, int, int]:
        return self.page_index, self.block_index, self.order

    def public_location(self) -> dict[str, Any]:
        location = {
            "page_index": self.page_index,
            "block_index": self.block_index,
            "block": self.top_block,
        }
        if self.molecule_block is not None and self.molecule_block != self.top_block:
            location["molecule_block"] = self.molecule_block
        return location


@dataclass
class MarkushFormula:
    doc_id: str
    formula_id: str
    smi: str
    occurrences: list[FormulaOccurrence] = field(default_factory=list)
    formula_label: str | None = None
    structure_image: str | None = None

    @property
    def first_location(self) -> tuple[int, int, int]:
        return min(occurrence.location_key for occurrence in self.occurrences)

    def public_inventory_row(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "formula_id": self.formula_id,
            "formula_label": self.formula_label,
            "markush_smiles": self.smi,
            "structure_image": self.structure_image,
            "occurrences": [occurrence.public_location() for occurrence in self.occurrences],
        }


@dataclass(frozen=True)
class ContextUnit:
    unit_id: str
    page_index: int
    block_index: int
    block: int | None
    block_type: str
    text: str

    def render(self) -> str:
        return f"[{self.unit_id}|page={self.page_index + 1}|block={self.block}]\n{self.text.strip()}\n\n"

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "page_index": self.page_index,
            "block_index": self.block_index,
            "block": self.block,
            "type": self.block_type,
            "text": self.text,
        }


@dataclass(frozen=True)
class ContextChunk:
    chunk_id: str
    char_start: int
    char_end: int
    overlap_chars: int
    unit_ids: tuple[str, ...]
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "char_count": len(self.text),
            "overlap_chars": self.overlap_chars,
            "unit_ids": list(self.unit_ids),
            "text": self.text,
        }


@dataclass(frozen=True)
class GeneralFormulaOutputs:
    inventory_path: Path
    context_chunks_path: Path
    analysis_path: Path
    excel_path: Path
    summary_path: Path
    formula_count: int
    occurrence_count: int
    image_count: int
    chunk_count: int
    llm_call_count: int


def _walk_dicts(
    value: Any, ancestors: tuple[dict[str, Any], ...] = ()
) -> Iterator[tuple[dict[str, Any], tuple[dict[str, Any], ...]]]:
    if isinstance(value, dict):
        yield value, ancestors
        next_ancestors = (*ancestors, value)
        for child in value.values():
            yield from _walk_dicts(child, next_ancestors)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child, ancestors)


def _descendants(node: dict[str, Any], block_type: str) -> list[dict[str, Any]]:
    return [item for item, _ in _walk_dicts(node) if item is not node and item.get("type") == block_type]


def _normalize_label(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    label = _WHITESPACE_RE.sub("", value).strip(";；,，。")
    return label or None


def _label_score(label: str | None) -> int:
    if not label:
        return 0
    if "式" in label:
        return 5
    if re.search(r"[（(][IVX]+[)）]", label, re.IGNORECASE):
        return 4
    if re.search(r"[（(][a-z][)）]", label, re.IGNORECASE):
        return 3
    if re.fullmatch(r"\d+", label):
        return 2
    return 1


def _label_for_molecule(
    molecule: dict[str, Any],
    ancestors: tuple[dict[str, Any], ...],
) -> str | None:
    for ancestor in reversed(ancestors):
        ancestor_type = str(ancestor.get("type") or "")
        if ancestor_type not in {"moleculegroup", "figuregroup", "expression", "image", "group"}:
            continue
        molecules = _descendants(ancestor, "molecule")
        molecule_ids = _descendants(ancestor, "moleculeid")
        if len(molecules) == 1 and molecule_ids:
            return _normalize_label(molecule_ids[0].get("text"))
        if ancestor_type == "moleculegroup" and molecule_ids:
            direct_items = ancestor.get("items")
            if isinstance(direct_items, list) and molecule in direct_items:
                return _normalize_label(molecule_ids[0].get("text"))
    return None


def _located_blocks(resolver: BlockResolver, node_id: str) -> list[dict[str, Any]]:
    located = resolver.resolve(node_id, include_locations=True)
    for item in located:
        if not isinstance(item.get("locator"), dict) or not isinstance(item.get("content"), dict):
            raise ValueError(f"Invalid located block returned for {node_id}")
    return located


def build_markush_inventory(resolver: BlockResolver, doc_id: str) -> list[MarkushFormula]:
    """Collect and raw-SMI deduplicate all ``markush=true`` molecules in description."""
    description = _located_blocks(resolver, "description")
    summary_keys = {
        (int(item["locator"]["page_index"]), int(item["locator"]["block_index"]))
        for item in _located_blocks(resolver, CONTEXT_NODE_ID)
    }
    by_dedup_key: dict[str, MarkushFormula] = {}

    for located in description:
        locator = located["locator"]
        content = located["content"]
        page_index = int(locator["page_index"])
        block_index = int(locator["block_index"])
        for node, ancestors in _walk_dicts(content):
            if node.get("type") != "molecule" or node.get("markush") is not True:
                continue
            smi = str(node.get("smi") or "").strip()
            occurrence = FormulaOccurrence(
                page_index=page_index,
                block_index=block_index,
                top_block=locator.get("block"),
                molecule_block=node.get("block"),
                order=int(node.get("order") or 0),
                label=_label_for_molecule(node, ancestors),
                source=node.get("source") if isinstance(node.get("source"), str) else None,
                confidence=float(node.get("conf") or 0.0),
                in_invention_summary=(page_index, block_index) in summary_keys,
            )
            dedup_key = (
                f"smi:{smi}"
                if smi
                else f"missing:{page_index}:{block_index}:{occurrence.molecule_block}:{occurrence.order}"
            )
            formula = by_dedup_key.setdefault(
                dedup_key,
                MarkushFormula(doc_id=doc_id, formula_id="", smi=smi),
            )
            formula.occurrences.append(occurrence)

    formulas = sorted(by_dedup_key.values(), key=lambda formula: formula.first_location)
    for index, formula in enumerate(formulas, start=1):
        formula.formula_id = f"F{index:03d}"
        labels = [occurrence for occurrence in formula.occurrences if occurrence.label]
        if labels:
            best_label = max(
                labels,
                key=lambda occurrence: (
                    _label_score(occurrence.label),
                    int(occurrence.in_invention_summary),
                    -occurrence.page_index,
                    -occurrence.block_index,
                ),
            )
            formula.formula_label = best_label.label
        formula.occurrences.sort(key=lambda occurrence: occurrence.location_key)
    return formulas


def _normalized_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return _WHITESPACE_RE.sub(" ", value.replace("\r", "\n")).strip()


def _table_text(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return ""
    return _normalized_text(html.unescape(_HTML_TAG_RE.sub(" ", value)))


def build_invention_context_units(
    resolver: BlockResolver,
    formulas: list[MarkushFormula],
) -> list[ContextUnit]:
    """Build compact text/structure-anchor units from invention-summary only."""
    formula_by_smi = {formula.smi: formula for formula in formulas if formula.smi}
    formula_by_occurrence = {
        (
            occurrence.page_index,
            occurrence.block_index,
            occurrence.molecule_block,
            occurrence.order,
        ): formula
        for formula in formulas
        for occurrence in formula.occurrences
    }
    units: list[ContextUnit] = []

    for located in _located_blocks(resolver, CONTEXT_NODE_ID):
        locator = located["locator"]
        content = located["content"]
        parts: list[str] = []
        block_type = str(content.get("type") or "")
        if block_type in _TEXT_TYPES:
            text = _normalized_text(content.get("text"))
            if text:
                parts.append(text)
        elif block_type == "table":
            text = _table_text(content.get("structure"))
            if text:
                parts.append(text)

        seen_options: set[str] = set()
        for node, _ in _walk_dicts(content):
            if node.get("type") != "molecule":
                continue
            smi = str(node.get("smi") or "").strip()
            formula = formula_by_occurrence.get(
                (
                    int(locator["page_index"]),
                    int(locator["block_index"]),
                    node.get("block"),
                    int(node.get("order") or 0),
                )
            ) or formula_by_smi.get(smi)
            if node.get("markush") is True and formula is not None:
                label = formula.formula_label or ""
                parts.append(f"[FORMULA formula_id={formula.formula_id} label={label}]")
            elif smi and "*" in smi and smi not in seen_options:
                seen_options.add(smi)
                parts.append(f"[STRUCTURE_OPTION smiles={smi}]")

        if not parts:
            continue
        page_index = int(locator["page_index"])
        block_index = int(locator["block_index"])
        units.append(
            ContextUnit(
                unit_id=f"p{page_index + 1}_b{block_index}",
                page_index=page_index,
                block_index=block_index,
                block=locator.get("block"),
                block_type=block_type,
                text="\n".join(parts),
            )
        )
    return units


def chunk_context_units(
    units: list[ContextUnit],
    *,
    target_chars: int = CHUNK_TARGET_CHARS,
    overlap_chars: int = CHUNK_OVERLAP_CHARS,
) -> list[ContextChunk]:
    """Cut rendered context at about 12k characters with 800-character overlap."""
    if target_chars <= 0:
        raise ValueError("target_chars must be positive")
    if overlap_chars < 0 or overlap_chars >= target_chars:
        raise ValueError("overlap_chars must be between 0 and target_chars")
    if not units:
        return []

    rendered_parts: list[str] = []
    spans: list[tuple[int, int, str]] = []
    cursor = 0
    for unit in units:
        rendered = unit.render()
        rendered_parts.append(rendered)
        spans.append((cursor, cursor + len(rendered), unit.unit_id))
        cursor += len(rendered)
    text = "".join(rendered_parts)

    chunks: list[ContextChunk] = []
    start = 0
    previous_end = 0
    while start < len(text):
        ideal_end = min(start + target_chars, len(text))
        end = ideal_end
        if ideal_end < len(text):
            boundary = text.rfind("\n\n[", start + target_chars // 2, ideal_end)
            if boundary > start:
                end = boundary + 2
        if end <= start:
            end = ideal_end

        unit_ids = tuple(unit_id for left, right, unit_id in spans if left < end and right > start)
        chunks.append(
            ContextChunk(
                chunk_id=f"C{len(chunks) + 1:03d}",
                char_start=start,
                char_end=end,
                overlap_chars=max(0, previous_end - start),
                unit_ids=unit_ids,
                text=text[start:end],
            )
        )
        if end >= len(text):
            break

        next_start = max(start + 1, end - overlap_chars)
        containing_span = next(
            ((left, right) for left, right, _ in spans if left <= next_start < right),
            None,
        )
        if containing_span is not None and containing_span[0] > start:
            next_start = containing_span[0]
        previous_end = end
        start = next_start
    return chunks


def _strip_fences(value: str) -> str:
    text = (value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_general_formula_response(raw: str) -> list[dict[str, Any]]:
    payload = json.loads(_strip_fences(raw))
    if isinstance(payload, dict):
        results = payload.get("results")
    elif isinstance(payload, list):
        results = payload
    else:
        results = None
    if not isinstance(results, list):
        raise ValueError("LLM response must be a list or {results: [...]} object")
    return [item for item in results if isinstance(item, dict)]


def build_general_formula_prompt(
    doc_id: str,
    formulas: list[MarkushFormula],
    chunk: ContextChunk,
) -> tuple[str, str]:
    inventory = [
        {
            "formula_id": formula.formula_id,
            "formula_label": formula.formula_label,
            "occurrence_pages": sorted({occurrence.page_index + 1 for occurrence in formula.occurrences}),
        }
        for formula in formulas
    ]
    payload = {
        "document": doc_id,
        "context_scope": CONTEXT_NODE_ID,
        "chunk_id": chunk.chunk_id,
        "allowed_unit_ids": list(chunk.unit_ids),
        "formula_inventory": inventory,
        "context": chunk.text,
    }
    return GENERAL_FORMULA_SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False, indent=2)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _normalize_fragment(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return _WHITESPACE_RE.sub(" ", value).strip(" ;；。")


def _context_location(unit: ContextUnit) -> dict[str, Any]:
    return {
        "kind": "context",
        "page_index": unit.page_index,
        "block_index": unit.block_index,
        "block": unit.block,
    }


def analyze_general_formulas(
    doc_id: str,
    formulas: list[MarkushFormula],
    units: list[ContextUnit],
    chunks: list[ContextChunk],
    *,
    llm_config: LLMConfig | None = None,
    llm_client: OpenAICompatLLM | None = None,
    chat_fn: ChatFn | None = None,
    skip_llm: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Analyze chunks and deterministically merge partial formula evidence."""
    valid_ids = {formula.formula_id for formula in formulas}
    unit_by_id = {unit.unit_id: unit for unit in units}
    unit_order = {unit.unit_id: index for index, unit in enumerate(units)}
    accumulators: dict[str, dict[str, Any]] = {
        formula.formula_id: {
            "names": [],
            "roles": [],
            "fragments": [],
            "evidence_unit_ids": [],
        }
        for formula in formulas
    }
    errors: list[dict[str, str]] = []
    llm_call_count = 0
    resolved_client = llm_client

    def chat(system_prompt: str, user_content: str) -> str:
        nonlocal resolved_client
        if chat_fn is not None:
            return chat_fn(system_prompt, user_content)
        if resolved_client is None:
            resolved_client = OpenAICompatLLM(config=llm_config or resolve_llm_config())
        return resolved_client.chat(system_prompt=system_prompt, user_content=user_content)

    llm_enabled = not skip_llm and bool(formulas) and bool(chunks)
    if llm_enabled:
        for chunk_index, chunk in enumerate(chunks):
            system_prompt, user_content = build_general_formula_prompt(doc_id, formulas, chunk)
            llm_call_count += 1
            try:
                raw = chat(system_prompt, user_content)
                items = parse_general_formula_response(raw)
            except Exception as exc:  # noqa: BLE001 - one invalid chunk must not discard the inventory
                errors.append({"chunk_id": chunk.chunk_id, "error": str(exc)})
                continue

            allowed_units = set(chunk.unit_ids)
            for result_index, item in enumerate(items):
                formula_id = str(item.get("formula_id") or "").strip()
                if formula_id not in valid_ids:
                    continue
                accumulator = accumulators[formula_id]
                formula_name = _normalized_text(item.get("formula_name"))
                if formula_name:
                    accumulator["names"].append((chunk_index, result_index, formula_name))
                role = str(item.get("formula_role") or "unknown").strip()
                if role not in FORMULA_ROLES:
                    role = "unknown"
                accumulator["roles"].append((chunk_index, result_index, role))

                result_evidence = [
                    unit_id for unit_id in _string_list(item.get("evidence_unit_ids")) if unit_id in allowed_units
                ]
                accumulator["evidence_unit_ids"].extend(result_evidence)
                fragments = item.get("definition_fragments")
                if isinstance(fragments, list):
                    for fragment_index, fragment in enumerate(fragments):
                        if not isinstance(fragment, dict):
                            continue
                        text = _normalize_fragment(fragment.get("text"))
                        if not text:
                            continue
                        evidence_ids = [
                            unit_id
                            for unit_id in _string_list(fragment.get("evidence_unit_ids"))
                            if unit_id in allowed_units
                        ]
                        accumulator["evidence_unit_ids"].extend(evidence_ids)
                        accumulator["fragments"].append(
                            {
                                "text": text,
                                "evidence_unit_ids": evidence_ids,
                                "sort_key": (
                                    min((unit_order.get(unit_id, 10**9) for unit_id in evidence_ids), default=10**9),
                                    chunk_index,
                                    result_index,
                                    fragment_index,
                                ),
                            }
                        )

    rows: list[dict[str, Any]] = []
    for formula in formulas:
        accumulator = accumulators[formula.formula_id]
        names = sorted(accumulator["names"])
        roles = sorted(accumulator["roles"])
        formula_name = names[0][2] if names else None
        formula_role = next((role for _, _, role in roles if role != "unknown"), "unknown")

        fragments = sorted(accumulator["fragments"], key=lambda item: item["sort_key"])
        unique_fragments: list[str] = []
        seen_fragments: set[str] = set()
        for fragment in fragments:
            normalized_key = _WHITESPACE_RE.sub("", fragment["text"]).lower()
            if normalized_key in seen_fragments:
                continue
            seen_fragments.add(normalized_key)
            unique_fragments.append(fragment["text"])

        evidence_ids = sorted(
            set(accumulator["evidence_unit_ids"]),
            key=lambda unit_id: unit_order.get(unit_id, 10**9),
        )
        evidence_locations = [{"kind": "formula", **occurrence.public_location()} for occurrence in formula.occurrences]
        evidence_locations.extend(
            _context_location(unit_by_id[unit_id]) for unit_id in evidence_ids if unit_id in unit_by_id
        )
        rows.append(
            {
                "doc_id": doc_id,
                "formula_id": formula.formula_id,
                "formula_label": formula.formula_label,
                "formula_name": formula_name,
                "formula_role": formula_role,
                "structure_image": formula.structure_image,
                "markush_smiles": formula.smi,
                "variable_definition_text": "；".join(unique_fragments),
                "evidence_locations": evidence_locations,
            }
        )

    return rows, {
        "uses_llm": llm_enabled,
        "llm_call_count": llm_call_count,
        "llm_errors": errors,
    }


def _decode_source(source: str) -> bytes:
    payload = source.split(",", 1)[1] if source.startswith("data:") and "," in source else source
    return base64.b64decode(payload, validate=False)


def _save_structure_image(source: str, output_path: Path) -> tuple[int, int]:
    image = Image.open(BytesIO(_decode_source(source))).convert("RGB")
    white = Image.new("RGB", image.size, "white")
    diff = ImageChops.difference(image, white).convert("L")
    diff = diff.point(lambda value: 255 if value > 12 else 0)
    bbox = diff.getbbox()
    if bbox is not None:
        image = image.crop(bbox)
    image = ImageOps.expand(image, border=12, fill="white")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", optimize=True)
    return image.size


def _source_area(source: str | None) -> int:
    if not source:
        return 0
    try:
        with Image.open(BytesIO(_decode_source(source))) as image:
            return image.width * image.height
    except Exception:  # noqa: BLE001 - invalid candidates are retried during image writing
        return 0


def write_structure_images(
    formulas: list[MarkushFormula],
    output_dir: Path,
) -> dict[str, dict[str, int]]:
    """Write one original UniParser molecule crop per unique formula."""
    image_meta: dict[str, dict[str, int]] = {}
    for formula in formulas:
        ranked = sorted(
            (occurrence for occurrence in formula.occurrences if occurrence.source),
            key=lambda occurrence: (
                -_label_score(occurrence.label),
                -int(occurrence.in_invention_summary),
                -_source_area(occurrence.source),
                -occurrence.confidence,
                occurrence.page_index,
                occurrence.block_index,
            ),
        )
        for occurrence in ranked:
            image_path = output_dir / formula.doc_id / f"{formula.formula_id}.png"
            try:
                width, height = _save_structure_image(occurrence.source or "", image_path)
            except Exception:  # noqa: BLE001 - try another parsed occurrence of the same formula
                continue
            formula.structure_image = str(image_path)
            image_meta[formula.formula_id] = {"width": width, "height": height}
            break
    return image_meta


def build_general_formula_analysis_payload(
    doc_id: str,
    rows: list[dict[str, Any]],
    *,
    chunk_count: int,
    llm_meta: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "table_name": TABLE_NAME,
        "patent_format": "CN",
        "extraction_scope": {
            "inventory_navigation_node": "description",
            "inventory_filter": {"type": "molecule", "markush": True},
            "context_navigation_node": CONTEXT_NODE_ID,
            "chunk_target_chars": CHUNK_TARGET_CHARS,
            "chunk_overlap_chars": CHUNK_OVERLAP_CHARS,
            "chunk_count": chunk_count,
            "uses_llm": llm_meta["uses_llm"],
        },
        "columns": list(TABLE_COLUMNS),
        "rows": rows,
    }


def write_general_formula_outputs(
    resolver: BlockResolver,
    doc_id: str,
    output_dir: str | Path,
    *,
    llm_config: LLMConfig | None = None,
    llm_client: OpenAICompatLLM | None = None,
    chat_fn: ChatFn | None = None,
    skip_llm: bool = False,
) -> GeneralFormulaOutputs:
    """Run the complete V2 Markush table flow and write JSON, images, and Excel."""
    target_dir = Path(output_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    formulas = build_markush_inventory(resolver, doc_id)
    image_meta = write_structure_images(formulas, target_dir / "structure_images")
    units = build_invention_context_units(resolver, formulas)
    chunks = chunk_context_units(units)
    rows, llm_meta = analyze_general_formulas(
        doc_id,
        formulas,
        units,
        chunks,
        llm_config=llm_config,
        llm_client=llm_client,
        chat_fn=chat_fn,
        skip_llm=skip_llm,
    )

    inventory_path = target_dir / "markush_inventory.json"
    context_chunks_path = target_dir / "formula_context_chunks.json"
    analysis_path = target_dir / "general_formula_analysis.json"
    excel_path = target_dir / "general_formula_analysis.xlsx"
    summary_path = target_dir / "general_formula_extraction_summary.json"

    inventory_payload = {
        "schema_version": SCHEMA_VERSION,
        "doc_id": doc_id,
        "navigation_node": "description",
        "filter": {"type": "molecule", "markush": True},
        "deduplication": {
            "method": "raw_smi_exact",
            "missing_smi": "keep_each_occurrence",
        },
        "formulas": [formula.public_inventory_row() for formula in formulas],
    }
    inventory_path.write_text(
        json.dumps(inventory_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    context_chunks_path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "doc_id": doc_id,
                "navigation_node": CONTEXT_NODE_ID,
                "target_chars": CHUNK_TARGET_CHARS,
                "overlap_chars": CHUNK_OVERLAP_CHARS,
                "units": [unit.to_dict() for unit in units],
                "chunks": [chunk.to_dict() for chunk in chunks],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    analysis_payload = build_general_formula_analysis_payload(
        doc_id,
        rows,
        chunk_count=len(chunks),
        llm_meta=llm_meta,
    )
    analysis_path.write_text(
        json.dumps(analysis_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    from uniparser_agent.chemistry.general_formula_excel import write_general_formula_excel

    write_general_formula_excel(rows, excel_path)
    occurrence_count = sum(len(formula.occurrences) for formula in formulas)
    summary_payload = {
        "schema_version": SCHEMA_VERSION,
        "doc_id": doc_id,
        "formula_count": len(formulas),
        "occurrence_count": occurrence_count,
        "structure_image_count": len(image_meta),
        "context_unit_count": len(units),
        "chunk_count": len(chunks),
        "llm_call_count": llm_meta["llm_call_count"],
        "llm_errors": llm_meta["llm_errors"],
        "outputs": {
            "inventory": str(inventory_path),
            "context_chunks": str(context_chunks_path),
            "analysis": str(analysis_path),
            "excel": str(excel_path),
        },
    }
    summary_path.write_text(
        json.dumps(summary_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return GeneralFormulaOutputs(
        inventory_path=inventory_path,
        context_chunks_path=context_chunks_path,
        analysis_path=analysis_path,
        excel_path=excel_path,
        summary_path=summary_path,
        formula_count=len(formulas),
        occurrence_count=occurrence_count,
        image_count=len(image_meta),
        chunk_count=len(chunks),
        llm_call_count=int(llm_meta["llm_call_count"]),
    )
