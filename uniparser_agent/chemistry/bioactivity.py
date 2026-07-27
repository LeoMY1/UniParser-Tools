"""LLM-first, table-scoped bioactivity extraction."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from uniparser_agent.chemistry.join import LogicalCompound
from uniparser_agent.chemistry.patent_chunks import build_patent_chunks
from uniparser_agent.chemistry.tables import normalize_label
from uniparser_agent.chemistry.text_units import TextUnit, build_text_units


ChatFn = Callable[[str, str], str]
TABLE_PART_CHAR_BUDGET = 12_000

READOUT_TYPES = {
    "IC50",
    "EC50",
    "Ki",
    "Kd",
    "%inhibition",
    "GI50",
    "CC50",
    "MIC",
    "DC50",
    "Dmax",
    "kinact",
    "KI",
    "kinact/KI",
    "Kobs",
    "residence_time",
    "aggregation",
    "cell_viability",
    "synergy",
    "other",
}

BIOACTIVITY_SYSTEM_PROMPT = """You extract experimental bioactivity readouts from
ONE chemistry-patent table represented as text.
Return STRICT JSON only:
{
  "table_has_assay_data": true,
  "table_caption": "verbatim caption or empty",
  "source_table_id": "input id",
  "readouts": [
    {
      "compound_label": "raw row label",
      "assay_name": "verbatim assay/column name",
      "target": "protein/biological target or null",
      "readout_type": "IC50|EC50|Ki|Kd|%inhibition|GI50|CC50|MIC|DC50|Dmax|kinact|KI|kinact/KI|Kobs|residence_time|aggregation|cell_viability|synergy|other",
      "value": "number, qualitative string, or null",
      "unit": "verbatim unit or null",
      "concentration": "fixed test concentration or null",
      "conditions": "inequality, SD/SEM, treatment, dose, time, footnote, or null",
      "assay_type": "enzymatic|cell-based|binding|functional|null",
      "cell_line": "cell line or null",
      "assay_format": "technology such as MTT/HTRF or null",
      "source_row": 3,
      "evidence": "verbatim source row"
    }
  ]
}
Rules:
- Emit one readout per (compound row, experimental assay column) pair. Read every row and every assay column.
- Preserve raw compound labels and include control/reference compounds.
- Use caption, section context, headers and footnotes to identify target, cell line, format and conditions.
- Use aggregation for a measured platelet aggregation/rate column and %inhibition only for an inhibition column. Likewise use cell_viability for measured viability/survival and synergy only for a synergy endpoint.
- For >10 or <0.1 use numeric value and put the inequality in conditions.
- Preserve mean ± SD/SEM in conditions/evidence. Blank, ND, n.d. and '-' use value=null.
- A synthesis-yield, identity, calculated-property or non-assay table must return table_has_assay_data=false and readouts=[].
- Exclude FEP, docking, MM-GBSA, QSAR, ML-predicted or other computational values.
- Never infer a numeric value from structure or prose. source_row and evidence must point to the supplied table.
"""


@dataclass(frozen=True)
class ActivityTableInput:
    source_table_id: str
    page: int
    block: int
    section_type: str
    section_title: str
    context: str
    rows: tuple[str, ...]
    row_numbers: tuple[int, ...]
    part: int = 1


def _strip_fences(text: str) -> str:
    value = (text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    return value.strip()


def parse_bioactivity_response(raw: str) -> dict[str, Any]:
    data = json.loads(_strip_fences(raw))
    if not isinstance(data, dict):
        raise ValueError("BioActivity response must be an object")
    if not isinstance(data.get("table_has_assay_data"), bool):
        raise ValueError("table_has_assay_data must be boolean")
    readouts = data.get("readouts")
    if not isinstance(readouts, list):
        raise ValueError("readouts must be a list")
    data["readouts"] = [item for item in readouts if isinstance(item, dict)]
    return data


def _table_context(chunk_units: list[TextUnit], table_order: int) -> str:
    nearby = [
        unit.text
        for unit in chunk_units
        if unit.type != "table" and abs(unit.order - table_order) <= 5
    ]
    return "\n".join(nearby)[-3_000:]


def build_activity_table_inputs(
    pages_tree_doc: dict[str, Any],
    *,
    max_chars: int = TABLE_PART_CHAR_BUDGET,
) -> list[ActivityTableInput]:
    units = build_text_units(pages_tree_doc)
    chunks = build_patent_chunks(units)
    chunk_for_unit = {
        unit.unit_id: chunk
        for chunk in chunks
        for unit in chunk.units
    }
    out: list[ActivityTableInput] = []
    for unit in units:
        if unit.type != "table":
            continue
        chunk = chunk_for_unit.get(unit.unit_id)
        rows = tuple(line for line in unit.text.splitlines() if line.strip())
        if not rows:
            continue
        context = _table_context(chunk.units if chunk else [], unit.order)
        section_type = chunk.section_type if chunk else "table"
        section_title = chunk.section_title if chunk else ""
        base_cost = len(context) + len(section_title) + 500
        row_budget = max(1_000, max_chars - base_cost)
        current: list[str] = []
        current_numbers: list[int] = []
        size = 0
        parts: list[tuple[tuple[str, ...], tuple[int, ...]]] = []
        for row_number, row in enumerate(rows):
            cost = len(row) + 16
            if current and size + cost > row_budget:
                parts.append((tuple(current), tuple(current_numbers)))
                current = []
                current_numbers = []
                size = 0
            current.append(row)
            current_numbers.append(row_number)
            size += cost
        if current:
            parts.append((tuple(current), tuple(current_numbers)))
        # Repeat up to two header rows for split tables.
        headers = rows[: min(2, len(rows))]
        header_numbers = tuple(range(len(headers)))
        for part_index, (part_rows, part_numbers) in enumerate(parts, start=1):
            if part_index > 1:
                combined = dict(zip((*headers, *part_rows), (*header_numbers, *part_numbers)))
                part_rows = tuple(combined)
                part_numbers = tuple(combined.values())
            out.append(
                ActivityTableInput(
                    source_table_id=unit.unit_id,
                    page=unit.page,
                    block=unit.block,
                    section_type=section_type,
                    section_title=section_title,
                    context=context,
                    rows=part_rows,
                    row_numbers=part_numbers,
                    part=part_index,
                )
            )
    return out


def build_bioactivity_prompt(table: ActivityTableInput) -> tuple[str, str]:
    numbered_rows = [
        {"source_row": index, "text": text}
        for index, text in zip(table.row_numbers, table.rows)
    ]
    payload = {
        "activity_table": {
            "source_table_id": table.source_table_id,
            "part": table.part,
            "page": table.page,
            "block": table.block,
            "section_type": table.section_type,
            "section_title": table.section_title,
            "context": table.context,
            "rows": numbered_rows,
        }
    }
    return BIOACTIVITY_SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False, indent=2)


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "").replace("−", "-")


def _validated_readouts(
    data: dict[str, Any],
    table: ActivityTableInput,
) -> list[dict[str, Any]]:
    if not data.get("table_has_assay_data"):
        return []
    rows = dict(zip(table.row_numbers, table.rows))
    out: list[dict[str, Any]] = []
    for item in data.get("readouts") or []:
        label = str(item.get("compound_label") or "").strip()
        readout_type = str(item.get("readout_type") or "other").strip()
        if not label:
            continue
        if readout_type not in READOUT_TYPES:
            readout_type = "other"
        try:
            row_index = int(item.get("source_row"))
        except (TypeError, ValueError):
            continue
        if row_index not in rows:
            continue
        row = rows[row_index]
        evidence = str(item.get("evidence") or row).strip()
        if _normalized_text(evidence) not in _normalized_text(row):
            evidence = row
        value = item.get("value")
        if value is not None:
            value_text = _normalized_text(str(value))
            if value_text and value_text not in _normalized_text(row):
                # Qualitative aliases are accepted only when literally present.
                continue
        out.append(
            {
                "compound_label": label,
                "assay_name": str(item.get("assay_name") or "").strip(),
                "target": item.get("target"),
                "readout_type": readout_type,
                "value": value,
                "unit": item.get("unit"),
                "concentration": item.get("concentration"),
                "conditions": item.get("conditions"),
                "assay_type": item.get("assay_type"),
                "cell_line": item.get("cell_line"),
                "assay_format": item.get("assay_format"),
                "source_table_id": table.source_table_id,
                "source_row": row_index,
                "page": table.page,
                "evidence": evidence,
                "raw": row,
            }
        )
    return out


def extract_bioactivity_via_llm(
    pages_tree_doc: dict[str, Any],
    *,
    chat_fn: ChatFn,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for table in build_activity_table_inputs(pages_tree_doc):
        system_prompt, user_content = build_bioactivity_prompt(table)
        parsed: dict[str, Any] | None = None
        for _attempt in range(2):
            try:
                parsed = parse_bioactivity_response(chat_fn(system_prompt, user_content))
                break
            except Exception:  # noqa: BLE001 - a malformed table response is retried
                parsed = None
        if not parsed:
            continue
        for record in _validated_readouts(parsed, table):
            key = (
                record["source_table_id"],
                record["compound_label"],
                record["assay_name"],
                str(record.get("concentration") or ""),
                str(record.get("conditions") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            records.append(record)
    return records


def _record_to_activity_json(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "activity_type": record.get("readout_type") or "other",
        "activity_value": record.get("value"),
        "activity_value_sd": None,
        "activity_unit": record.get("unit") or "",
        "assay": record.get("assay_name") or "",
        "target": record.get("target"),
        "concentration": record.get("concentration"),
        "condition": record.get("conditions"),
        "assay_type": record.get("assay_type"),
        "cell_line": record.get("cell_line"),
        "assay_format": record.get("assay_format"),
        "source_table_id": record.get("source_table_id"),
        "source_row": record.get("source_row"),
        "evidence": record.get("evidence") or "",
    }


def attach_bioactivity_records(
    compounds: list[LogicalCompound],
    records: list[dict[str, Any]],
) -> list[LogicalCompound]:
    by_key = {
        key: compound
        for compound in compounds
        for key in {compound.compound_id, compound.label}
        if key
    }
    for record in records:
        raw_label = str(record.get("compound_label") or "").strip()
        normalized = normalize_label(raw_label)
        target = by_key.get(normalized) or by_key.get(raw_label)
        example_match = re.search(r"(?:实施例|example)\s*(\d+)", raw_label, re.IGNORECASE)
        if not target and example_match:
            target = by_key.get(f"I-{example_match.group(1)}")
        if not target and normalized.isdigit():
            target = by_key.get(f"I-{normalized}")
        if not target:
            role = "reference" if re.search(
                r"control|reference|对照|阳性|阴性",
                raw_label,
                re.IGNORECASE,
            ) else "unknown"
            target = LogicalCompound(
                compound_id=normalized or raw_label,
                label=normalized or raw_label,
                smi="",
                role=role,
                source_type="activity_table",
            )
            compounds.append(target)
            by_key[target.compound_id] = target
            by_key[target.label] = target
        if record not in target.activity_rows:
            target.activity_rows.append(record)
        activity = _record_to_activity_json(record)
        if activity not in target.activities_json:
            target.activities_json.append(activity)
        page = int(record.get("page") or 0)
        if page and page not in target.pages:
            target.pages.append(page)
    return compounds
