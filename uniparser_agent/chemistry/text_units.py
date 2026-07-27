"""Build ordered non-image text units from UniParser pages_tree."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from uniparser_agent.chemistry.tables import parse_html_table, walk_blocks


@dataclass(frozen=True)
class TextUnit:
    unit_id: str
    page: int
    block: int
    type: str
    text: str
    order: int = 0


_TEXT_TYPES = frozenset(
    {
        "paragraph",
        "title",
        "documenttitle",
        "keyvalue",
        "tablecaption",
        "imagecaption",
        "moleculeid",
    }
)

_LAYOUT_NOISE_TYPES = frozenset(
    {"pageheader", "pagefooter", "pagebar", "pagenumber", "watermark", "hline"}
)


def _is_image_like(block: dict[str, Any]) -> bool:
    if block.get("type") == "image":
        return True
    source = block.get("source")
    if isinstance(source, str) and len(source) > 200 and not (block.get("text") or "").strip():
        # Likely base64 / binary payload with no readable text
        return True
    return False


def table_structure_to_text(structure: str) -> str:
    rows = parse_html_table(structure)
    lines = ["\t".join(cell for cell in row) for row in rows if any(cell.strip() for cell in row)]
    return "\n".join(lines).strip()


def _molecule_short_text(block: dict[str, Any], *, label: str = "") -> str:
    smi = (block.get("smi") or "").strip()
    caption = (block.get("caption") or "").strip()
    parts: list[str] = []
    if label:
        parts.append(f"label={label}")
    if smi:
        parts.append(f"smi={smi}")
    elif caption:
        parts.append(f"caption={caption[:200]}")
    return "; ".join(parts)


def _moleculegroup_text(block: dict[str, Any]) -> str:
    label = ""
    smi = ""
    caption = ""
    for nb in walk_blocks(block.get("items") or []):
        if nb.get("type") == "moleculeid":
            label = (nb.get("text") or "").strip() or label
        if nb.get("type") == "molecule" or nb.get("smi"):
            smi = (nb.get("smi") or "").strip() or smi
            caption = (nb.get("caption") or "").strip() or caption
    return _molecule_short_text({"smi": smi, "caption": caption}, label=label)


def _block_text(block: dict[str, Any]) -> str:
    for key in ("text", "content"):
        val = block.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _make_unit(
    block: dict[str, Any],
    typ: str,
    text: str,
    *,
    order: int,
) -> TextUnit | None:
    text = (text or "").strip()
    if not text:
        return None
    page = int(block.get("page", 0) or 0)
    block_no = int(block.get("block", 0) or 0)
    unit_id = f"p{page}_b{block_no}"
    return TextUnit(
        unit_id=unit_id,
        page=page,
        block=block_no,
        type=typ,
        text=text,
        order=order,
    )


def _emit_blocks(blocks: list[Any] | None, out: list[TextUnit], seen_ids: set[str]) -> None:
    for block in blocks or []:
        if not isinstance(block, dict):
            continue

        typ = str(block.get("type") or "")
        if typ in _LAYOUT_NOISE_TYPES:
            continue

        # Skip emitting image binaries, but still walk nested text/molecule children.
        if _is_image_like(block):
            items = block.get("items")
            if isinstance(items, list) and items:
                _emit_blocks(items, out, seen_ids)
            continue

        if typ == "figuregroup":
            _emit_blocks(block.get("items") or [], out, seen_ids)
            continue

        if typ == "moleculegroup":
            unit = _make_unit(
                block,
                "moleculegroup",
                _moleculegroup_text(block),
                order=len(out),
            )
            if unit and unit.unit_id not in seen_ids:
                seen_ids.add(unit.unit_id)
                out.append(unit)
            continue

        if typ == "molecule":
            unit = _make_unit(
                block,
                "molecule",
                _molecule_short_text(block),
                order=len(out),
            )
            if unit and unit.unit_id not in seen_ids:
                seen_ids.add(unit.unit_id)
                out.append(unit)
            continue

        if typ == "table":
            struct = block.get("structure") or ""
            text = table_structure_to_text(struct) if isinstance(struct, str) else ""
            unit = _make_unit(block, "table", text, order=len(out))
            if unit and unit.unit_id not in seen_ids:
                seen_ids.add(unit.unit_id)
                out.append(unit)
            continue

        if typ in _TEXT_TYPES or _block_text(block):
            text = _block_text(block)
            unit = _make_unit(block, typ or "text", text, order=len(out))
            if unit and unit.unit_id not in seen_ids:
                seen_ids.add(unit.unit_id)
                out.append(unit)
            # Leaf-like text nodes: do not also recurse for a duplicate unit
            if typ in _TEXT_TYPES or typ in ("table", "molecule", "moleculegroup"):
                continue

        items = block.get("items")
        if isinstance(items, list) and items:
            _emit_blocks(items, out, seen_ids)


def build_text_units(pages_tree_doc: dict[str, Any]) -> list[TextUnit]:
    """Linear non-image text units from ``pages_tree`` (one block → one unit)."""
    pages = pages_tree_doc.get("pages_tree") or []
    out: list[TextUnit] = []
    seen_ids: set[str] = set()
    for page in pages:
        page_blocks = page if isinstance(page, list) else [page]
        _emit_blocks(page_blocks, out, seen_ids)
    # Preserve the parser's reading order. ``block`` is an opaque identifier in
    # real pages trees and is not guaranteed to increase with reading order.
    return out
