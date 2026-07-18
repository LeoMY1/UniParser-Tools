from __future__ import annotations

from pathlib import Path
from typing import Any

from uniparser_agent.chemistry.config import default_db_path
from uniparser_agent.chemistry.extract import extract_from_pages_tree
from uniparser_agent.chemistry.jobspec import JobSpec
from uniparser_agent.parse.service import load_pages_tree, parse_document
from uniparser_agent.chemistry.store import ChemistryStore, IngestSummary


def _resolve_doc_id(doc_id: str | None, fallback: str) -> str:
    return (doc_id or fallback).strip() or fallback


def ingest_pages_tree(
    pages_tree_path: str | Path,
    *,
    jobspec: JobSpec,
    doc_id: str | None = None,
    source: str | None = None,
    markdown_path: str | None = None,
    output_dir: str | None = None,
    token: str = "",
    db_path: Path | None = None,
) -> IngestSummary:
    path = Path(pages_tree_path).expanduser().resolve()
    pages_tree_doc = load_pages_tree(path)
    molecules, reactions = extract_from_pages_tree(pages_tree_doc)
    resolved_doc_id = _resolve_doc_id(doc_id, path.parent.name)
    jobspec.doc_id = resolved_doc_id
    jobspec.source = source or str(path)
    jobspec.db_path = db_path or jobspec.db_path or default_db_path()

    with ChemistryStore(jobspec.db_path) as store:
        return store.ingest(
            doc_id=resolved_doc_id,
            source=jobspec.source,
            pages_tree_path=str(path),
            markdown_path=markdown_path,
            output_dir=output_dir,
            token=token,
            jobspec=jobspec,
            molecules=molecules,
            reactions=reactions,
        )


def run_full_pipeline(
    input_path: str,
    *,
    jobspec: JobSpec,
    doc_id: str | None = None,
    output_dir: str | None = None,
    overwrite: bool = False,
    db_path: Path | None = None,
) -> dict[str, Any]:
    parse_result = parse_document(input_path, output_dir=output_dir, overwrite=overwrite)
    resolved_doc_id = _resolve_doc_id(doc_id, parse_result["source_stem"])
    jobspec.doc_id = resolved_doc_id
    jobspec.source = input_path
    jobspec.output_dir = Path(parse_result["output_dir"])
    jobspec.db_path = db_path or jobspec.db_path or default_db_path()

    summary = ingest_pages_tree(
        parse_result["pages_tree_path"],
        jobspec=jobspec,
        doc_id=resolved_doc_id,
        source=input_path,
        markdown_path=parse_result.get("markdown_path"),
        output_dir=parse_result.get("output_dir"),
        token=parse_result.get("token", ""),
        db_path=jobspec.db_path,
    )
    return {
        "parse": parse_result,
        "ingest": summary,
        "db_path": str(jobspec.db_path),
    }
