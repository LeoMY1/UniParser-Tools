"""CN chemistry-patent extraction pipeline built on semantic navigation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from uniparser_agent.chemistry.general_formula import write_general_formula_outputs
from uniparser_agent.chemistry.patent_basic_info import write_patent_basic_info
from uniparser_agent.chemistry.patent_structure import (
    BlockResolver,
    build_patent_structure,
    write_patent_structure_payload,
)
from uniparser_agent.llm import LLMConfig
from uniparser_agent.parse.service import load_pages_tree, parse_document


def _resolve_doc_id(doc_id: str | None, fallback: str) -> str:
    return (doc_id or fallback).strip() or fallback


def _write_patent_artifacts(
    pages_tree_doc: dict[str, Any],
    *,
    doc_id: str,
    output_dir: Path,
    llm_config: LLMConfig | None,
    skip_llm: bool,
) -> dict[str, Any]:
    """Build every currently supported V2 patent artifact from one pages tree."""
    patent_structure = build_patent_structure(pages_tree_doc, doc_id)
    resolver = BlockResolver(pages_tree_doc, patent_structure)
    patent_structure_path = write_patent_structure_payload(
        patent_structure,
        output_dir / "patent_structure.json",
    )
    patent_basic_info_path = write_patent_basic_info(
        resolver,
        doc_id,
        output_dir / "patent_basic_info.json",
    )
    formulas = write_general_formula_outputs(
        resolver,
        doc_id,
        output_dir,
        llm_config=llm_config,
        skip_llm=skip_llm,
    )
    return {
        "doc_id": doc_id,
        "patent_format": "CN",
        "output_dir": str(output_dir),
        "patent_structure_path": str(patent_structure_path),
        "patent_basic_info_path": str(patent_basic_info_path),
        "general_formula_inventory_path": str(formulas.inventory_path),
        "general_formula_context_chunks_path": str(formulas.context_chunks_path),
        "general_formula_analysis_path": str(formulas.analysis_path),
        "general_formula_excel_path": str(formulas.excel_path),
        "general_formula_summary_path": str(formulas.summary_path),
        "formula_count": formulas.formula_count,
        "formula_occurrence_count": formulas.occurrence_count,
        "formula_image_count": formulas.image_count,
        "formula_context_chunk_count": formulas.chunk_count,
        "formula_llm_call_count": formulas.llm_call_count,
        "skip_llm": skip_llm,
    }


def ingest_pages_tree(
    pages_tree_path: str | Path,
    *,
    doc_id: str | None = None,
    output_dir: str | Path | None = None,
    skip_llm: bool = False,
    llm_config: LLMConfig | None = None,
) -> dict[str, Any]:
    """Create V2 CN-patent artifacts from an existing `pages_tree.json`."""
    path = Path(pages_tree_path).expanduser().resolve()
    pages_tree_doc = load_pages_tree(path)
    resolved_doc_id = _resolve_doc_id(doc_id, path.parent.name)
    target_dir = Path(output_dir).expanduser().resolve() if output_dir else path.parent
    result = _write_patent_artifacts(
        pages_tree_doc,
        doc_id=resolved_doc_id,
        output_dir=target_dir,
        llm_config=llm_config,
        skip_llm=skip_llm,
    )
    result["pages_tree_path"] = str(path)
    return result


def run_full_pipeline(
    input_path: str,
    *,
    doc_id: str | None = None,
    output_dir: str | None = None,
    skip_llm: bool = False,
    llm_config: LLMConfig | None = None,
) -> dict[str, Any]:
    """Parse a document, then create only the supported V2 patent artifacts."""
    parse_result = parse_document(input_path, output_dir=output_dir)
    resolved_doc_id = _resolve_doc_id(doc_id, parse_result["source_stem"])
    result = ingest_pages_tree(
        parse_result["pages_tree_path"],
        doc_id=resolved_doc_id,
        output_dir=parse_result["output_dir"],
        skip_llm=skip_llm,
        llm_config=llm_config,
    )
    result.update(
        {
            "markdown_path": parse_result.get("markdown_path", ""),
            "token": parse_result.get("token", ""),
            "input_type": parse_result.get("input_type", ""),
            "source": input_path,
        }
    )
    return result
