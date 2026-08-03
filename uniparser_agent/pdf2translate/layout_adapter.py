"""Adapt UniParser pages_tree into TranslateUnit list with PDF coordinates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from uniparser_agent.pdf2translate.models import (
    SKIP_TYPES,
    TRANSLATABLE_TYPES,
    BBox,
    TranslateUnit,
)


def _iter_blocks(pages_tree: list[Any]) -> list[dict[str, Any]]:
    """Flatten pages and nested groups in reading order."""
    flat: list[dict[str, Any]] = []

    def _walk(blocks: list[Any]) -> None:
        ordered = sorted(
            [block for block in blocks if isinstance(block, dict)],
            key=lambda block: block.get("order") if block.get("order") is not None else 10**9,
        )
        for block in ordered:
            flat.append(block)
            items = block.get("items")
            if isinstance(items, list) and items:
                _walk(items)

    for page in pages_tree:
        if not isinstance(page, list):
            continue
        _walk(page)
    return flat


def _format_inline(content: str, content_type: str) -> str:
    normalized_type = content_type.strip().lower()
    if normalized_type in {"equation", "equationinline"}:
        if content.startswith(("$", r"\(", r"\[")):
            return content
        return f"${content}$"
    if normalized_type == "molecule":
        return content if content.startswith("`") else f"`{content}`"
    return content


def _inline_contents(block: dict[str, Any]) -> str:
    contents = block.get("contents")
    if not isinstance(contents, list) or not contents:
        return ""
    types = block.get("types")
    if not isinstance(types, list) or len(types) != len(contents):
        types = ["text"] * len(contents)
    return "".join(_format_inline(str(content), str(content_type)) for content, content_type in zip(contents, types))


def _block_text(block: dict[str, Any]) -> str:
    inline_text = _inline_contents(block)
    if inline_text:
        return inline_text.strip()
    return (block.get("text") or "").strip()


def _normalized_bbox(block: dict[str, Any]) -> dict[str, float]:
    """Return a normalized bbox for v1.3 dict/list and legacy absolute forms."""
    raw = block.get("bbox")
    if isinstance(raw, dict):
        try:
            bbox = {key: float(raw[key]) for key in ("x1", "y1", "x2", "y2")}
        except (KeyError, TypeError, ValueError):
            return {}
    elif isinstance(raw, (list, tuple)) and len(raw) >= 4:
        try:
            bbox = dict(zip(("x1", "y1", "x2", "y2"), map(float, raw[:4])))
        except (TypeError, ValueError):
            return {}
    else:
        return {}

    page_width, page_height = _page_size(block)
    if max(abs(value) for value in bbox.values()) > 1.0 + 1e-6:
        bbox = {
            "x1": bbox["x1"] / page_width,
            "y1": bbox["y1"] / page_height,
            "x2": bbox["x2"] / page_width,
            "y2": bbox["y2"] / page_height,
        }
    return bbox


def norm_bbox_to_pdf(
    bbox_norm: dict[str, float],
    page_width: float,
    page_height: float,
) -> BBox:
    """Convert UniParser normalized top-left bbox to PyMuPDF page coordinates.

    Both UniParser and PyMuPDF use a top-left origin with y growing downward.
    """
    x1 = float(bbox_norm.get("x1", 0.0))
    y1 = float(bbox_norm.get("y1", 0.0))
    x2 = float(bbox_norm.get("x2", 0.0))
    y2 = float(bbox_norm.get("y2", 0.0))

    # Clamp to [0, 1] then map.
    x1 = min(max(x1, 0.0), 1.0)
    y1 = min(max(y1, 0.0), 1.0)
    x2 = min(max(x2, 0.0), 1.0)
    y2 = min(max(y2, 0.0), 1.0)

    pdf_x0 = min(x1, x2) * page_width
    pdf_x1 = max(x1, x2) * page_width
    pdf_y0 = min(y1, y2) * page_height
    pdf_y1 = max(y1, y2) * page_height
    return BBox(x0=pdf_x0, y0=pdf_y0, x1=pdf_x1, y1=pdf_y1)


def _page_size(block: dict[str, Any]) -> tuple[float, float]:
    size = block.get("page_size") or [1, 1]
    if not isinstance(size, (list, tuple)) or len(size) < 2:
        return (1.0, 1.0)
    w, h = float(size[0]), float(size[1])
    return (w if w > 0 else 1.0, h if h > 0 else 1.0)


def _decide_translate(
    block: dict[str, Any],
    text: str,
    bbox_norm: dict[str, float],
) -> tuple[bool, str | None]:
    if block.get("hidden") is True:
        return False, "hidden"
    btype = (block.get("type") or "").strip().lower()
    if btype in SKIP_TYPES:
        return False, f"type:{btype}"
    if btype not in TRANSLATABLE_TYPES:
        return False, f"unsupported_type:{btype or 'unknown'}"
    if not text:
        return False, "empty_text"
    if not all(key in bbox_norm for key in ("x1", "y1", "x2", "y2")):
        return False, "missing_bbox"
    return True, None


def pages_tree_to_units(
    pages_tree_data: dict[str, Any] | list[Any],
    *,
    page_rect_map: dict[int, tuple[float, float]] | None = None,
) -> list[TranslateUnit]:
    """Convert UniParser pages_tree into TranslateUnit list.

    ``page_rect_map`` maps page index -> (width_pt, height_pt) from the PDF.
    When omitted, ``page_size`` pixels from UniParser are used as a stand-in
    (fine for adapter unit tests; production should pass real PDF rects).
    """
    if isinstance(pages_tree_data, dict):
        pages = pages_tree_data.get("pages_tree")
        if pages is None:
            raise ValueError("Invalid pages_tree data: missing 'pages_tree' key")
    else:
        pages = pages_tree_data
    if not isinstance(pages, list):
        raise ValueError(f"Expected pages_tree list, got {type(pages)}")

    units: list[TranslateUnit] = []
    for idx, block in enumerate(_iter_blocks(pages)):
        page = int(block.get("page") if block.get("page") is not None else 0)
        order = int(block.get("order") if block.get("order") is not None else idx)
        btype = (block.get("type") or "").strip().lower()
        text = _block_text(block)
        bbox_norm = _normalized_bbox(block)
        page_size_px = _page_size(block)

        if page_rect_map and page in page_rect_map:
            page_w, page_h = page_rect_map[page]
        else:
            page_w, page_h = page_size_px

        translate, skip_reason = _decide_translate(block, text, bbox_norm)
        if all(k in bbox_norm for k in ("x1", "y1", "x2", "y2")):
            bbox_pdf = norm_bbox_to_pdf(bbox_norm, page_w, page_h)
        else:
            bbox_pdf = BBox(0.0, 0.0, 0.0, 0.0)
            if translate:
                translate = False
                skip_reason = "missing_bbox"

        unit = TranslateUnit(
            unit_id=f"p{page}_o{order}_{idx}",
            page=page,
            order=order,
            block_type=btype,
            text=text,
            bbox_norm=bbox_norm,
            page_size_px=page_size_px,
            bbox_pdf=bbox_pdf,
            translate=translate,
            skip_reason=skip_reason,
            status="pending" if translate else "skipped",
        )
        units.append(unit)

    units.sort(key=lambda u: (u.page, u.order, u.unit_id))
    return units


def adapt_pages_tree_file(
    pages_tree_path: str | Path,
    output_path: str | Path,
    *,
    page_rect_map: dict[int, tuple[float, float]] | None = None,
) -> list[TranslateUnit]:
    path = Path(pages_tree_path).expanduser().resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    units = pages_tree_to_units(data, page_rect_map=page_rect_map)
    out = Path(output_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for unit in units:
            fh.write(json.dumps(unit.to_dict(), ensure_ascii=False) + "\n")
    return units
