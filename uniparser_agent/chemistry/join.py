"""Join molecules, catalog tables, and activity rows into logical compounds."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from uniparser_agent.chemistry.tables import (
    CatalogRow,
    extract_catalog_tables,
    normalize_label,
    walk_blocks,
)


@dataclass
class MoleculeHit:
    page: int
    block: int
    label: str
    smi: str
    markush: bool
    caption: str = ""
    score: float | None = None


@dataclass
class LogicalCompound:
    compound_id: str
    label: str
    smi: str
    name: str = ""
    markush: bool = False
    pages: list[int] = field(default_factory=list)
    block: int | None = None
    score: float | None = None
    caption: str = ""
    catalog_rows: list[dict[str, Any]] = field(default_factory=list)
    activity_rows: list[dict[str, Any]] = field(default_factory=list)
    local_context: str = ""
    # LLM-enriched fields (filled later)
    role: str = ""
    semantic_summary: str = ""
    activities_json: list[dict[str, Any]] = field(default_factory=list)
    example_no: str = ""
    enrich_json: dict[str, Any] = field(default_factory=dict)
    source_type: str = "merged"


def _block_type(block: dict[str, Any]) -> str:
    return str(block.get("type") or "").strip().lower()


def _molecule_smiles(block: dict[str, Any]) -> str:
    return str(block.get("smi") or block.get("esmi") or "").strip()


def extract_molecules(pages: list[Any]) -> list[MoleculeHit]:
    hits: list[MoleculeHit] = []
    for page in pages:
        page_blocks = page if isinstance(page, list) else [page]
        for block in walk_blocks(page_blocks):
            if _block_type(block) == "moleculegroup":
                page_no = int(block.get("page", 0))
                label = ""
                smi = ""
                caption = ""
                markush = False
                score: float | None = None
                mol_block = int(block.get("block", 0))
                for nb in walk_blocks(block.get("items") or []):
                    nested_type = _block_type(nb)
                    if nested_type == "moleculeid":
                        label = normalize_label(nb.get("text") or "")
                    if nested_type == "molecule" or _molecule_smiles(nb):
                        smi = _molecule_smiles(nb) or smi
                        caption = (nb.get("caption") or "").strip() or caption
                        markush = bool(nb.get("markush")) or ("*" in smi) or markush
                        mol_block = int(nb.get("block", mol_block))
                        if nb.get("conf") is not None:
                            score = float(nb["conf"])
                if not smi and not label:
                    continue
                hits.append(
                    MoleculeHit(
                        page=page_no,
                        block=mol_block,
                        label=label,
                        smi=smi,
                        markush=markush,
                        caption=caption,
                        score=score,
                    )
                )
                continue

            # Standalone molecule nodes (not in moleculegroup)
            block_type = _block_type(block)
            if block_type == "molecule" or (
                "markush" in block
                and (block.get("smi") is not None or block.get("esmi") is not None)
                and block_type != "moleculegroup"
            ):
                # Skip if parent walk already handled via group items — still OK to collect leaves
                # Avoid double-count when nested under moleculegroup: parent group already yielded
                # Check: if we're a leaf under group, walk_blocks still yields us. Skip leaves that
                # are only reachable via group by requiring no parent context — simpler: only
                # collect standalone top-level-ish by skipping when we already have group path.
                # For fixtures without moleculegroup, we need this branch.
                smi = _molecule_smiles(block)
                caption = (block.get("caption") or "").strip()
                if not smi and not caption:
                    continue
                # De-dupe later by smi+page+block; groups already cover patent trees.
                # Only add if not already represented — use a marker: skip molecules that have
                # sibling moleculeid in same walk depth is hard; keep both and dedupe in join.
                hits.append(
                    MoleculeHit(
                        page=int(block.get("page", 0)),
                        block=int(block.get("block", 0)),
                        label="",
                        smi=smi,
                        markush=bool(block.get("markush")) or "*" in smi or "*" in caption,
                        caption=caption,
                        score=float(block["conf"]) if block.get("conf") is not None else None,
                    )
                )
    # Prefer moleculegroup hits: drop standalone molecule that shares page+smi with a labeled group hit
    labeled_keys = {(h.page, h.smi) for h in hits if h.label and h.smi}
    filtered: list[MoleculeHit] = []
    for h in hits:
        if not h.label and h.smi and (h.page, h.smi) in labeled_keys:
            continue
        filtered.append(h)
    return filtered


def join_compounds(
    doc_id: str,
    molecules: list[MoleculeHit],
    catalog: list[CatalogRow],
) -> list[LogicalCompound]:
    compounds: dict[str, LogicalCompound] = {}
    del doc_id  # reserved for future doc-specific policy

    def upsert(key: str, **kwargs: Any) -> LogicalCompound:
        if key not in compounds:
            compounds[key] = LogicalCompound(compound_id=key, label="", smi="")
        c = compounds[key]
        for k, v in kwargs.items():
            if v is None or v == "":
                continue
            cur = getattr(c, k, None)
            if isinstance(cur, list) and isinstance(v, list):
                for item in v:
                    if item not in cur:
                        cur.append(item)
            elif isinstance(cur, list) and not isinstance(v, list):
                if v not in cur:
                    cur.append(v)
            elif not cur:
                setattr(c, k, v)
            elif k == "smi" and "*" in str(cur) and "*" not in str(v):
                setattr(c, k, v)
            elif k == "markush" and cur and not v:
                setattr(c, k, False)
            elif k in ("block", "score", "caption") and getattr(c, k) in (None, ""):
                setattr(c, k, v)
        return c

    for row in catalog:
        upsert(
            row.label,
            label=row.label,
            smi=row.smi,
            name=row.name,
            pages=[row.page],
            catalog_rows=[asdict(row)],
            markush=False,
            source_type="catalog_table",
        )

    # Insert labeled structures first so exact unlabeled duplicates can be
    # folded into their stable label instead of becoming separate ``smi:`` cards.
    ordered_molecules = [m for m in molecules if m.label] + [m for m in molecules if not m.label]
    smi_to_labeled: dict[str, str] = {}
    for key, compound in compounds.items():
        if not compound.smi or not compound.label or compound.markush:
            continue
        existing = smi_to_labeled.get(compound.smi)
        smi_to_labeled[compound.smi] = key if not existing or existing == key else ""
    for mol in ordered_molecules:
        label = mol.label
        merged_label = smi_to_labeled.get(mol.smi) if not label and mol.smi else None
        if merged_label:
            key = merged_label
        elif not label and mol.smi:
            key = f"smi:{mol.smi}"
        elif label:
            key = label
            if key.startswith("式"):
                key = normalize_label(key.replace("式", "").strip(" ;；"))
        else:
            continue
        if catalog and re.match(r"^[IVX]+$", key) and any(c.label.startswith("I-") for c in catalog):
            # Prefer catalog I-n library over roman scaffolds on CN115-like docs
            continue
        upsert(
            key,
            label=label or key,
            smi=mol.smi,
            markush=mol.markush,
            pages=[mol.page],
            block=mol.block,
            score=mol.score,
            caption=mol.caption,
            source_type="molecule_node" if key not in compounds or not compounds[key].catalog_rows else "merged",
        )
        if label and mol.smi and not mol.markush:
            existing = smi_to_labeled.get(mol.smi)
            smi_to_labeled[mol.smi] = key if not existing or existing == key else ""

    # local_context is filled by Phase 2a LLM linking (enrich), not tag-truncated snippets.
    for _key, c in compounds.items():
        c.local_context = ""
        if c.catalog_rows and c.activity_rows:
            c.source_type = "merged"
        elif c.catalog_rows:
            c.source_type = "catalog_table"
        elif not c.source_type:
            c.source_type = "molecule_node"

    result = [c for c in compounds.values() if c.smi or c.activity_rows or c.catalog_rows]
    result.sort(key=_compound_sort_key)
    return result


def _compound_sort_key(c: LogicalCompound) -> tuple:
    m = re.match(r"^I-(\d+)$", c.label or c.compound_id)
    if m:
        return (0, int(m.group(1)), c.compound_id)
    roman = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9}
    if c.label in roman:
        return (1, roman[c.label], c.compound_id)
    if re.match(r"^I[A-F]$", c.label or ""):
        return (2, c.label or "", c.compound_id)
    if re.match(r"^\d+$", c.label or ""):
        return (3, int(c.label), c.compound_id)
    return (4, c.compound_id, "")


def select_library_compounds(doc_id: str, compounds: list[LogicalCompound]) -> list[LogicalCompound]:
    """Keep all joined compounds (products, Markush, intermediates, reactants).

    Deduping is already done in ``join_compounds`` by label / ``smi:`` key.
    This step only applies a stable sort for deterministic ingest order.
    """
    del doc_id  # reserved for future doc-specific policy
    out = list(compounds)
    out.sort(key=_compound_sort_key)
    return out


def build_logical_compounds(pages_tree_doc: dict[str, Any], doc_id: str) -> list[LogicalCompound]:
    pages = pages_tree_doc.get("pages_tree") or []
    molecules = extract_molecules(pages)
    catalog = extract_catalog_tables(pages)
    # Bioactivity is extracted later by the dedicated LLM table stage.
    compounds = join_compounds(doc_id, molecules, catalog)
    return select_library_compounds(doc_id, compounds)
