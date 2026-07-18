from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import typer

from uniparser_agent.chemistry.config import default_db_path
from uniparser_agent.chemistry.export_csv import export_doc_csv, export_library_csv
from uniparser_agent.chemistry.jobspec import JobSpec, PROFILE_MODULES
from uniparser_agent.parse.service import parse_document
from uniparser_agent.chemistry.pipeline import ingest_pages_tree, run_full_pipeline
from uniparser_agent.chemistry.store import ChemistryStore
from uniparser_agent.pdf2qa.pipeline import run_qa_pipeline


app = typer.Typer(
    name="uniparser-agent",
    help="UniParser agent: chemistry library and exam QA extraction.",
    no_args_is_help=True,
)


@app.command("parse")
def parse_cmd(
    input_path: str = typer.Argument(..., help="Local PDF/image path or public PDF URL."),
    output_dir: Optional[str] = typer.Option(None, "-o", "--output-dir", help="Output directory."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Replace output directory if it exists."),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Parse a document with UniParser scientific-paper defaults."""
    result = parse_document(input_path, output_dir=output_dir, overwrite=overwrite)
    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    typer.echo(f"Token: {result.get('token', '')}")
    typer.echo(f"Pages tree: {result['pages_tree_path']}")
    typer.echo(f"Markdown: {result['markdown_path']}")
    typer.echo(f"Output directory: {result['output_dir']}")


@app.command("ingest")
def ingest_cmd(
    pages_tree_path: str = typer.Argument(..., help="Path to pages_tree.json."),
    doc_id: Optional[str] = typer.Option(None, "--doc-id", help="Document identifier."),
    profile: str = typer.Option("scientific-paper", "--profile", help=f"Profile: {list(PROFILE_MODULES)}"),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite database path."),
    source: Optional[str] = typer.Option(None, "--source", help="Original source path or URL."),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Ingest molecules and reactions from an existing pages_tree.json."""
    jobspec = JobSpec.from_profile(profile, db_path=Path(db) if db else default_db_path())
    summary = ingest_pages_tree(
        pages_tree_path,
        jobspec=jobspec,
        doc_id=doc_id,
        source=source,
        db_path=jobspec.db_path,
    )
    payload = {
        "doc_id": summary.doc_id,
        "db_path": str(jobspec.db_path),
        "n_extractions": summary.n_extractions,
        "n_unique_compounds": summary.n_unique_compounds,
        "n_markush": summary.n_markush,
        "n_invalid": summary.n_invalid,
        "n_reactions": summary.n_reactions,
    }
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    _print_summary(payload)


@app.command("run")
def run_cmd(
    input_path: str = typer.Argument(..., help="Local PDF/image path or public PDF URL."),
    doc_id: Optional[str] = typer.Option(None, "--doc-id", help="Document identifier."),
    profile: str = typer.Option("scientific-paper", "--profile", help=f"Profile: {list(PROFILE_MODULES)}"),
    output_dir: Optional[str] = typer.Option(None, "-o", "--output-dir", help="Parse output directory."),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite database path."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Replace parse output directory if it exists."),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Parse a document and ingest into the chemistry library."""
    jobspec = JobSpec.from_profile(profile, db_path=Path(db) if db else default_db_path())
    result = run_full_pipeline(
        input_path,
        jobspec=jobspec,
        doc_id=doc_id,
        output_dir=output_dir,
        overwrite=overwrite,
        db_path=jobspec.db_path,
    )
    summary = result["ingest"]
    payload = {
        "doc_id": summary.doc_id,
        "db_path": result["db_path"],
        "pages_tree_path": result["parse"]["pages_tree_path"],
        "markdown_path": result["parse"]["markdown_path"],
        "n_extractions": summary.n_extractions,
        "n_unique_compounds": summary.n_unique_compounds,
        "n_markush": summary.n_markush,
        "n_invalid": summary.n_invalid,
        "n_reactions": summary.n_reactions,
    }
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(f"Pages tree: {payload['pages_tree_path']}")
    typer.echo(f"Database: {payload['db_path']}")
    _print_summary(payload)


@app.command("show")
def show_cmd(
    doc_id: str = typer.Argument(..., help="Document identifier."),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite database path."),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show ingest statistics for a document."""
    with ChemistryStore(Path(db) if db else default_db_path()) as store:
        stats = store.get_document_stats(doc_id)
    if json_output:
        typer.echo(json.dumps(stats, ensure_ascii=False, indent=2))
        return
    typer.echo(f"doc_id: {stats['doc_id']}")
    typer.echo(f"source: {stats['source']}")
    typer.echo(f"parsed_at: {stats['parsed_at']}")
    typer.echo(f"extractions: {stats['extractions']}")
    typer.echo(f"unique_compounds: {stats['unique_compounds']}")
    typer.echo(f"invalid: {stats['invalid']}")
    typer.echo(f"markush: {stats['markush']}")
    typer.echo(f"reactions: {stats['reactions']}")


@app.command("qa")
def qa_cmd(
    input_path: Optional[str] = typer.Argument(
        None,
        help="Local PDF/image path or public PDF URL. Omit when using --pages-tree.",
    ),
    output_dir: Optional[str] = typer.Option(None, "-o", "--output-dir", help="QA output directory."),
    pages_tree: Optional[str] = typer.Option(
        None,
        "--pages-tree",
        help="Skip UniParser parse and use an existing pages_tree.json.",
    ),
    overwrite: bool = typer.Option(False, "--overwrite", help="Replace output directory if it exists."),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Parse with UniParser (unless --pages-tree) then extract QA pairs via LLM."""
    if not input_path and not pages_tree:
        raise typer.BadParameter("Provide INPUT (pdf/url/image) or --pages-tree.")
    if input_path and pages_tree:
        raise typer.BadParameter("Use either INPUT or --pages-tree, not both.")

    result = run_qa_pipeline(
        input_path=input_path,
        pages_tree_path=pages_tree,
        output_dir=output_dir,
        overwrite=overwrite,
    )
    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    paths = result["paths"]
    typer.echo(f"Pages tree: {paths['pages_tree']}")
    typer.echo(f"Content list items: {result['n_content_items']}")
    typer.echo(f"Merged QA pairs: {result['n_merged_qa']}")
    typer.echo(f"JSONL: {paths['merged_qa_pairs_jsonl']}")
    typer.echo(f"Markdown: {paths['merged_qa_pairs_md']}")
    typer.echo(f"Output directory: {paths['output_dir']}")


@app.command("export")
def export_cmd(
    doc_id: Optional[str] = typer.Argument(None, help="Document identifier. Omit when using --all."),
    out: Optional[str] = typer.Option(None, "--out", help="Export directory."),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite database path."),
    all_docs: bool = typer.Option(False, "--all", help="Export the full library across all documents."),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Export library data to CSV (one document or the full library)."""
    if all_docs and doc_id:
        raise typer.BadParameter("Use either DOC_ID or --all, not both.")
    if not all_docs and not doc_id:
        raise typer.BadParameter("Provide DOC_ID or pass --all to export the full library.")

    db_path = Path(db) if db else default_db_path()
    with ChemistryStore(db_path) as store:
        if all_docs:
            out_dir = Path(out).expanduser().resolve() if out else Path.cwd() / "exports" / "library"
            paths = export_library_csv(store, out_dir)
            payload: dict[str, Any] = {
                "mode": "library",
                "db_path": str(db_path),
                "out_dir": str(out_dir),
                "stats": store.get_library_stats(),
                "files": paths,
            }
        else:
            assert doc_id is not None
            out_dir = Path(out).expanduser().resolve() if out else Path.cwd() / "exports" / doc_id
            paths = export_doc_csv(store, doc_id, out_dir)
            payload = {
                "mode": "document",
                "doc_id": doc_id,
                "db_path": str(db_path),
                "out_dir": str(out_dir),
                "files": paths,
            }

    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if all_docs:
        stats = payload["stats"]
        typer.echo(f"Database: {payload['db_path']}")
        typer.echo(f"documents: {stats['documents']}")
        typer.echo(f"compounds: {stats['compounds']}")
        typer.echo(f"markush_scaffolds: {stats['markush_scaffolds']}")
        typer.echo(f"extractions: {stats['extractions']}")
        typer.echo(f"reactions: {stats['reactions']}")
    for name, path in paths.items():
        typer.echo(f"{name}: {path}")


def _print_summary(payload: dict) -> None:
    typer.echo(f"doc_id: {payload['doc_id']}")
    typer.echo(f"extractions: {payload['n_extractions']}")
    typer.echo(f"unique_compounds: {payload['n_unique_compounds']}")
    typer.echo(f"markush: {payload['n_markush']}")
    typer.echo(f"invalid: {payload['n_invalid']}")
    typer.echo(f"reactions: {payload['n_reactions']}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
