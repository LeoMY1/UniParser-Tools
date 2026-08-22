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
from uniparser_agent.llm import LLMConfig, OpenAICompatLLM


SCHEMA_VERSION = "3.0"
TABLE_NAME = "general_formula_analysis"
CONTEXT_NODE_ID = "description"

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
class MarkushStructure:
    doc_id: str
    structure_id: str
    smi: str
    occurrences: list[FormulaOccurrence] = field(default_factory=list)
    structure_image: str | None = None

    @property
    def first_location(self) -> tuple[int, int, int]:
        return min(occurrence.location_key for occurrence in self.occurrences)

    def public_inventory_row(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "structure_id": self.structure_id,
            "markush_smiles": self.smi,
            "structure_image": self.structure_image,
            "occurrences": [
                {**occurrence.public_location(), "formula_label": occurrence.label} for occurrence in self.occurrences
            ],
        }


@dataclass
class FormulaRecord:
    doc_id: str
    formula_id: str
    structure_id: str
    smi: str
    occurrences: list[FormulaOccurrence] = field(default_factory=list)
    formula_label: str | None = None
    structure_image: str | None = None

    @property
    def first_location(self) -> tuple[int, int, int]:
        return min(occurrence.location_key for occurrence in self.occurrences)


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
class GeneralFormulaOutputs:
    inventory_path: Path
    task_packets_path: Path
    evidence_ledger_path: Path
    agent_contexts_path: Path
    analysis_path: Path
    excel_path: Path
    summary_path: Path
    structure_count: int
    formula_count: int
    occurrence_count: int
    image_count: int
    packet_count: int
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


def build_markush_inventory(resolver: BlockResolver, doc_id: str) -> list[MarkushStructure]:
    """Collect and raw-SMI deduplicate all ``markush=true`` molecules in description."""
    description = _located_blocks(resolver, "description")
    by_dedup_key: dict[str, MarkushStructure] = {}

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
            )
            dedup_key = (
                f"smi:{smi}"
                if smi
                else f"missing:{page_index}:{block_index}:{occurrence.molecule_block}:{occurrence.order}"
            )
            formula = by_dedup_key.setdefault(
                dedup_key,
                MarkushStructure(doc_id=doc_id, structure_id="", smi=smi),
            )
            formula.occurrences.append(occurrence)

    structures = sorted(by_dedup_key.values(), key=lambda structure: structure.first_location)
    for index, structure in enumerate(structures, start=1):
        structure.structure_id = f"S{index:03d}"
        structure.occurrences.sort(key=lambda occurrence: occurrence.location_key)
    return structures


def build_formula_records(structures: list[MarkushStructure]) -> list[FormulaRecord]:
    """Create conservative disclosure records without merging different labels."""
    provisional: list[FormulaRecord] = []
    for structure in structures:
        labeled: dict[str, list[FormulaOccurrence]] = {}
        unlabeled: list[FormulaOccurrence] = []
        for occurrence in structure.occurrences:
            if occurrence.label:
                labeled.setdefault(occurrence.label, []).append(occurrence)
            else:
                unlabeled.append(occurrence)

        if len(labeled) == 1:
            only_label = next(iter(labeled))
            labeled[only_label].extend(unlabeled)
            unlabeled = []

        for label, occurrences in labeled.items():
            provisional.append(
                FormulaRecord(
                    doc_id=structure.doc_id,
                    formula_id="",
                    structure_id=structure.structure_id,
                    smi=structure.smi,
                    occurrences=sorted(occurrences, key=lambda item: item.location_key),
                    formula_label=label,
                    structure_image=structure.structure_image,
                )
            )
        if unlabeled or not labeled:
            occurrences = unlabeled or list(structure.occurrences)
            provisional.append(
                FormulaRecord(
                    doc_id=structure.doc_id,
                    formula_id="",
                    structure_id=structure.structure_id,
                    smi=structure.smi,
                    occurrences=sorted(occurrences, key=lambda item: item.location_key),
                    structure_image=structure.structure_image,
                )
            )

    records = sorted(provisional, key=lambda formula: formula.first_location)
    for index, formula in enumerate(records, start=1):
        formula.formula_id = f"F{index:03d}"
    return records


def _normalized_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return _WHITESPACE_RE.sub(" ", value.replace("\r", "\n")).strip()


def _table_text(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return ""
    return _normalized_text(html.unescape(_HTML_TAG_RE.sub(" ", value)))


def build_description_context_units(
    resolver: BlockResolver,
    formulas: list[FormulaRecord],
) -> list[ContextUnit]:
    """Build compact text/structure-anchor units from the complete description."""
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
            )
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
    structures: list[MarkushStructure],
    output_dir: Path,
) -> dict[str, dict[str, int]]:
    """Write one original UniParser molecule crop per raw-SMI structure."""
    image_meta: dict[str, dict[str, int]] = {}
    for structure in structures:
        ranked = sorted(
            (occurrence for occurrence in structure.occurrences if occurrence.source),
            key=lambda occurrence: (
                -_label_score(occurrence.label),
                -_source_area(occurrence.source),
                -occurrence.confidence,
                occurrence.page_index,
                occurrence.block_index,
            ),
        )
        for occurrence in ranked:
            image_path = output_dir / structure.doc_id / f"{structure.structure_id}.png"
            try:
                width, height = _save_structure_image(occurrence.source or "", image_path)
            except Exception:  # noqa: BLE001 - try another parsed occurrence of the same formula
                continue
            structure.structure_image = str(image_path)
            image_meta[structure.structure_id] = {"width": width, "height": height}
            break
    return image_meta


def build_general_formula_analysis_payload(
    doc_id: str,
    rows: list[dict[str, Any]],
    *,
    packet_count: int,
    agent_meta: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "table_name": TABLE_NAME,
        "patent_format": "CN",
        "extraction_scope": {
            "inventory_navigation_node": "description",
            "inventory_filter": {"type": "molecule", "markush": True},
            "context_navigation_node": CONTEXT_NODE_ID,
            "agent": "formula_anchor_retrieval_v1_1",
            "classification": "same_llm_call",
            "table_object_types": ["general_formula", "scheme_generic_structure"],
            "other_candidates": "retained_in_evidence_ledger",
            "task_packet_count": packet_count,
            "uses_llm": agent_meta["uses_llm"],
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
    """Run the bounded Markush retrieval agent and write its structured artifacts."""
    from uniparser_agent.chemistry.general_formula_agent import (
        AGENT_SCHEMA_VERSION,
        CONTEXT_TARGET_CHARS,
        JSON_RETRY_COUNT,
        MAX_AGENT_ROUNDS,
        MAX_ANCHOR_GAP_CHARS,
        MAX_ANCHOR_SPAN_CHARS,
        MAX_PACKET_FORMULAS,
        PACKET_OVERLAP_CHARS,
        SEARCH_MAX_PAGES,
        SEARCH_PAGE_SIZE,
        run_formula_agent,
    )

    target_dir = Path(output_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    structures = build_markush_inventory(resolver, doc_id)
    image_meta = write_structure_images(structures, target_dir / "structure_images")
    formulas = build_formula_records(structures)
    units = build_description_context_units(resolver, formulas)
    agent_result = run_formula_agent(
        doc_id,
        formulas,
        units,
        llm_config=llm_config,
        llm_client=llm_client,
        chat_fn=chat_fn,
        skip_llm=skip_llm,
    )

    inventory_path = target_dir / "markush_inventory.json"
    task_packets_path = target_dir / "formula_task_packets.json"
    evidence_ledger_path = target_dir / "formula_evidence_ledger.json"
    agent_contexts_path = target_dir / "formula_agent_contexts.json"
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
            "semantic_records": "split_different_labels",
        },
        "structures": [structure.public_inventory_row() for structure in structures],
        "formula_records": [
            {
                "formula_id": formula.formula_id,
                "structure_id": formula.structure_id,
                "formula_label": formula.formula_label,
                "occurrences": [occurrence.public_location() for occurrence in formula.occurrences],
            }
            for formula in formulas
        ],
    }
    inventory_path.write_text(
        json.dumps(inventory_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    task_packets_path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "agent_schema_version": AGENT_SCHEMA_VERSION,
                "doc_id": doc_id,
                "navigation_node": CONTEXT_NODE_ID,
                "parameters": {
                    "context_target_chars": CONTEXT_TARGET_CHARS,
                    "packet_overlap_chars": PACKET_OVERLAP_CHARS,
                    "max_packet_formulas": MAX_PACKET_FORMULAS,
                    "max_anchor_gap_chars": MAX_ANCHOR_GAP_CHARS,
                    "max_anchor_span_chars": MAX_ANCHOR_SPAN_CHARS,
                    "max_agent_rounds": MAX_AGENT_ROUNDS,
                    "search_page_size": SEARCH_PAGE_SIZE,
                    "search_max_pages": SEARCH_MAX_PAGES,
                    "json_retry_count": JSON_RETRY_COUNT,
                },
                "packets": [packet.to_dict() for packet in agent_result.packets],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    evidence_ledger_path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "agent_schema_version": AGENT_SCHEMA_VERSION,
                "doc_id": doc_id,
                "ledger": list(agent_result.ledger.values()),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    agent_contexts_path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "agent_schema_version": AGENT_SCHEMA_VERSION,
                "doc_id": doc_id,
                "units": [unit.to_dict() for unit in units],
                "contexts": [context.to_dict() for context in agent_result.contexts],
                "trace": agent_result.meta["trace"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    analysis_payload = build_general_formula_analysis_payload(
        doc_id,
        agent_result.rows,
        packet_count=len(agent_result.packets),
        agent_meta=agent_result.meta,
    )
    analysis_path.write_text(
        json.dumps(analysis_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    from uniparser_agent.chemistry.general_formula_excel import write_general_formula_excel

    write_general_formula_excel(agent_result.rows, excel_path)
    occurrence_count = sum(len(structure.occurrences) for structure in structures)
    summary_payload = {
        "schema_version": SCHEMA_VERSION,
        "doc_id": doc_id,
        "structure_count": len(structures),
        "formula_record_count": len(formulas),
        "occurrence_count": occurrence_count,
        "structure_image_count": len(image_meta),
        "context_unit_count": len(units),
        "task_packet_count": len(agent_result.packets),
        "agent_context_count": len(agent_result.contexts),
        "complete_formula_count": agent_result.meta["complete_formula_count"],
        "insufficient_formula_count": agent_result.meta["insufficient_formula_count"],
        "output_formula_count": agent_result.meta["output_formula_count"],
        "excluded_formula_count": agent_result.meta["excluded_formula_count"],
        "review_formula_count": agent_result.meta["review_formula_count"],
        "merged_formula_count": agent_result.meta["merged_formula_count"],
        "object_type_counts": agent_result.meta["object_type_counts"],
        "llm_call_count": agent_result.meta["llm_call_count"],
        "llm_errors": agent_result.meta["llm_errors"],
        "outputs": {
            "inventory": str(inventory_path),
            "task_packets": str(task_packets_path),
            "evidence_ledger": str(evidence_ledger_path),
            "agent_contexts": str(agent_contexts_path),
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
        task_packets_path=task_packets_path,
        evidence_ledger_path=evidence_ledger_path,
        agent_contexts_path=agent_contexts_path,
        analysis_path=analysis_path,
        excel_path=excel_path,
        summary_path=summary_path,
        structure_count=len(structures),
        formula_count=len(formulas),
        occurrence_count=occurrence_count,
        image_count=len(image_meta),
        packet_count=len(agent_result.packets),
        llm_call_count=int(agent_result.meta["llm_call_count"]),
    )
