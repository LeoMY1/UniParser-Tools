"""Prompts for link-then-summarize enrich."""

from __future__ import annotations

import json

from uniparser_agent.chemistry.join import LogicalCompound
from uniparser_agent.chemistry.patent_chunks import PatentChunk


BATCH_SIZE = 6
LINK_BATCH_CHAR_BUDGET = 12_000
LOCAL_CONTEXT_MAX_CHARS = 4_000

SYSTEM_PROMPT = """You are a chemistry patent extraction assistant.
Extract molecule-library compounds only (no reactions).
Return STRICT JSON only (no markdown fences) matching this schema:
{
  "compounds": [
    {
      "compound_label": "string",
      "name": "string or empty",
      "smiles": "string or empty",
      "role": "claimed_compound|example_product|intermediate|scaffold|reagent|reference|unknown",
      "semantic_summary": "2-5 sentences on identity/role/activity or synthesis",
      "evidence_quotes": ["verbatim substrings from local_context"],
      "uncertainties": ["explicit evidence/structure conflicts or missing support"],
      "structure_text_conflict": false,
      "confidence": 0.0
    }
  ]
}
Rules:
- Only state facts supported by local_context (and tabulated activity rows on the card). Do not invent.
- Starting materials, yields, melting points, and colors must appear in local_context; otherwise omit or mark uncertainty.
- If local_context conflicts with the card SMILES (e.g. wrong aryl description), note the conflict and lower confidence; do not invent a structure story from SMILES alone.
- matched_activity_rows are authoritative BioActivity records. Describe them faithfully; do not add, remove, merge, or alter values.
- If local_context is empty for an unlabeled structure, role MUST be unknown and the summary must only state that textual evidence is unavailable.
- Put every conflict between SMILES and text into uncertainties, set structure_text_conflict=true, and lower confidence.
- When multiple examples/yields are present, keep them distinct; never generalize one example's yield to the whole compound family.
- Assign a yield only to the isolated product explicitly named in the same evidence; never assign a product yield to its starting material or reagent.
- Prefer concrete example compounds over Markush scaffolds when both appear.
- Do not attach reference-drug rows (e.g. clopidogrel) to target compounds.
- Keep labels/SMILES faithful to the cards.
- evidence_quotes must be exact substrings of local_context; omit if unsure.
"""

LINK_SYSTEM_PROMPT = """You are a chemistry patent evidence linker.
Given a molecule inventory and text units from a patent pages_tree (images excluded),
decide which text units are relevant evidence for which molecules.
Return STRICT JSON only (no markdown fences):
{
  "links": [
    {
      "unit_id": "p5_b12",
      "molecule_ids": ["IA", "smi:..."],
      "relation": "synthesis|activity|scaffold|other"
    }
  ]
}
Rules:
- molecule_ids must use ids from the inventory (compound_id / label).
- Link a unit only when it clearly discusses that molecule (label, embodiment, structure, activity, or synthesis of it).
- One unit may link to multiple molecules; omit units with no clear link.
- Do not invent molecule ids that are not in the inventory.
"""


def compound_card(c: LogicalCompound) -> dict:
    return {
        "compound_id": c.compound_id,
        "label": c.label,
        "name": c.name,
        "smiles": c.smi,
        "markush": c.markush,
        "pages": c.pages,
        "catalog_rows": c.catalog_rows,
        "matched_activity_rows": c.activity_rows,
        "local_context": c.local_context,
    }


def build_strategy_a_prompt(doc_id: str, batch: list[LogicalCompound]) -> tuple[str, str]:
    payload = {
        "document": doc_id,
        "instruction": (
            "Each item is a pre-aligned structure card with catalog/activity table rows "
            "already joined by label/SMILES/example number, plus local_context evidence "
            "linked from the patent text. Write semantic_summary only from local_context "
            "and authoritative matched_activity_rows. Do not rewrite activity records. "
            "Keep labels/SMILES faithful and report uncertainties explicitly."
        ),
        "compounds": [compound_card(c) for c in batch],
    }
    user = json.dumps(payload, ensure_ascii=False, indent=2)
    return SYSTEM_PROMPT, user


def build_link_prompt(
    doc_id: str,
    compounds: list[LogicalCompound],
    chunks: list[PatentChunk],
) -> tuple[str, str]:
    inventory = [
        {
            "compound_id": c.compound_id,
            "label": c.label,
            "smiles": c.smi,
            "pages": c.pages,
            "markush": c.markush,
        }
        for c in compounds
    ]
    payload = {
        "document": doc_id,
        "instruction": (
            "Link each relevant atomic unit to molecule compound_id values. Use patent "
            "section, example/claim number, and references as context, but return only "
            "unit_id values supplied below."
        ),
        "molecules": inventory,
        "chunks": [
            {
                "chunk_id": chunk.chunk_id,
                "parent_chunk_id": chunk.parent_chunk_id or None,
                "section_type": chunk.section_type,
                "section_title": chunk.section_title,
                "example_no": chunk.example_no or None,
                "claim_no": chunk.claim_no or None,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "references": chunk.references,
                "units": [
                    {
                        "unit_id": unit.unit_id,
                        "page": unit.page,
                        "type": unit.type,
                        "text": unit.text,
                    }
                    for unit in chunk.units
                ],
            }
            for chunk in chunks
        ],
    }
    user = json.dumps(payload, ensure_ascii=False, indent=2)
    return LINK_SYSTEM_PROMPT, user
