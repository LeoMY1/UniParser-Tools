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
    compound_label: str = ""


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
    if isinstance(bbox, dict):
        return bbox
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        return dict(zip(("x1", "y1", "x2", "y2"), bbox[:4]))
    return None


def _molecule_smiles(block: dict[str, Any]) -> str:
    return str(block.get("smi") or block.get("esmi") or "").strip()


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


def extract_from_pages_tree(
    pages_tree_doc: dict[str, Any],
) -> tuple[list[MoleculeExtraction], list[ReactionExtraction]]:
    """Legacy walker: molecules (+ optional moleculeid) and reactions.

    Prefer :func:`uniparser_agent.chemistry.join.build_logical_compounds` for
    Strategy A molecule-library ingest.
    """
    molecules: list[MoleculeExtraction] = []
    reactions: list[ReactionExtraction] = []

    pages = pages_tree_doc.get("pages_tree") or []
    for page_items in pages:
        if not isinstance(page_items, list):
            continue
        for block in _walk_blocks(page_items):
            block_type = str(block.get("type") or "").strip().lower()
            if block_type == "moleculegroup":
                label = ""
                mol_block: dict[str, Any] | None = None
                for nb in _walk_blocks(block.get("items") or []):
                    nested_type = str(nb.get("type") or "").strip().lower()
                    if nested_type == "moleculeid":
                        label = (nb.get("text") or "").strip()
                    if nested_type == "molecule" or _molecule_smiles(nb):
                        mol_block = nb
                if mol_block is None:
                    continue
                smi = _molecule_smiles(mol_block)
                caption = (mol_block.get("caption") or "").strip()
                markush = bool(mol_block.get("markush")) or "*" in smi or "*" in caption
                if not smi and not caption:
                    continue
                molecules.append(
                    MoleculeExtraction(
                        smi=smi,
                        caption=caption,
                        markush=markush,
                        page=int(mol_block.get("page", block.get("page", 0))),
                        block=int(mol_block.get("block", block.get("block", 0))),
                        bbox=_bbox_from_block(mol_block),
                        score=float(mol_block["conf"]) if mol_block.get("conf") is not None else None,
                        token=str(mol_block.get("token") or ""),
                        compound_label=label,
                    )
                )
            elif block_type == "molecule" or "markush" in block:
                smi = _molecule_smiles(block)
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
