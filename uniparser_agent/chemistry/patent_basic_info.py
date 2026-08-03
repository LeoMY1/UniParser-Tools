"""Rule-only extraction of the first-page basic information table for CN patents."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from uniparser_agent.chemistry.patent_structure import BlockResolver


SCHEMA_VERSION = "1.0"
TABLE_NAME = "patent_basic_info"

TABLE_COLUMNS = (
    "doc_id",
    "document_number",
    "kind_code",
    "document_type",
    "document_status",
    "title",
    "application_number",
    "application_date",
    "publication_date",
    "application_publication_number",
    "application_publication_date",
    "authorization_announcement_date",
    "holder_role",
    "applicants_or_patentees",
    "addresses",
    "inventors",
    "ipc_codes",
    "priority_claims",
    "agency",
    "agency_code",
    "agents",
    "abstract",
)

_TEXT_BLOCK_TYPES = frozenset({"documenttitle", "keyvalue", "paragraph", "text", "title"})
_INID_RE = re.compile(r"^\s*[（(]\s*(\d{2})\s*[)）]\s*")
_CN_DOCUMENT_RE = re.compile(r"\bCN\s*(\d{6,})\s*([A-Z]\d?)\b", re.IGNORECASE)
_APPLICATION_NUMBER_RE = re.compile(r"(?<!\d)(\d{8,14}(?:\.[0-9X])?)(?!\d)", re.IGNORECASE)
_DATE_RE = re.compile(r"(?<!\d)(\d{4})[.\-/年](\d{1,2})[.\-/月](\d{1,2})日?(?!\d)")
_IPC_RE = re.compile(r"(?<![A-Z0-9])([A-HY]\s*\d{2}\s*[A-Z]\s*\d{1,4}\s*/\s*\d{1,6})", re.IGNORECASE)


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    lines = [re.sub(r"[ \t\u3000]+", " ", line).strip() for line in value.replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line)


def _strip_label(text: str, *labels: str) -> str:
    value = text.strip()
    for label in labels:
        match = re.match(rf"^\s*{re.escape(label)}\s*[:：]?\s*", value)
        if match:
            return value[match.end() :].strip()
    return value


def _first_group(groups: dict[str, list[str]], code: str) -> str:
    values = groups.get(code, [])
    return "\n".join(value for value in values if value).strip()


def _group_blocks_by_inid(blocks: list[dict[str, Any]]) -> tuple[dict[str, list[str]], list[str]]:
    groups: dict[str, list[str]] = {}
    warnings = [] if blocks else ["front_matter_empty"]
    current_code: str | None = None
    for block in blocks:
        block_type = str(block.get("type") or "")
        text = _normalize_text(block.get("text"))
        if block_type not in _TEXT_BLOCK_TYPES or not text:
            if block_type in {"hline", "image", "molecule", "moleculegroup"}:
                current_code = None
            continue

        match = _INID_RE.match(text)
        if match:
            current_code = match.group(1)
            groups.setdefault(current_code, []).append(text[match.end() :].strip())
        elif current_code is not None:
            groups[current_code].append(text)
    return groups, warnings


def _extract_document_number(text: str) -> tuple[str | None, str | None]:
    match = _CN_DOCUMENT_RE.search(text)
    if not match:
        return None, None
    return f"CN{match.group(1)}{match.group(2).upper()}", match.group(2).upper()


def _extract_application_number(text: str) -> str | None:
    match = _APPLICATION_NUMBER_RE.search(text)
    return match.group(1) if match else None


def _extract_date(text: str) -> str | None:
    match = _DATE_RE.search(text)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _split_values(text: str, *, whitespace: bool = False) -> list[str]:
    separator = r"[\s,，、;；]+" if whitespace else r"[、;；]+"
    return [part.strip(" ,，") for part in re.split(separator, text) if part.strip(" ,，")]


def _extract_holders(text: str) -> tuple[str | None, list[str], list[str]]:
    role = None
    if re.match(r"^\s*申请人", text):
        role = "申请人"
    elif re.match(r"^\s*专利权人", text):
        role = "专利权人"

    body = _strip_label(text, "申请人", "专利权人")
    address_parts = re.split(r"(?:^|\n)\s*地址\s*[:：]?\s*", body)
    holder_text = address_parts[0].strip()
    addresses = [re.sub(r"\s+", " ", value).strip() for value in address_parts[1:] if value.strip()]
    return role, _split_values(holder_text), addresses


def _extract_agency(text: str) -> tuple[str | None, str | None, list[str]]:
    body = _strip_label(text, "专利代理机构")
    parts = re.split(r"(?:^|\n)\s*(?:专利代理师|代理人)\s*[:：]?\s*", body, maxsplit=1)
    agency_with_code = re.sub(r"\s+", " ", parts[0]).strip()
    agents = _split_values(parts[1], whitespace=True) if len(parts) > 1 else []
    code_match = re.search(r"(?<!\d)(\d{5})\s*$", agency_with_code)
    agency_code = code_match.group(1) if code_match else None
    agency = agency_with_code
    if code_match:
        agency = f"{agency_with_code[: code_match.start()]} {agency_with_code[code_match.end() :]}".strip()
    return agency or None, agency_code, agents


def _extract_ipc_codes(text: str) -> list[str]:
    codes: list[str] = []
    seen: set[str] = set()
    for match in _IPC_RE.finditer(text):
        code = re.sub(r"\s+", "", match.group(1).upper())
        code = re.sub(r"^([A-HY]\d{2}[A-Z])(\d+)", r"\1 \2", code)
        if code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def _extract_priority_claims(text: str) -> list[str]:
    body = _strip_label(text, "优先权", "优先权数据")
    return [part.strip() for part in re.split(r"[\n;；]+", body) if part.strip()]


def extract_patent_basic_info(resolver: BlockResolver, doc_id: str) -> tuple[dict[str, Any], list[str]]:
    """Extract one CN patent row from the semantic tree's front-matter node."""
    groups, warnings = _group_blocks_by_inid(resolver.resolve("front_matter"))

    document_text = _first_group(groups, "10") or _first_group(groups, "11")
    document_number, kind_code = _extract_document_number(document_text)
    if "授权公告号" in document_text:
        document_status = "授权公告"
    elif "申请公布号" in document_text:
        document_status = "申请公布"
    else:
        document_status = None

    application_publication_text = _first_group(groups, "65")
    application_publication_number, _ = _extract_document_number(application_publication_text)
    if application_publication_number is None and document_status == "申请公布":
        application_publication_number = document_number
    application_publication_date = _extract_date(_first_group(groups, "43"))
    authorization_announcement_date = _extract_date(_first_group(groups, "45"))
    publication_date = authorization_announcement_date or application_publication_date

    holder_text = _first_group(groups, "71") or _first_group(groups, "73")
    holder_role, holders, addresses = _extract_holders(holder_text)
    agency, agency_code, agents = _extract_agency(_first_group(groups, "74"))

    title = _strip_label(_first_group(groups, "54"), "发明名称") or None
    abstract = _strip_label(_first_group(groups, "57"), "摘要") or None
    row = {
        "doc_id": doc_id,
        "document_number": document_number,
        "kind_code": kind_code,
        "document_type": _strip_label(_first_group(groups, "12"), "文献种类") or None,
        "document_status": document_status,
        "title": re.sub(r"\s*\n\s*", "", title) if title else None,
        "application_number": _extract_application_number(_first_group(groups, "21")),
        "application_date": _extract_date(_first_group(groups, "22")),
        "publication_date": publication_date,
        "application_publication_number": application_publication_number,
        "application_publication_date": application_publication_date,
        "authorization_announcement_date": authorization_announcement_date,
        "holder_role": holder_role,
        "applicants_or_patentees": holders,
        "addresses": addresses,
        "inventors": _split_values(_strip_label(_first_group(groups, "72"), "发明人"), whitespace=True),
        "ipc_codes": _extract_ipc_codes(_first_group(groups, "51")),
        "priority_claims": _extract_priority_claims(_first_group(groups, "30")),
        "agency": agency,
        "agency_code": agency_code,
        "agents": agents,
        "abstract": re.sub(r"\s*\n\s*", "", abstract) if abstract else None,
    }

    for field in ("document_number", "title", "application_number"):
        if row[field] is None:
            warnings.append(f"{field}_not_detected_in_front_matter")
    return row, warnings


def build_patent_basic_info_table(resolver: BlockResolver, doc_id: str) -> dict[str, Any]:
    """Build one row from the semantic tree's front-matter navigation node."""
    row, warnings = extract_patent_basic_info(resolver, doc_id)
    return {
        "schema_version": SCHEMA_VERSION,
        "table_name": TABLE_NAME,
        "patent_format": "CN",
        "extraction_scope": {
            "navigation_node": "front_matter",
            "partition_source": "patent_structure",
            "method": "rule_only",
            "uses_llm": False,
        },
        "columns": list(TABLE_COLUMNS),
        "rows": [row],
        "warnings": warnings,
    }


def write_patent_basic_info(
    resolver: BlockResolver,
    doc_id: str,
    output_path: str | Path,
) -> Path:
    """Write the front-matter basic information table as JSON."""
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_patent_basic_info_table(resolver, doc_id)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
