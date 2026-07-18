from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class MoleculeExtraction:
    smi: str
    caption: str
    markush: bool
    page: int
    block: int
    bbox: dict[str, Any] | None
    score: float | None = None
    token: str = ""


@dataclass
class ReactionExtraction:
    reactants: str
    products: str
    conditions: str
    page: int
    block: int
    bbox: dict[str, Any] | None
    token: str = ""
    reactant_texts: list[str] = field(default_factory=list)
    product_texts: list[str] = field(default_factory=list)
    condition_texts: list[str] = field(default_factory=list)


def _walk_blocks(blocks: list[Any]) -> Iterator[dict[str, Any]]:
    for block in blocks:
        if not isinstance(block, dict):
            continue
        yield block
        nested = block.get("items")
        if isinstance(nested, list):
            yield from _walk_blocks(nested)


def _bbox_from_block(block: dict[str, Any]) -> dict[str, Any] | None:
    bbox = block.get("bbox")
    return bbox if isinstance(bbox, dict) else None


def _component_texts(components: Any) -> list[str]:
    if not isinstance(components, list):
        return []
    texts: list[str] = []
    for comp in components:
        if isinstance(comp, dict):
            text = (comp.get("text") or "").strip()
        else:
            text = (getattr(comp, "text", "") or "").strip()
        if text:
            texts.append(text)
    return texts


def _join_components(components: Any) -> str:
    return ", ".join(_component_texts(components))


def extract_from_pages_tree(pages_tree_doc: dict[str, Any]) -> tuple[list[MoleculeExtraction], list[ReactionExtraction]]:
    molecules: list[MoleculeExtraction] = []
    reactions: list[ReactionExtraction] = []

    pages = pages_tree_doc.get("pages_tree") or []
    for page_items in pages:
        if not isinstance(page_items, list):
            continue
        for block in _walk_blocks(page_items):
            block_type = block.get("type")
            if block_type == "molecule" or "markush" in block:
                smi = (block.get("smi") or "").strip()
                caption = (block.get("caption") or "").strip()
                markush = bool(block.get("markush")) or "*" in smi or "*" in caption
                if not smi and not caption:
                    continue
                molecules.append(
                    MoleculeExtraction(
                        smi=smi,
                        caption=caption,
                        markush=markush,
                        page=int(block.get("page", 0)),
                        block=int(block.get("block", 0)),
                        bbox=_bbox_from_block(block),
                        score=float(block["conf"]) if block.get("conf") is not None else None,
                        token=str(block.get("token") or ""),
                    )
                )
            elif block_type == "expression" or "reactions" in block:
                for reaction in block.get("reactions") or []:
                    if not isinstance(reaction, dict):
                        continue
                    reactant_texts = _component_texts(reaction.get("reactants"))
                    product_texts = _component_texts(reaction.get("products"))
                    condition_texts = _component_texts(reaction.get("conditions"))
                    if not reactant_texts and not product_texts and not condition_texts:
                        continue
                    reactions.append(
                        ReactionExtraction(
                            reactants=_join_components(reaction.get("reactants")),
                            products=_join_components(reaction.get("products")),
                            conditions=_join_components(reaction.get("conditions")),
                            page=int(block.get("page", 0)),
                            block=int(block.get("block", 0)),
                            bbox=_bbox_from_block(block),
                            token=str(block.get("token") or ""),
                            reactant_texts=reactant_texts,
                            product_texts=product_texts,
                            condition_texts=condition_texts,
                        )
                    )
    return molecules, reactions
