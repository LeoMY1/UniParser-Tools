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
from uniparser_agent.pdf2vqa.pipeline import run_vqa_pipeline
from uniparser_agent.pdf2translate.pipeline import run_translate_pipeline


app = typer.Typer(
    name="uniparser-agent",
    help="UniParser agent: chemistry library, exam VQA, and PDF translation.",
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


@app.command("vqa")
def vqa_cmd(
    input_path: Optional[str] = typer.Argument(
        None,
        help="Local PDF/image path or public PDF URL. Omit when using --pages-tree.",
    ),
    output_dir: Optional[str] = typer.Option(None, "-o", "--output-dir", help="VQA output directory."),
    answer_pdf: Optional[str] = typer.Option(
        None,
        "--answer-pdf",
        help="Answer booklet PDF. Merged after the question booklet (local PDFs only).",
    ),
    pages_tree: Optional[str] = typer.Option(
        None,
        "--pages-tree",
        help="Skip UniParser parse and use an existing pages_tree.json.",
    ),
    overwrite: bool = typer.Option(False, "--overwrite", help="Replace output directory if it exists."),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Parse with UniParser (unless --pages-tree) then extract VQA pairs via LLM."""
    if answer_pdf and pages_tree:
        raise typer.BadParameter("Use either --answer-pdf or --pages-tree, not both.")
    if answer_pdf and not input_path:
        raise typer.BadParameter("--answer-pdf requires the question booklet as INPUT.")
    if not input_path and not pages_tree:
        raise typer.BadParameter("Provide INPUT (pdf/url/image) or --pages-tree.")
    if input_path and pages_tree:
        raise typer.BadParameter("Use either INPUT or --pages-tree, not both.")

    result = run_vqa_pipeline(
        input_path=input_path,
        answer_pdf=answer_pdf,
        pages_tree_path=pages_tree,
        output_dir=output_dir,
        overwrite=overwrite,
    )
    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    paths = result["paths"]
    if paths.get("merged_pdf"):
        typer.echo(f"Merged PDF: {paths['merged_pdf']}")
    typer.echo(f"Pages tree: {paths['pages_tree']}")
    typer.echo(f"Content list items: {result['n_content_items']}")
    typer.echo(f"VQA images: {result.get('n_vqa_images', 0)} -> {paths.get('vqa_images', '')}")
    typer.echo(f"Merged VQA pairs: {result['n_merged_vqa']}")
    typer.echo(f"JSONL: {paths['merged_vqa_pairs_jsonl']}")
    typer.echo(f"Markdown: {paths['merged_vqa_pairs_md']}")
    if paths.get("vqa_sharegpt"):
        typer.echo(f"ShareGPT: {paths['vqa_sharegpt']}")
    typer.echo(f"Output directory: {paths['output_dir']}")


@app.command("translate")
def translate_cmd(
    pdf_path: str = typer.Argument(..., help="Local PDF path to translate in place."),
    source_lang: Optional[str] = typer.Option(
        None,
        "--source-lang",
        help="Optional source language hint (default: auto).",
    ),
    output_dir: Optional[str] = typer.Option(
        None,
        "-o",
        "--output-dir",
        help="Translation output directory.",
    ),
    pages_tree: Optional[str] = typer.Option(
        None,
        "--pages-tree",
        help="Skip UniParser parse and use an existing pages_tree.json.",
    ),
    font: Optional[str] = typer.Option(
        None,
        "--font",
        help="Optional TTF/OTF font file for translated text.",
    ),
    glossary: Optional[str] = typer.Option(
        None,
        "--glossary",
        help="Optional glossary CSV (columns: source,target[,tgt_lng]).",
    ),
    auto_glossary: bool = typer.Option(
        True,
        "--auto-glossary/--no-auto-glossary",
        help="Auto-extract glossary terms before translation (default: on).",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Replace output directory if it exists.",
    ),
    debug_layout: bool = typer.Option(
        False,
        "--debug-layout",
        help="Also write layout_debug.pdf with unit bounding boxes.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Translate a PDF in place to zh-CN using UniParser layout + overlay rendering."""
    result = run_translate_pipeline(
        pdf_path,
        source_lang=source_lang,
        pages_tree_path=pages_tree,
        output_dir=output_dir,
        overwrite=overwrite,
        font=font,
        debug_layout=debug_layout,
        glossary_path=glossary,
        auto_glossary=auto_glossary,
    )
    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    paths = result["paths"]
    counts = result["counts"]
    typer.echo(f"Translated PDF: {paths['translated_pdf']}")
    typer.echo(f"Pages tree: {paths['pages_tree']}")
    typer.echo(f"Units: {paths['translate_units']}")
    typer.echo(
        "Counts: "
        f"translated={counts.get('translated', 0)} "
        f"skipped={counts.get('skipped', 0)} "
        f"failed={counts.get('failed', 0)} "
        f"overflow={counts.get('overflow', 0)}"
    )
    typer.echo(f"Output directory: {paths['output_dir']}")
    if paths.get("layout_debug_pdf"):
        typer.echo(f"Layout debug: {paths['layout_debug_pdf']}")


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
