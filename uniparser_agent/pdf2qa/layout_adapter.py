"""Convert UniParser pages_tree into a flat LLM content list with ids."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SKIP_TYPES = frozenset({"hline", "pageheader", "pagefooter", "pagenumber"})
TEXT_TYPES = frozenset({"paragraph", "title", "documenttitle"})


def _block_text(block: dict[str, Any]) -> str:
    btype = (block.get("type") or "").strip().lower()
    if btype == "equation":
        latex = (block.get("latex_repr") or "").strip()
        if latex:
            if latex.startswith("$$") or latex.startswith("$"):
                return latex
            return f"$$\n{latex}\n$$"
        return (block.get("text") or "").strip()
    return (block.get("text") or "").strip()


def _iter_blocks(pages_tree: list[Any]) -> list[dict[str, Any]]:
    """Flatten pages into a reading-order list of blocks."""
    flat: list[dict[str, Any]] = []
    for page in pages_tree:
        if not isinstance(page, list):
            continue
        ordered = sorted(
            [b for b in page if isinstance(b, dict)],
            key=lambda b: (b.get("order") if b.get("order") is not None else 10**9),
        )
        for block in ordered:
            items = block.get("items")
            if isinstance(items, list) and items:
                nested = sorted(
                    [b for b in items if isinstance(b, dict)],
                    key=lambda b: (b.get("order") if b.get("order") is not None else 10**9),
                )
                flat.extend(nested)
            else:
                flat.append(block)
    return flat


def pages_tree_to_content_list(pages_tree_data: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    """Adapt UniParser pages_tree envelope (or raw list) to LLM content list."""
    if isinstance(pages_tree_data, dict):
        pages = pages_tree_data.get("pages_tree")
        if pages is None:
            raise ValueError("Invalid pages_tree data: missing 'pages_tree' key")
    else:
        pages = pages_tree_data

    if not isinstance(pages, list):
        raise ValueError(f"Expected pages_tree list, got {type(pages)}")

    content: list[dict[str, Any]] = []
    next_id = 0
    for block in _iter_blocks(pages):
        btype = (block.get("type") or "").strip().lower()
        if btype in SKIP_TYPES:
            continue

        text = _block_text(block)
        source = block.get("source") or ""
        has_source = isinstance(source, str) and bool(source.strip())

        if btype == "equation":
            if not text and not has_source:
                continue
            item: dict[str, Any] = {"id": next_id, "type": "equation", "text": text}
            content.append(item)
            next_id += 1
            continue

        if btype in TEXT_TYPES or text:
            if not text:
                continue
            content.append({"id": next_id, "type": "text", "text": text})
            next_id += 1
            continue

        # Figure/table/chart with source — MVP keeps a placeholder text path ref if present.
        if has_source and btype in {"figure", "image", "chart", "table"}:
            content.append(
                {
                    "id": next_id,
                    "type": "image",
                    "img_path": f"images/{block.get('page', 0)}_{block.get('block', next_id)}.png",
                    "image_caption": [],
                }
            )
            next_id += 1

    return content


def adapt_pages_tree_file(pages_tree_path: str | Path, output_path: str | Path) -> list[dict[str, Any]]:
    path = Path(pages_tree_path).expanduser().resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    content = pages_tree_to_content_list(data)
    out = Path(output_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    return content
