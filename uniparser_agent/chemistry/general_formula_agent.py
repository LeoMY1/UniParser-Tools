"""Bounded retrieval agent for Markush formula evidence extraction."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable

from uniparser_agent.chemistry.general_formula import ContextUnit, FormulaRecord
from uniparser_agent.llm import LLMConfig, OpenAICompatLLM, resolve_llm_config


AGENT_SCHEMA_VERSION = "1.1"
CONTEXT_TARGET_CHARS = 12_000
PACKET_OVERLAP_CHARS = 800
SINGLE_ANCHOR_SIDE_CHARS = 6_000
PACKET_MARGIN_CHARS = 2_000
MAX_PACKET_FORMULAS = 20
MAX_ANCHOR_GAP_CHARS = 3_000
MAX_ANCHOR_SPAN_CHARS = 8_000
MAX_AGENT_ROUNDS = 4
SEARCH_PAGE_SIZE = 5
SEARCH_MAX_PAGES = 4
JSON_RETRY_COUNT = 2

FORMULA_ROLES = frozenset({"target_compound", "starting_material", "intermediate", "unknown"})
FORMULA_OBJECT_TYPES = frozenset(
    {
        "general_formula",
        "scheme_generic_structure",
        "substituent_option",
        "drawing_rule",
        "fixed_compound",
        "reagent_or_catalyst",
        "uncertain",
    }
)
TABLE_OBJECT_TYPES = frozenset({"general_formula", "scheme_generic_structure"})
TABLE_ACTIONS = frozenset({"keep", "exclude", "merge", "review"})
_WHITESPACE_RE = re.compile(r"\s+")
_DEFINITION_CUE_RE = re.compile(
    r"(?:其中|式中|各自独立|独立地|选自|表示|定义为|是指|"
    r"wherein|independently selected|is selected from|represents)",
    re.IGNORECASE,
)

FORMULA_AGENT_SYSTEM_PROMPT = """You are a bounded extraction agent for Markush formulas in a chemistry patent description.
Return STRICT JSON only:
{
  "updates": [
    {
      "formula_id": "F001",
      "object_type": "general_formula|scheme_generic_structure|substituent_option|drawing_rule|fixed_compound|reagent_or_catalyst|uncertain",
      "classification_reason": "short evidence-based reason",
      "formula_name": "string or empty",
      "formula_role": "target_compound|starting_material|intermediate|unknown",
      "evidence_unit_ids": ["p8_b13"],
      "definition_fragments": [
        {"text": "plain-text variable or parameter definition", "evidence_unit_ids": ["p8_b18"]}
      ]
    }
  ],
  "complete_formula_ids": ["F001"],
  "retrieval_requests": [
    {
      "tool": "find_occurrences|search_text|expand_context",
      "formula_ids": ["F001"],
      "query": "optional exact text query",
      "cursor": 0,
      "direction": "before|after",
      "reason": "short missing-evidence reason"
    }
  ]
}
Rules:
- Use only the supplied description evidence. Claims are excluded.
- Treat UniParser structures and SMILES as read-only. Never generate, repair, or normalize SMILES.
- Keep formula_id exactly as supplied and never create identifiers.
- Classify every candidate before marking it complete:
  - general_formula: a disclosed variable-bearing Markush formula defining a compound class.
  - scheme_generic_structure: a variable-bearing generic structure used as a reactant, product, or intermediate in a reaction scheme.
  - substituent_option: one selectable R/Ar/X/Q/Het group, not a complete compound formula.
  - drawing_rule: an attachment-point, bond, stereochemistry, or drawing convention rather than a compound formula.
  - fixed_compound: one fully specified compound, building block, or example structure without patent-defined variables.
  - reagent_or_catalyst: a reagent, catalyst, ligand, solvent, protecting group, or reaction additive.
  - uncertain: the supplied evidence cannot safely distinguish the above classes.
- Typical exclusions: “Rv is selected from the following structures” is substituent_option; an asterisk attachment rule is drawing_rule; Boc/TBS, BB7, Pd catalyst, or a named fixed intermediate is fixed_compound or reagent_or_catalyst.
- A complete variable-bearing reactant/product structure in a synthesis scheme is scheme_generic_structure and is kept.
- Different non-empty labels such as Ia, Ia′, and Ib can refer to distinct disclosures even when UniParser returns the same raw SMILES. Do not request or propose semantic merging.
- Every non-empty extracted value must cite one or more allowed_unit_ids.
- Preserve general, preferred, and more-preferred definition levels when present.
- Include R/Ar/X variables and m/n parameters in definition_fragments.
- Mark a formula complete only when object_type is resolved and the supplied evidence is sufficient. Otherwise request one focused retrieval.
- Use find_occurrences for another depiction of the same formula, search_text for an exact label/variable phrase, and expand_context only for adjacent prose.
- If the patent does not disclose a field after retrieval, leave it empty. Do not infer chemically plausible values.
"""

ChatFn = Callable[[str, str], str]


@dataclass(frozen=True)
class FormulaTaskPacket:
    packet_id: str
    formula_ids: tuple[str, ...]
    anchor_start: int
    anchor_end: int
    context_start: int
    context_end: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "formula_ids": list(self.formula_ids),
            "formula_count": len(self.formula_ids),
            "anchor_start": self.anchor_start,
            "anchor_end": self.anchor_end,
            "anchor_span_chars": self.anchor_end - self.anchor_start,
            "context_start": self.context_start,
            "context_end": self.context_end,
            "context_char_count": self.context_end - self.context_start,
        }


@dataclass(frozen=True)
class AgentContext:
    context_id: str
    packet_id: str
    round_index: int
    tool: str
    formula_ids: tuple[str, ...]
    unit_ids: tuple[str, ...]
    text: str
    source_ranges: tuple[tuple[int, int], ...]
    query: str = ""
    cursor: int = 0
    total_hits: int = 0
    next_cursor: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_id": self.context_id,
            "packet_id": self.packet_id,
            "round_index": self.round_index,
            "tool": self.tool,
            "formula_ids": list(self.formula_ids),
            "unit_ids": list(self.unit_ids),
            "char_count": len(self.text),
            "source_ranges": [list(item) for item in self.source_ranges],
            "query": self.query,
            "cursor": self.cursor,
            "total_hits": self.total_hits,
            "next_cursor": self.next_cursor,
            "text": self.text,
        }


@dataclass(frozen=True)
class AgentRunResult:
    packets: list[FormulaTaskPacket]
    contexts: list[AgentContext]
    ledger: dict[str, dict[str, Any]]
    rows: list[dict[str, Any]]
    meta: dict[str, Any]


class DescriptionContextIndex:
    """Index rendered description units for bounded local and exact-text retrieval."""

    def __init__(self, units: list[ContextUnit], formulas: list[FormulaRecord]) -> None:
        self.units = units
        self.formulas = formulas
        self.unit_by_id = {unit.unit_id: unit for unit in units}
        self.unit_order = {unit.unit_id: index for index, unit in enumerate(units)}
        self.rendered_parts: list[str] = []
        self.spans: list[tuple[int, int, str]] = []
        self.location_positions: dict[tuple[int, int], int] = {}
        cursor = 0
        for unit in units:
            rendered = unit.render()
            start = cursor
            end = start + len(rendered)
            self.rendered_parts.append(rendered)
            self.spans.append((start, end, unit.unit_id))
            self.location_positions[(unit.page_index, unit.block_index)] = start
            cursor = end
        self.text = "".join(self.rendered_parts)
        self.formula_positions = {
            formula.formula_id: sorted(
                {
                    self.location_positions[(occurrence.page_index, occurrence.block_index)]
                    for occurrence in formula.occurrences
                    if (occurrence.page_index, occurrence.block_index) in self.location_positions
                }
            )
            for formula in formulas
        }

    def _balanced_range(self, anchor_start: int, anchor_end: int) -> tuple[int, int]:
        if anchor_start == anchor_end:
            start = anchor_start - SINGLE_ANCHOR_SIDE_CHARS
            end = anchor_end + SINGLE_ANCHOR_SIDE_CHARS
        else:
            start = anchor_start - PACKET_MARGIN_CHARS
            end = anchor_end + PACKET_MARGIN_CHARS
            remaining = max(0, CONTEXT_TARGET_CHARS - (end - start))
            start -= remaining // 2
            end += remaining - remaining // 2
        if start < 0:
            end = min(len(self.text), end - start)
            start = 0
        if end > len(self.text):
            start = max(0, start - (end - len(self.text)))
            end = len(self.text)
        if end - start > CONTEXT_TARGET_CHARS:
            end = start + CONTEXT_TARGET_CHARS
        return start, end

    def build_packets(self) -> list[FormulaTaskPacket]:
        positioned = [
            (formula.formula_id, self.formula_positions[formula.formula_id][0])
            for formula in self.formulas
            if self.formula_positions.get(formula.formula_id)
        ]
        positioned.sort(key=lambda item: item[1])
        groups: list[list[tuple[str, int]]] = []
        current: list[tuple[str, int]] = []
        for item in positioned:
            if not current:
                current = [item]
                continue
            if (
                len(current) >= MAX_PACKET_FORMULAS
                or item[1] - current[-1][1] > MAX_ANCHOR_GAP_CHARS
                or item[1] - current[0][1] > MAX_ANCHOR_SPAN_CHARS
            ):
                groups.append(current)
                current = [item]
            else:
                current.append(item)
        if current:
            groups.append(current)

        packets: list[FormulaTaskPacket] = []
        for index, group in enumerate(groups, start=1):
            anchor_start = group[0][1]
            anchor_end = group[-1][1]
            context_start, context_end = self._balanced_range(anchor_start, anchor_end)
            packets.append(
                FormulaTaskPacket(
                    packet_id=f"P{index:03d}",
                    formula_ids=tuple(item[0] for item in group),
                    anchor_start=anchor_start,
                    anchor_end=anchor_end,
                    context_start=context_start,
                    context_end=context_end,
                )
            )
        return packets

    def _range_unit_ids(self, start: int, end: int) -> tuple[str, ...]:
        return tuple(unit_id for left, right, unit_id in self.spans if left < end and right > start)

    def _range_context(
        self,
        packet: FormulaTaskPacket,
        *,
        round_index: int,
        tool: str,
        start: int,
        end: int,
        formula_ids: tuple[str, ...] | None = None,
        query: str = "",
        cursor: int = 0,
        total_hits: int = 0,
        next_cursor: int | None = None,
    ) -> AgentContext:
        start = max(0, min(start, len(self.text)))
        end = max(start, min(end, len(self.text)))
        return AgentContext(
            context_id=f"{packet.packet_id}_R{round_index:02d}",
            packet_id=packet.packet_id,
            round_index=round_index,
            tool=tool,
            formula_ids=formula_ids or packet.formula_ids,
            unit_ids=self._range_unit_ids(start, end),
            text=self.text[start:end],
            source_ranges=((start, end),),
            query=query,
            cursor=cursor,
            total_hits=total_hits,
            next_cursor=next_cursor,
        )

    def initial_context(self, packet: FormulaTaskPacket) -> AgentContext:
        return self._range_context(
            packet,
            round_index=1,
            tool="initial_context",
            start=packet.context_start,
            end=packet.context_end,
        )

    def _compose_hits(
        self,
        packet: FormulaTaskPacket,
        *,
        round_index: int,
        tool: str,
        hit_positions: list[int],
        formula_ids: tuple[str, ...],
        query: str,
        cursor: int,
    ) -> AgentContext:
        page_start = min(max(cursor, 0), SEARCH_MAX_PAGES - 1) * SEARCH_PAGE_SIZE
        selected = hit_positions[page_start : page_start + SEARCH_PAGE_SIZE]
        ranges: list[tuple[int, int]] = []
        snippets: list[str] = []
        unit_ids: list[str] = []
        if selected:
            budget = max(600, CONTEXT_TARGET_CHARS // len(selected))
            for hit_index, position in enumerate(selected, start=1):
                start = max(0, position - budget // 2)
                end = min(len(self.text), start + budget)
                start = max(0, end - budget)
                ranges.append((start, end))
                snippet = self.text[start:end]
                snippets.append(f"[RETRIEVAL_HIT {hit_index}]\n{snippet}")
                unit_ids.extend(self._range_unit_ids(start, end))
        text = "\n\n".join(snippets)[:CONTEXT_TARGET_CHARS]
        unique_unit_ids = tuple(dict.fromkeys(unit_ids))
        next_cursor = cursor + 1 if page_start + SEARCH_PAGE_SIZE < len(hit_positions) else None
        return AgentContext(
            context_id=f"{packet.packet_id}_R{round_index:02d}",
            packet_id=packet.packet_id,
            round_index=round_index,
            tool=tool,
            formula_ids=formula_ids,
            unit_ids=unique_unit_ids,
            text=text or "[NO_RESULTS]",
            source_ranges=tuple(ranges),
            query=query,
            cursor=cursor,
            total_hits=len(hit_positions),
            next_cursor=next_cursor,
        )

    def find_occurrences(
        self,
        packet: FormulaTaskPacket,
        *,
        round_index: int,
        formula_ids: tuple[str, ...],
        cursor: int,
    ) -> AgentContext:
        positions = sorted(
            {position for formula_id in formula_ids for position in self.formula_positions.get(formula_id, [])}
        )
        return self._compose_hits(
            packet,
            round_index=round_index,
            tool="find_occurrences",
            hit_positions=positions,
            formula_ids=formula_ids,
            query="",
            cursor=cursor,
        )

    def search_text(
        self,
        packet: FormulaTaskPacket,
        *,
        round_index: int,
        formula_ids: tuple[str, ...],
        query: str,
        cursor: int,
    ) -> AgentContext:
        normalized_query = _WHITESPACE_RE.sub("", query).lower()
        hits: list[tuple[int, int, int]] = []
        anchor = packet.anchor_start
        if normalized_query:
            for start, _, unit_id in self.spans:
                unit = self.unit_by_id[unit_id]
                normalized_text = _WHITESPACE_RE.sub("", unit.text).lower()
                if normalized_query in normalized_text:
                    cue_rank = 0 if _DEFINITION_CUE_RE.search(unit.text) else 1
                    hits.append((cue_rank, abs(start - anchor), start))
        positions = [item[2] for item in sorted(hits)]
        return self._compose_hits(
            packet,
            round_index=round_index,
            tool="search_text",
            hit_positions=positions,
            formula_ids=formula_ids,
            query=query,
            cursor=cursor,
        )

    def expand_context(
        self,
        packet: FormulaTaskPacket,
        current: AgentContext,
        *,
        round_index: int,
        formula_ids: tuple[str, ...],
        direction: str,
    ) -> AgentContext:
        ranges = current.source_ranges or ((packet.context_start, packet.context_end),)
        if direction == "before":
            end = min(item[0] for item in ranges) + PACKET_OVERLAP_CHARS
            start = max(0, end - CONTEXT_TARGET_CHARS)
        else:
            start = max(item[1] for item in ranges) - PACKET_OVERLAP_CHARS
            end = min(len(self.text), start + CONTEXT_TARGET_CHARS)
            start = max(0, end - CONTEXT_TARGET_CHARS)
        return self._range_context(
            packet,
            round_index=round_index,
            tool="expand_context",
            start=start,
            end=end,
            formula_ids=formula_ids,
            query=direction,
        )


def _strip_fences(value: str) -> str:
    text = (value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_agent_response(raw: str) -> dict[str, list[Any]]:
    payload = json.loads(_strip_fences(raw))
    if not isinstance(payload, dict):
        raise ValueError("Agent response must be a JSON object")
    return {
        "updates": payload.get("updates") if isinstance(payload.get("updates"), list) else [],
        "complete_formula_ids": (
            payload.get("complete_formula_ids") if isinstance(payload.get("complete_formula_ids"), list) else []
        ),
        "retrieval_requests": (
            payload.get("retrieval_requests") if isinstance(payload.get("retrieval_requests"), list) else []
        ),
    }


def build_formula_ledger(formulas: list[FormulaRecord]) -> dict[str, dict[str, Any]]:
    return {
        formula.formula_id: {
            "formula_id": formula.formula_id,
            "structure_id": formula.structure_id,
            "formula_label": formula.formula_label,
            "label_candidates": sorted({occurrence.label for occurrence in formula.occurrences if occurrence.label}),
            "markush_smiles": formula.smi,
            "structure_image": formula.structure_image,
            "occurrences": [occurrence.public_location() for occurrence in formula.occurrences],
            "formula_name_candidates": [],
            "formula_role_candidates": [],
            "object_type": "uncertain",
            "object_type_candidates": [],
            "classification_reason": None,
            "table_action": "review",
            "merge_target_formula_id": None,
            "merged_formula_ids": [],
            "definition_fragments": [],
            "evidence_unit_ids": [],
            "processed_packet_ids": [],
            "status": "pending",
        }
        for formula in formulas
    }


def _normalize_fragment(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return _WHITESPACE_RE.sub(" ", value).strip(" ;；。")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _resolved_role(entry: dict[str, Any]) -> str:
    candidates = entry["formula_role_candidates"]
    return candidates[0]["value"] if candidates else "unknown"


def _roles_are_compatible(first: dict[str, Any], second: dict[str, Any]) -> bool:
    first_role = _resolved_role(first)
    second_role = _resolved_role(second)
    return first_role == second_role or "unknown" in {first_role, second_role}


def _normalize_formula_label(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFKC", value).strip().lower()
    text = text.replace("′", "'").replace("’", "'").replace("`", "'")
    text = _WHITESPACE_RE.sub("", text)
    text = re.sub(r"^(?:通式|结构式|式|formula(?:e)?)", "", text, flags=re.IGNORECASE)
    while len(text) >= 2 and text[0] in "([{" and text[-1] in ")]}":
        text = text[1:-1].strip()
    return text.strip("：:;；,.。")


def _definition_keys(entry: dict[str, Any]) -> set[str]:
    return {
        _WHITESPACE_RE.sub("", str(fragment.get("text") or "")).lower()
        for fragment in entry["definition_fragments"]
        if fragment.get("text")
    }


def _apply_updates(
    ledger: dict[str, dict[str, Any]],
    updates: list[Any],
    *,
    allowed_formula_ids: set[str],
    allowed_unit_ids: set[str],
) -> int:
    accepted = 0
    for item in updates:
        if not isinstance(item, dict):
            continue
        formula_id = str(item.get("formula_id") or "").strip()
        if formula_id not in allowed_formula_ids or formula_id not in ledger:
            continue
        evidence_ids = [
            unit_id for unit_id in _string_list(item.get("evidence_unit_ids")) if unit_id in allowed_unit_ids
        ]
        entry = ledger[formula_id]
        entry_accepted = 0
        accepted_evidence_ids: list[str] = []
        object_type = str(item.get("object_type") or "").strip()
        classification_reason = _normalize_fragment(item.get("classification_reason"))
        if object_type in FORMULA_OBJECT_TYPES and evidence_ids:
            candidate = {
                "value": object_type,
                "reason": classification_reason or None,
                "evidence_unit_ids": evidence_ids,
            }
            if candidate not in entry["object_type_candidates"]:
                entry["object_type_candidates"].append(candidate)
                if object_type != "uncertain" or entry["object_type"] == "uncertain":
                    entry["object_type"] = object_type
                    entry["classification_reason"] = classification_reason or None
                accepted_evidence_ids.extend(evidence_ids)
                accepted += 1
                entry_accepted += 1
        formula_name = _normalize_fragment(item.get("formula_name"))
        if formula_name and evidence_ids:
            candidate = {"value": formula_name, "evidence_unit_ids": evidence_ids}
            if candidate not in entry["formula_name_candidates"]:
                entry["formula_name_candidates"].append(candidate)
                accepted_evidence_ids.extend(evidence_ids)
                accepted += 1
                entry_accepted += 1
        role = str(item.get("formula_role") or "unknown").strip()
        if role in FORMULA_ROLES and role != "unknown" and evidence_ids:
            candidate = {"value": role, "evidence_unit_ids": evidence_ids}
            if candidate not in entry["formula_role_candidates"]:
                entry["formula_role_candidates"].append(candidate)
                accepted_evidence_ids.extend(evidence_ids)
                accepted += 1
                entry_accepted += 1
        fragments = item.get("definition_fragments")
        fragment_evidence_ids: list[str] = []
        if isinstance(fragments, list):
            for fragment in fragments:
                if not isinstance(fragment, dict):
                    continue
                text = _normalize_fragment(fragment.get("text"))
                fragment_evidence = [
                    unit_id
                    for unit_id in _string_list(fragment.get("evidence_unit_ids"))
                    if unit_id in allowed_unit_ids
                ]
                if not text or not fragment_evidence:
                    continue
                normalized_key = _WHITESPACE_RE.sub("", text).lower()
                if any(
                    _WHITESPACE_RE.sub("", existing["text"]).lower() == normalized_key
                    for existing in entry["definition_fragments"]
                ):
                    continue
                entry["definition_fragments"].append({"text": text, "evidence_unit_ids": fragment_evidence})
                fragment_evidence_ids.extend(fragment_evidence)
                accepted += 1
                entry_accepted += 1
        entry["evidence_unit_ids"].extend([*accepted_evidence_ids, *fragment_evidence_ids])
        entry["evidence_unit_ids"] = list(dict.fromkeys(entry["evidence_unit_ids"]))
        if entry_accepted:
            entry["status"] = "searching"
    return accepted


def _ledger_prompt_view(ledger: dict[str, dict[str, Any]], formula_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {
            "formula_id": formula_id,
            "structure_id": ledger[formula_id]["structure_id"],
            "formula_label": ledger[formula_id]["formula_label"],
            "label_candidates": ledger[formula_id]["label_candidates"],
            "occurrence_pages": sorted({int(item["page_index"]) + 1 for item in ledger[formula_id]["occurrences"]}),
            "existing_formula_names": ledger[formula_id]["formula_name_candidates"],
            "existing_formula_roles": ledger[formula_id]["formula_role_candidates"],
            "existing_object_type": ledger[formula_id]["object_type"],
            "existing_object_type_candidates": ledger[formula_id]["object_type_candidates"],
            "existing_definition_fragments": ledger[formula_id]["definition_fragments"],
            "status": ledger[formula_id]["status"],
        }
        for formula_id in formula_ids
    ]


def build_agent_prompt(
    doc_id: str,
    packet: FormulaTaskPacket,
    context: AgentContext,
    ledger: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    payload = {
        "document": doc_id,
        "context_scope": "description",
        "packet": packet.to_dict(),
        "round": context.round_index,
        "tool_result": {
            "tool": context.tool,
            "query": context.query,
            "cursor": context.cursor,
            "total_hits": context.total_hits,
            "next_cursor": context.next_cursor,
        },
        "allowed_unit_ids": list(context.unit_ids),
        "formula_ledger": _ledger_prompt_view(ledger, packet.formula_ids),
        "context": context.text,
    }
    return FORMULA_AGENT_SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False, indent=2)


def _next_context(
    index: DescriptionContextIndex,
    packet: FormulaTaskPacket,
    current: AgentContext,
    request: dict[str, Any],
    *,
    round_index: int,
) -> AgentContext:
    tool = str(request.get("tool") or "").strip()
    requested_ids = (
        tuple(formula_id for formula_id in _string_list(request.get("formula_ids")) if formula_id in packet.formula_ids)
        or packet.formula_ids
    )
    try:
        cursor = int(request.get("cursor") or 0)
    except (TypeError, ValueError):
        cursor = 0
    cursor = min(max(cursor, 0), SEARCH_MAX_PAGES - 1)
    if tool == "find_occurrences":
        return index.find_occurrences(
            packet,
            round_index=round_index,
            formula_ids=requested_ids,
            cursor=cursor,
        )
    if tool == "search_text":
        query = str(request.get("query") or "").strip()[:120]
        return index.search_text(
            packet,
            round_index=round_index,
            formula_ids=requested_ids,
            query=query,
            cursor=cursor,
        )
    if tool == "expand_context":
        direction = "before" if str(request.get("direction") or "") == "before" else "after"
        return index.expand_context(
            packet,
            current,
            round_index=round_index,
            formula_ids=requested_ids,
            direction=direction,
        )
    raise ValueError(f"Unsupported retrieval tool: {tool or '<empty>'}")


def _context_location(unit: ContextUnit) -> dict[str, Any]:
    return {
        "kind": "context",
        "page_index": unit.page_index,
        "block_index": unit.block_index,
        "block": unit.block,
    }


def _extend_unique(target: list[Any], values: list[Any]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _merge_ledger_entry(
    ledger: dict[str, dict[str, Any]],
    *,
    source_formula_id: str,
    target_formula_id: str,
) -> None:
    source = ledger[source_formula_id]
    target = ledger[target_formula_id]
    for key in (
        "label_candidates",
        "occurrences",
        "formula_name_candidates",
        "formula_role_candidates",
        "object_type_candidates",
        "definition_fragments",
        "evidence_unit_ids",
        "processed_packet_ids",
    ):
        _extend_unique(target[key], source[key])
    _extend_unique(target["merged_formula_ids"], [source_formula_id, *source["merged_formula_ids"]])
    source["table_action"] = "merge"
    source["merge_target_formula_id"] = target_formula_id


def apply_table_decisions(
    formulas: list[FormulaRecord],
    ledger: dict[str, dict[str, Any]],
) -> None:
    """Filter object types and merge only deterministic, low-risk duplicate records."""
    for entry in ledger.values():
        object_type = entry["object_type"]
        if object_type in TABLE_OBJECT_TYPES:
            entry["table_action"] = "keep"
        elif object_type == "uncertain":
            entry["table_action"] = "review"
        else:
            entry["table_action"] = "exclude"
        entry["merge_target_formula_id"] = None

    by_structure: dict[str, list[str]] = {}
    for formula in formulas:
        if ledger[formula.formula_id]["table_action"] == "keep":
            by_structure.setdefault(formula.structure_id, []).append(formula.formula_id)

    # Equivalent non-empty labels, such as 式（I） and Formula I, are safe aliases.
    for formula_ids in by_structure.values():
        retained_by_label: dict[tuple[str, str], list[str]] = {}
        for formula_id in formula_ids:
            entry = ledger[formula_id]
            label_key = _normalize_formula_label(entry["formula_label"])
            if not label_key:
                continue
            group_key = (label_key, entry["object_type"])
            compatible_targets = [
                target_id
                for target_id in retained_by_label.get(group_key, [])
                if _roles_are_compatible(entry, ledger[target_id])
            ]
            if compatible_targets:
                _merge_ledger_entry(
                    ledger,
                    source_formula_id=formula_id,
                    target_formula_id=compatible_targets[0],
                )
            else:
                retained_by_label.setdefault(group_key, []).append(formula_id)

    # An unlabeled duplicate may join a labeled record only when the target is unique
    # and the unlabeled definitions add no new semantic scope.
    for formula_ids in by_structure.values():
        labeled_ids = [
            formula_id
            for formula_id in formula_ids
            if ledger[formula_id]["table_action"] == "keep"
            and _normalize_formula_label(ledger[formula_id]["formula_label"])
        ]
        for formula_id in formula_ids:
            entry = ledger[formula_id]
            if entry["table_action"] != "keep" or _normalize_formula_label(entry["formula_label"]):
                continue
            source_definitions = _definition_keys(entry)
            compatible_targets = [
                target_id
                for target_id in labeled_ids
                if entry["object_type"] == ledger[target_id]["object_type"]
                and _roles_are_compatible(entry, ledger[target_id])
                and source_definitions.issubset(_definition_keys(ledger[target_id]))
            ]
            if len(compatible_targets) == 1:
                _merge_ledger_entry(
                    ledger,
                    source_formula_id=formula_id,
                    target_formula_id=compatible_targets[0],
                )


def ledger_to_rows(
    doc_id: str,
    formulas: list[FormulaRecord],
    ledger: dict[str, dict[str, Any]],
    units: list[ContextUnit],
) -> list[dict[str, Any]]:
    unit_by_id = {unit.unit_id: unit for unit in units}
    unit_order = {unit.unit_id: index for index, unit in enumerate(units)}
    rows: list[dict[str, Any]] = []
    for formula in formulas:
        entry = ledger[formula.formula_id]
        if entry["table_action"] != "keep":
            continue
        names = entry["formula_name_candidates"]
        roles = entry["formula_role_candidates"]
        evidence_ids = set(entry["evidence_unit_ids"])
        for candidate in names:
            evidence_ids.update(candidate["evidence_unit_ids"])
        for candidate in roles:
            evidence_ids.update(candidate["evidence_unit_ids"])
        for fragment in entry["definition_fragments"]:
            evidence_ids.update(fragment["evidence_unit_ids"])
        ordered_evidence = sorted(evidence_ids, key=lambda item: unit_order.get(item, 10**9))
        evidence_locations = [{"kind": "formula", **occurrence} for occurrence in entry["occurrences"]]
        evidence_locations.extend(
            _context_location(unit_by_id[unit_id]) for unit_id in ordered_evidence if unit_id in unit_by_id
        )
        rows.append(
            {
                "doc_id": doc_id,
                "formula_id": formula.formula_id,
                "formula_label": formula.formula_label,
                "formula_name": names[0]["value"] if names else None,
                "formula_role": roles[0]["value"] if roles else "unknown",
                "structure_image": formula.structure_image,
                "markush_smiles": formula.smi,
                "variable_definition_text": "；".join(fragment["text"] for fragment in entry["definition_fragments"]),
                "evidence_locations": evidence_locations,
            }
        )
    return rows


def run_formula_agent(
    doc_id: str,
    formulas: list[FormulaRecord],
    units: list[ContextUnit],
    *,
    llm_config: LLMConfig | None = None,
    llm_client: OpenAICompatLLM | None = None,
    chat_fn: ChatFn | None = None,
    skip_llm: bool = False,
) -> AgentRunResult:
    index = DescriptionContextIndex(units, formulas)
    packets = index.build_packets()
    ledger = build_formula_ledger(formulas)
    contexts: list[AgentContext] = []
    errors: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    llm_call_count = 0
    resolved_client = llm_client

    def chat(system_prompt: str, user_content: str) -> str:
        nonlocal resolved_client
        if chat_fn is not None:
            return chat_fn(system_prompt, user_content)
        if resolved_client is None:
            config = llm_config or resolve_llm_config(temperature=0)
            resolved_client = OpenAICompatLLM(config=config, temperature=0)
        return resolved_client.chat(system_prompt=system_prompt, user_content=user_content)

    llm_enabled = not skip_llm and bool(formulas) and bool(packets)
    if llm_enabled:
        for packet in packets:
            for formula_id in packet.formula_ids:
                ledger[formula_id]["processed_packet_ids"].append(packet.packet_id)
                ledger[formula_id]["status"] = "searching"
            context = index.initial_context(packet)
            no_evidence_actions: set[tuple[str, str, int]] = set()
            for round_index in range(1, MAX_AGENT_ROUNDS + 1):
                contexts.append(context)
                system_prompt, user_content = build_agent_prompt(doc_id, packet, context, ledger)
                parsed: dict[str, list[Any]] | None = None
                last_error = ""
                for attempt in range(JSON_RETRY_COUNT + 1):
                    llm_call_count += 1
                    try:
                        parsed = parse_agent_response(chat(system_prompt, user_content))
                        break
                    except Exception as exc:  # noqa: BLE001 - bounded retry and packet isolation
                        last_error = str(exc)
                if parsed is None:
                    errors.append({"packet_id": packet.packet_id, "round": round_index, "error": last_error})
                    break

                accepted = _apply_updates(
                    ledger,
                    parsed["updates"],
                    allowed_formula_ids=set(packet.formula_ids),
                    allowed_unit_ids=set(context.unit_ids),
                )
                requested_complete_ids = {
                    str(item) for item in parsed["complete_formula_ids"] if str(item) in packet.formula_ids
                }
                complete_ids = {
                    formula_id
                    for formula_id in requested_complete_ids
                    if ledger[formula_id]["object_type"] != "uncertain"
                }
                for formula_id in complete_ids:
                    ledger[formula_id]["status"] = "complete"
                trace.append(
                    {
                        "packet_id": packet.packet_id,
                        "round": round_index,
                        "context_id": context.context_id,
                        "accepted_updates": accepted,
                        "complete_formula_ids": sorted(complete_ids),
                        "retrieval_request_count": len(parsed["retrieval_requests"]),
                    }
                )
                if accepted:
                    no_evidence_actions.clear()
                elif context.tool != "initial_context":
                    no_evidence_actions.add((context.tool, context.query, context.cursor))
                if all(ledger[item]["status"] == "complete" for item in packet.formula_ids):
                    break
                requests = [
                    item
                    for item in parsed["retrieval_requests"]
                    if isinstance(item, dict)
                    and item.get("tool") in {"find_occurrences", "search_text", "expand_context"}
                ]
                if not requests or len(no_evidence_actions) >= 2 or round_index >= MAX_AGENT_ROUNDS:
                    break
                context = _next_context(
                    index,
                    packet,
                    context,
                    requests[0],
                    round_index=round_index + 1,
                )

            for formula_id in packet.formula_ids:
                if ledger[formula_id]["status"] != "complete":
                    ledger[formula_id]["status"] = "insufficient"
    elif skip_llm:
        for entry in ledger.values():
            entry["status"] = "not_run"

    apply_table_decisions(formulas, ledger)
    rows = ledger_to_rows(doc_id, formulas, ledger, units)
    action_counts = {
        action: sum(item["table_action"] == action for item in ledger.values()) for action in TABLE_ACTIONS
    }
    object_type_counts = {
        object_type: sum(item["object_type"] == object_type for item in ledger.values())
        for object_type in FORMULA_OBJECT_TYPES
    }
    return AgentRunResult(
        packets=packets,
        contexts=contexts,
        ledger=ledger,
        rows=rows,
        meta={
            "uses_llm": llm_enabled,
            "llm_call_count": llm_call_count,
            "llm_errors": errors,
            "trace": trace,
            "complete_formula_count": sum(item["status"] == "complete" for item in ledger.values()),
            "insufficient_formula_count": sum(item["status"] == "insufficient" for item in ledger.values()),
            "candidate_formula_count": len(formulas),
            "output_formula_count": len(rows),
            "excluded_formula_count": action_counts["exclude"],
            "review_formula_count": action_counts["review"],
            "merged_formula_count": action_counts["merge"],
            "object_type_counts": object_type_counts,
        },
    )
