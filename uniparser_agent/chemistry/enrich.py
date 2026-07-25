"""Strategy A LLM enrichment: batch structure cards, parse JSON, merge back."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from uniparser_agent.chemistry.join import LogicalCompound
from uniparser_agent.chemistry.prompts import BATCH_SIZE, build_strategy_a_prompt
from uniparser_agent.llm import LLMConfig, OpenAICompatLLM, resolve_llm_config


ChatFn = Callable[[str, str], str]


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def parse_enrich_response(raw: str) -> list[dict[str, Any]]:
    data = json.loads(_strip_fences(raw))
    if isinstance(data, dict) and "compounds" in data:
        items = data["compounds"]
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError("LLM response must be a list or {compounds: [...]}")
    if not isinstance(items, list):
        raise ValueError("compounds must be a list")
    return [x for x in items if isinstance(x, dict)]


def _normalize_activities(raw_acts: Any, prealigned: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(raw_acts, list):
        raw_acts = []
    for a in raw_acts:
        if not isinstance(a, dict):
            continue
        kind = (
            a.get("activity_type")
            or a.get("metric")
            or a.get("kind")
            or "other"
        )
        kind_map = {
            "ic50": "IC50",
            "IC50": "IC50",
            "inhibition": "inhibition",
            "aggregation": "aggregation",
            "viability": "cell_viability",
            "cell_viability": "cell_viability",
            "synergy": "synergy",
        }
        activity_type = kind_map.get(str(kind), str(kind))
        value = a.get("activity_value", a.get("value"))
        sd = a.get("activity_value_sd", a.get("sd"))
        unit = a.get("activity_unit", a.get("unit", ""))
        assay = a.get("assay", "")
        condition = a.get("condition") or a.get("partner") or ""
        evidence = a.get("evidence") or a.get("raw") or ""
        out.append(
            {
                "activity_type": activity_type,
                "activity_value": value,
                "activity_value_sd": sd,
                "activity_unit": unit,
                "assay": assay,
                "condition": condition or None,
                "evidence": evidence,
            }
        )
    # If LLM returned empty but we have prealigned rows, seed best-effort activities
    if not out and prealigned:
        for row in prealigned:
            kind = row.get("kind", "other")
            kind_map = {
                "ic50": "IC50",
                "inhibition": "inhibition",
                "viability": "cell_viability",
                "synergy": "synergy",
            }
            out.append(
                {
                    "activity_type": kind_map.get(kind, kind),
                    "activity_value": row.get("value"),
                    "activity_value_sd": None,
                    "activity_unit": row.get("unit", ""),
                    "assay": kind,
                    "condition": row.get("partner") or None,
                    "evidence": row.get("raw") or "",
                }
            )
    return out


def _index_key(item: dict[str, Any]) -> str:
    return str(
        item.get("compound_label")
        or item.get("label")
        or item.get("compound_id")
        or item.get("smiles")
        or ""
    ).strip()


def merge_enrichment(
    compounds: list[LogicalCompound],
    llm_items: list[dict[str, Any]],
    *,
    enrich_meta: dict[str, Any] | None = None,
) -> list[LogicalCompound]:
    by_label = {_index_key(x): x for x in llm_items if _index_key(x)}
    meta = enrich_meta or {}
    for c in compounds:
        hit = by_label.get(c.label) or by_label.get(c.compound_id)
        if not hit and c.smi:
            for item in llm_items:
                if (item.get("smiles") or item.get("smi") or "") == c.smi:
                    hit = item
                    break
        if not hit:
            # Seed activities from prealigned rows when LLM skipped this card
            if c.activity_rows and not c.activities_json:
                c.activities_json = _normalize_activities([], c.activity_rows)
            c.enrich_json = {**meta, "status": "missing_in_llm"}
            continue
        c.compound_label = str(hit.get("compound_label") or hit.get("label") or c.label)
        if hit.get("name"):
            c.name = str(hit["name"])
        role = str(hit.get("role") or "")
        # normalize role aliases from experiment prompt
        role_map = {
            "target_compound": "claimed_compound",
            "claimed_compound": "claimed_compound",
            "example_product": "example_product",
            "intermediate": "intermediate",
            "scaffold": "scaffold",
            "reagent": "reagent",
            "reference": "reference",
            "unknown": "unknown",
        }
        c.role = role_map.get(role, role or "unknown")
        c.semantic_summary = str(hit.get("semantic_summary") or "")
        c.activities_json = _normalize_activities(hit.get("activities"), c.activity_rows)
        conf = hit.get("confidence")
        c.enrich_json = {**meta, "status": "ok", "confidence": conf}
        if not c.label:
            c.label = c.compound_label
    return compounds


def _batched(items: list[LogicalCompound], n: int) -> list[list[LogicalCompound]]:
    return [items[i : i + n] for i in range(0, len(items), n)]


def enrich_compounds(
    doc_id: str,
    compounds: list[LogicalCompound],
    *,
    llm_config: LLMConfig | None = None,
    llm_client: OpenAICompatLLM | None = None,
    chat_fn: ChatFn | None = None,
    skip_enrich: bool = False,
    batch_size: int = BATCH_SIZE,
) -> list[LogicalCompound]:
    """Run Strategy A enrichment. On skip/failure, keep rule fields and seed activities."""
    if not compounds:
        return compounds

    if skip_enrich:
        for c in compounds:
            if c.activity_rows and not c.activities_json:
                c.activities_json = _normalize_activities([], c.activity_rows)
            c.enrich_json = {"status": "skipped"}
        return compounds

    def _chat(system_prompt: str, user_content: str) -> str:
        if chat_fn is not None:
            return chat_fn(system_prompt, user_content)
        client = llm_client or OpenAICompatLLM(config=llm_config or resolve_llm_config())
        return client.chat(system_prompt=system_prompt, user_content=user_content)

    # Probe config availability when not injecting chat_fn
    if chat_fn is None and llm_client is None:
        try:
            resolve_llm_config(config=llm_config)
        except Exception as exc:  # noqa: BLE001 — missing env is expected
            for c in compounds:
                if c.activity_rows and not c.activities_json:
                    c.activities_json = _normalize_activities([], c.activity_rows)
                c.enrich_json = {"status": "no_llm_config", "error": str(exc)}
            return compounds

    model_name = ""
    if llm_client is not None:
        model_name = llm_client.model
    elif llm_config is not None:
        model_name = llm_config.model

    for batch in _batched(compounds, max(1, batch_size)):
        system_prompt, user_content = build_strategy_a_prompt(doc_id, batch)
        raw = ""
        last_err = ""
        items: list[dict[str, Any]] = []
        for attempt in range(2):
            try:
                raw = _chat(system_prompt, user_content)
                items = parse_enrich_response(raw)
                break
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
                items = []
        meta = {"model": model_name, "strategy": "A", "batch_size": len(batch)}
        if not items:
            for c in batch:
                if c.activity_rows and not c.activities_json:
                    c.activities_json = _normalize_activities([], c.activity_rows)
                c.enrich_json = {**meta, "status": "llm_failed", "error": last_err}
            continue
        merge_enrichment(batch, items, enrich_meta=meta)
    return compounds
