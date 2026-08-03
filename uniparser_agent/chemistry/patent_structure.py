"""Build and navigate the fixed-depth semantic tree for Chinese patents."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "2.0"
PATENT_FORMAT = "CN"
FILTER_POLICY_VERSION = "chem_patent_filter_v1"

EXCLUDED_BLOCK_TYPES = frozenset({"hline", "pagebar", "pageheader", "pagenumber", "watermark"})
EXCLUDED_BLOCK_FIELDS = frozenset({"bbox", "bboxes", "direction", "hidden", "page_size", "token"})

_PARAGRAPH_NUMBER_RE = re.compile(r"^\s*[\[【](?:\d{1,6})[\]】]\s*")
_CN_PUBLICATION_RE = re.compile(r"\bCN\s*\d{6,}\s*[A-Z]?\b", re.IGNORECASE)
_DROP = object()

_DESCRIPTION_TITLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("technical_field", ("技术领域",)),
    ("background", ("背景技术", "现有技术")),
    ("invention_summary", ("发明内容", "发明概述", "发明目的", "技术方案", "有益效果")),
    ("drawings_description", ("附图说明",)),
    ("detailed_description", ("具体实施方式", "实施方式", "具体实施例")),
)

_TOP_LEVEL_TITLES = {
    "front_matter": "首页",
    "claims": "权利要求书",
    "description": "说明书",
    "drawings": "说明书附图",
    "unknown": "未分类内容",
}

_DESCRIPTION_NODE_TITLES = {
    "technical_field": "技术领域",
    "background": "背景技术",
    "invention_summary": "发明内容",
    "drawings_description": "附图说明",
    "detailed_description": "具体实施方式",
    "description_other": "说明书其他内容",
}


def pages_tree_sha256(pages_tree_doc: dict[str, Any]) -> str:
    """Return a stable content hash used to bind a semantic tree to its source."""
    payload = json.dumps(
        pages_tree_doc,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _new_node(node_id: str, node_type: str, title: str) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "node_type": node_type,
        "title": title,
        "present": False,
        "page_start": None,
        "page_end": None,
        "block_count": 0,
        "heading_ref": None,
        "block_refs": [],
        "children": [],
    }


def _block_ref(block: dict[str, Any], page_index: int, block_index: int) -> dict[str, Any]:
    return {
        "page_index": page_index,
        "block_index": block_index,
        "block": block.get("block"),
    }


def _normalized_text(block: dict[str, Any]) -> str:
    text = block.get("text")
    return text.strip() if isinstance(text, str) else ""


def _compact_text(text: str) -> str:
    return re.sub(r"[\s:：。．、]+", "", text)


def _description_heading(block: dict[str, Any]) -> str | None:
    block_type = str(block.get("type") or "")
    if block_type not in {"title", "paragraph"}:
        return None

    text = _PARAGRAPH_NUMBER_RE.sub("", _normalized_text(block), count=1).strip()
    compact = _compact_text(text)
    if not compact:
        return None

    for node_type, aliases in _DESCRIPTION_TITLES:
        for alias in aliases:
            normalized_alias = _compact_text(alias)
            if compact == normalized_alias:
                return node_type
            if block_type == "title" and compact.startswith(normalized_alias) and len(compact) <= 80:
                return node_type
    return None


def _page_section(page: list[dict[str, Any]], page_index: int, previous: str | None) -> str:
    if page_index == 0:
        return "front_matter"

    header_texts = [
        _compact_text(_normalized_text(block)) for block in page if str(block.get("type") or "") == "pageheader"
    ]
    if any("说明书附图" in text for text in header_texts):
        return "drawings"
    if any("权利要求书" in text for text in header_texts):
        return "claims"
    if any(text == "说明书" for text in header_texts):
        return "description"

    title_texts = {_compact_text(_normalized_text(block)) for block in page if str(block.get("type") or "") == "title"}
    if "权利要求书" in title_texts:
        return "claims"
    if "说明书附图" in title_texts:
        return "drawings"
    if "说明书" in title_texts:
        return "description"
    return previous or "unknown"


def _top_level_heading(block: dict[str, Any], section_type: str) -> bool:
    if str(block.get("type") or "") not in {"pageheader", "title"}:
        return False
    text = _compact_text(_normalized_text(block))
    if section_type == "claims":
        return "权利要求书" in text
    if section_type == "description":
        return text == "说明书"
    if section_type == "drawings":
        return "说明书附图" in text
    return False


def _append_ref(node: dict[str, Any], ref: dict[str, Any]) -> None:
    node["block_refs"].append(ref)
    node["present"] = True


def _node_pages(node: dict[str, Any]) -> list[int]:
    pages = [int(ref["page_index"]) + 1 for ref in node["block_refs"]]
    for child in node["children"]:
        if child["page_start"] is not None:
            pages.append(int(child["page_start"]))
        if child["page_end"] is not None:
            pages.append(int(child["page_end"]))
    return pages


def _finalize_node(node: dict[str, Any]) -> None:
    for child in node["children"]:
        _finalize_node(child)
    pages = _node_pages(node)
    if pages:
        node["present"] = True
        node["page_start"] = min(pages)
        node["page_end"] = max(pages)
    node["block_count"] = len(node["block_refs"]) + sum(child["block_count"] for child in node["children"])


def build_patent_structure(pages_tree_doc: dict[str, Any], doc_id: str) -> dict[str, Any]:
    """Build a CN patent chapter index without copying parsed block content."""
    pages = pages_tree_doc.get("pages_tree")
    if not isinstance(pages, list):
        raise ValueError("Invalid pages_tree document: pages_tree must be a list")
    if any(not isinstance(page, list) for page in pages):
        raise ValueError("Invalid pages_tree document: each page must be a list")

    top_nodes = {node_type: _new_node(node_type, node_type, title) for node_type, title in _TOP_LEVEL_TITLES.items()}
    description_nodes = {
        node_type: _new_node(f"description.{node_type}", node_type, title)
        for node_type, title in _DESCRIPTION_NODE_TITLES.items()
    }
    top_nodes["description"]["children"] = list(description_nodes.values())

    page_map: list[dict[str, Any]] = []
    warnings: list[str] = []
    current_page_section: str | None = None
    current_description_section = "description_other"

    for page_index, raw_page in enumerate(pages):
        page = [block for block in raw_page if isinstance(block, dict)]
        if len(page) != len(raw_page):
            warnings.append(f"non_object_block_on_page:{page_index}")
        current_page_section = _page_section(page, page_index, current_page_section)
        page_map.append(
            {
                "page_index": page_index,
                "physical_page": page_index + 1,
                "node_type": current_page_section,
            }
        )
        top_node = top_nodes[current_page_section]

        for block_index, raw_block in enumerate(raw_page):
            if not isinstance(raw_block, dict):
                continue
            ref = _block_ref(raw_block, page_index, block_index)

            if current_page_section == "description":
                heading = _description_heading(raw_block)
                if heading is not None:
                    current_description_section = heading
                child = description_nodes[current_description_section]
                _append_ref(child, ref)
                if heading is not None and child["heading_ref"] is None:
                    child["heading_ref"] = ref
                if top_node["heading_ref"] is None and _top_level_heading(raw_block, "description"):
                    top_node["heading_ref"] = ref
                continue

            _append_ref(top_node, ref)
            if top_node["heading_ref"] is None and _top_level_heading(raw_block, current_page_section):
                top_node["heading_ref"] = ref

    for node in top_nodes.values():
        _finalize_node(node)

    searchable_text = " ".join(
        str(value) for value in (doc_id, pages_tree_doc.get("filename", ""), pages_tree_doc.get("description", ""))
    )
    if not _CN_PUBLICATION_RE.search(searchable_text):
        page_text = " ".join(_normalized_text(block) for page in pages[:2] for block in page if isinstance(block, dict))
        if not _CN_PUBLICATION_RE.search(page_text):
            warnings.append("cn_publication_number_not_detected")
    if not top_nodes["claims"]["present"]:
        warnings.append("claims_not_detected")
    if not top_nodes["description"]["present"]:
        warnings.append("description_not_detected")
    if top_nodes["unknown"]["block_count"]:
        warnings.append("unclassified_content_present")

    root = _new_node("patent", "patent", "专利")
    root["present"] = bool(pages)
    root["page_start"] = 1 if pages else None
    root["page_end"] = len(pages) if pages else None
    root["children"] = [top_nodes[node_type] for node_type in _TOP_LEVEL_TITLES]
    root["block_count"] = sum(node["block_count"] for node in root["children"])

    return {
        "schema_version": SCHEMA_VERSION,
        "doc_id": doc_id,
        "patent_format": PATENT_FORMAT,
        "format_profile": "cn_patent_semantic_index_v2",
        "source": {
            "filename": pages_tree_doc.get("filename", ""),
            "token": pages_tree_doc.get("token", ""),
            "sha256": pages_tree_sha256(pages_tree_doc),
            "page_count": len(pages),
        },
        "resolver_policy": {
            "version": FILTER_POLICY_VERSION,
            "excluded_block_types": sorted(EXCLUDED_BLOCK_TYPES),
            "excluded_fields": sorted(EXCLUDED_BLOCK_FIELDS),
        },
        "page_map": page_map,
        "tree": root,
        "warnings": warnings,
    }


def _normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        block_type = str(value.get("type") or "")
        if block_type in EXCLUDED_BLOCK_TYPES:
            return _DROP
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if key in EXCLUDED_BLOCK_FIELDS:
                continue
            normalized_item = _normalize_value(item)
            if normalized_item is not _DROP:
                normalized[key] = normalized_item
        return normalized
    if isinstance(value, list):
        normalized_list = []
        for item in value:
            normalized_item = _normalize_value(item)
            if normalized_item is not _DROP:
                normalized_list.append(normalized_item)
        return normalized_list
    return value


class BlockResolver:
    """Resolve semantic nodes to filtered copies of their original top-level blocks."""

    def __init__(self, pages_tree_doc: dict[str, Any], patent_structure: dict[str, Any]) -> None:
        pages = pages_tree_doc.get("pages_tree")
        if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
            raise ValueError("Invalid pages_tree document")
        source = patent_structure.get("source")
        if not isinstance(source, dict) or source.get("sha256") != pages_tree_sha256(pages_tree_doc):
            raise ValueError("Semantic tree does not match pages_tree source")

        self._pages = pages
        self._nodes: dict[str, dict[str, Any]] = {}
        tree = patent_structure.get("tree")
        if not isinstance(tree, dict):
            raise ValueError("Invalid semantic tree")
        self._index_node(tree)

    def _index_node(self, node: dict[str, Any]) -> None:
        node_id = node.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            raise ValueError("Semantic tree node is missing node_id")
        if node_id in self._nodes:
            raise ValueError(f"Duplicate semantic tree node_id: {node_id}")
        self._nodes[node_id] = node
        for child in node.get("children", []):
            if not isinstance(child, dict):
                raise ValueError(f"Invalid child node under {node_id}")
            self._index_node(child)

    def _collect_refs(self, node: dict[str, Any]) -> list[dict[str, Any]]:
        refs = [ref for ref in node.get("block_refs", []) if isinstance(ref, dict)]
        for child in node.get("children", []):
            refs.extend(self._collect_refs(child))
        refs.sort(key=lambda ref: (int(ref["page_index"]), int(ref["block_index"])))
        unique_refs: list[dict[str, Any]] = []
        seen: set[tuple[int, int]] = set()
        for ref in refs:
            key = int(ref["page_index"]), int(ref["block_index"])
            if key not in seen:
                seen.add(key)
                unique_refs.append(ref)
        return unique_refs

    def resolve(self, node_id: str) -> list[dict[str, Any]]:
        """Return filtered blocks for a node in original pages_tree array order."""
        try:
            node = self._nodes[node_id]
        except KeyError as exc:
            raise KeyError(f"Unknown semantic tree node: {node_id}") from exc

        blocks: list[dict[str, Any]] = []
        for ref in self._collect_refs(node):
            page_index = int(ref["page_index"])
            block_index = int(ref["block_index"])
            try:
                block = self._pages[page_index][block_index]
            except IndexError as exc:
                raise ValueError(f"Invalid block location: ({page_index}, {block_index})") from exc
            if not isinstance(block, dict):
                raise ValueError(f"Referenced block is not an object: ({page_index}, {block_index})")
            expected_block = ref.get("block")
            if expected_block is not None and block.get("block") != expected_block:
                raise ValueError(f"Block validation failed at ({page_index}, {block_index})")
            normalized = _normalize_value(block)
            if normalized is not _DROP:
                blocks.append(normalized)
        return blocks


def write_patent_structure(
    pages_tree_doc: dict[str, Any],
    doc_id: str,
    output_path: str | Path,
) -> Path:
    """Build and write patent_structure.json."""
    return write_patent_structure_payload(build_patent_structure(pages_tree_doc, doc_id), output_path)


def write_patent_structure_payload(
    patent_structure: dict[str, Any],
    output_path: str | Path,
) -> Path:
    """Write an already-built patent structure without rebuilding its page partition."""
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(patent_structure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
