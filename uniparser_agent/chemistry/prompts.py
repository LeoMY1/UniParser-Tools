"""Strategy A prompts: structure cards + prealigned table rows."""

from __future__ import annotations

import json

from uniparser_agent.chemistry.join import LogicalCompound, truncate_nmr

BATCH_SIZE = 6

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
      "activities": [
        {
          "activity_type": "IC50|inhibition|aggregation|cell_viability|synergy|other",
          "activity_value": "number or string",
          "activity_value_sd": "number or empty",
          "activity_unit": "string",
          "assay": "string",
          "condition": "string or empty",
          "evidence": "string"
        }
      ],
      "confidence": 0.0
    }
  ]
}
Rules:
- Only use activity numbers present in the provided context. Do not invent IC50/inhibition/% values.
- If no activity is given for a compound, use activities: [] and say so in semantic_summary.
- Prefer concrete example compounds over Markush scaffolds when both appear.
- Do not attach reference-drug rows (e.g. clopidogrel) to target compounds.
- Keep labels/SMILES faithful to the cards.
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
        "local_context": truncate_nmr(c.local_context, 500),
    }


def build_strategy_a_prompt(doc_id: str, batch: list[LogicalCompound]) -> tuple[str, str]:
    payload = {
        "document": doc_id,
        "instruction": (
            "Each item is a pre-aligned structure card with catalog/activity table rows "
            "already joined by label/SMILES/example number. Write semantic_summary and "
            "normalize activities JSON. Keep labels/SMILES faithful to the card."
        ),
        "compounds": [compound_card(c) for c in batch],
    }
    user = json.dumps(payload, ensure_ascii=False, indent=2)
    return SYSTEM_PROMPT, user
