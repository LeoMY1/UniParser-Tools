from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import typer

from uniparser_agent.chemistry.config import default_db_path
from uniparser_agent.chemistry.export_csv import export_doc_csv, export_library_csv
from uniparser_agent.chemistry.jobspec import JobSpec
from uniparser_agent.chemistry.patent_basic_info import write_patent_basic_info
from uniparser_agent.chemistry.patent_structure import BlockResolver, build_patent_structure, write_patent_structure
from uniparser_agent.chemistry.pipeline import ingest_pages_tree, run_full_pipeline
from uniparser_agent.chemistry.store import ChemistryStore
from uniparser_agent.llm import LLMConfig, resolve_llm_config
from uniparser_agent.parse.service import load_pages_tree, parse_document
from uniparser_agent.pdf2translate.pipeline import run_translate_pipeline
from uniparser_agent.pdf2vqa.pipeline import run_vqa_pipeline


app = typer.Typer(
    name="uniparser-agent",
    help="UniParser agent: chemistry library, exam VQA, and PDF translation.",
    no_args_is_help=True,
)


def _missing_doc_message(doc_id: str, db_path: Path, store: ChemistryStore) -> str:
    known = store.list_doc_ids()
    lines = [
        f"Document not found: {doc_id}",
        f"Database used: {db_path}",
        "If you passed --db when running ingest/run, pass the same --db to show/export (or set UNIPARSER_AGENT_DB).",
    ]
    if known:
        preview = ", ".join(known[:20])
        extra = f" … (+{len(known) - 20} more)" if len(known) > 20 else ""
        lines.append(f"Documents in this database: {preview}{extra}")
    else:
        lines.append("This database has no documents yet.")
    return "\n".join(lines)


@app.command("parse")
def parse_cmd(
    input_path: str = typer.Argument(..., help="Local PDF/image path or public PDF URL."),
    output_dir: Optional[str] = typer.Option(
        None,
        "-o",
        "--output-dir",
        help="Preferred output directory; a suffixed sibling is used if occupied.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Parse a document with UniParser scientific-paper defaults."""
    result = parse_document(input_path, output_dir=output_dir)
    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    typer.echo(f"Token: {result.get('token', '')}")
    typer.echo(f"Pages tree: {result['pages_tree_path']}")
    typer.echo(f"Markdown: {result['markdown_path']}")
    typer.echo(f"Output directory: {result['output_dir']}")


@app.command("patent-structure")
def patent_structure_cmd(
    pages_tree_path: str = typer.Argument(..., help="Path to pages_tree.json."),
    doc_id: Optional[str] = typer.Option(None, "--doc-id", help="Patent document identifier."),
    output_dir: Optional[str] = typer.Option(
        None,
        "-o",
        "--output-dir",
        help="Output directory; defaults to the pages_tree.json directory.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Build the fixed-depth CN patent structure tree from UniParser output."""
    pages_path = Path(pages_tree_path).expanduser().resolve()
    pages_tree_doc = load_pages_tree(pages_path)
    resolved_doc_id = (doc_id or pages_path.parent.name).strip() or pages_path.parent.name
    target_dir = Path(output_dir).expanduser().resolve() if output_dir else pages_path.parent
    structure_path = write_patent_structure(
        pages_tree_doc,
        resolved_doc_id,
        target_dir / "patent_structure.json",
    )
    payload = {
        "doc_id": resolved_doc_id,
        "patent_format": "CN",
        "patent_structure_path": str(structure_path),
    }
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(f"Patent structure: {structure_path}")


@app.command("patent-basic-info")
def patent_basic_info_cmd(
    pages_tree_path: str = typer.Argument(..., help="Path to pages_tree.json."),
    doc_id: Optional[str] = typer.Option(None, "--doc-id", help="Patent document identifier."),
    output_dir: Optional[str] = typer.Option(
        None,
        "-o",
        "--output-dir",
        help="Output directory; defaults to the pages_tree.json directory.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Extract rule-only CN patent basic information through semantic navigation."""
    pages_path = Path(pages_tree_path).expanduser().resolve()
    pages_tree_doc = load_pages_tree(pages_path)
    resolved_doc_id = (doc_id or pages_path.parent.name).strip() or pages_path.parent.name
    target_dir = Path(output_dir).expanduser().resolve() if output_dir else pages_path.parent
    semantic_tree_path = target_dir / "patent_structure.json"
    if not semantic_tree_path.exists():
        semantic_tree_path = pages_path.parent / "patent_structure.json"
    if semantic_tree_path.exists():
        patent_structure = json.loads(semantic_tree_path.read_text(encoding="utf-8"))
    else:
        patent_structure = build_patent_structure(pages_tree_doc, resolved_doc_id)
    resolver = BlockResolver(pages_tree_doc, patent_structure)
    basic_info_path = write_patent_basic_info(
        resolver,
        resolved_doc_id,
        target_dir / "patent_basic_info.json",
    )
    payload = {
        "doc_id": resolved_doc_id,
        "patent_format": "CN",
        "patent_basic_info_path": str(basic_info_path),
    }
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(f"Patent basic information: {basic_info_path}")


@app.command("ingest")
def ingest_cmd(
    pages_tree_path: str = typer.Argument(..., help="Path to pages_tree.json."),
    doc_id: Optional[str] = typer.Option(None, "--doc-id", help="Document identifier."),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite database path."),
    source: Optional[str] = typer.Option(None, "--source", help="Original source path or URL."),
    skip_enrich: bool = typer.Option(
        False,
        "--skip-enrich",
        help="Skip Strategy A LLM enrichment; store rule-joined fields only.",
    ),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="LLM API key (overrides OPENAI_API_KEY).", envvar=[]),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="LLM base URL (overrides OPENAI_BASE_URL)."),
    model: Optional[str] = typer.Option(None, "--model", help="LLM model name (overrides OPENAI_MODEL)."),
    enable_thinking: bool = typer.Option(
        False,
        "--enable-thinking/--no-enable-thinking",
        help="Pass chat_template_kwargs.enable_thinking for Qwen-compatible servers.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Ingest molecule library from an existing pages_tree.json (Strategy A enrich)."""
    jobspec = JobSpec(db_path=Path(db) if db else default_db_path())
    llm_config = None
    if not skip_enrich:
        try:
            llm_config = resolve_llm_config(
                api_key=api_key,
                base_url=base_url,
                model=model,
                enable_thinking=enable_thinking,
            )
        except ValueError:
            # Missing OPENAI_* → rule-only ingest (same as --skip-enrich)
            skip_enrich = True
    summary = ingest_pages_tree(
        pages_tree_path,
        jobspec=jobspec,
        doc_id=doc_id,
        source=source,
        patent_output_dir=Path(pages_tree_path).expanduser().resolve().parent,
        db_path=jobspec.db_path,
        skip_enrich=skip_enrich,
        llm_config=llm_config,
    )
    payload = {
        "doc_id": summary.doc_id,
        "db_path": str(jobspec.db_path),
        "n_compounds": summary.n_compounds,
        "n_unique_compounds": summary.n_unique_compounds,
        "n_markush": summary.n_markush,
        "n_invalid": summary.n_invalid,
        "n_with_activities": summary.n_with_activities,
        "n_enriched": summary.n_enriched,
        "patent_structure_path": summary.patent_structure_path,
        "patent_basic_info_path": summary.patent_basic_info_path,
        "skip_enrich": skip_enrich,
    }
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    _print_summary(payload)


@app.command("run")
def run_cmd(
    input_path: str = typer.Argument(..., help="Local PDF/image path or public PDF URL."),
    doc_id: Optional[str] = typer.Option(None, "--doc-id", help="Document identifier."),
    output_dir: Optional[str] = typer.Option(
        None,
        "-o",
        "--output-dir",
        help="Preferred parse output directory; a suffixed sibling is used if occupied.",
    ),
    db: Optional[str] = typer.Option(None, "--db", help="SQLite database path."),
    skip_enrich: bool = typer.Option(
        False,
        "--skip-enrich",
        help="Skip Strategy A LLM enrichment; store rule-joined fields only.",
    ),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="LLM API key (overrides OPENAI_API_KEY).", envvar=[]),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="LLM base URL (overrides OPENAI_BASE_URL)."),
    model: Optional[str] = typer.Option(None, "--model", help="LLM model name (overrides OPENAI_MODEL)."),
    enable_thinking: bool = typer.Option(
        False,
        "--enable-thinking/--no-enable-thinking",
        help="Pass chat_template_kwargs.enable_thinking for Qwen-compatible servers.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Parse a document and ingest into the molecule library."""
    jobspec = JobSpec(db_path=Path(db) if db else default_db_path())
    llm_config = None
    if not skip_enrich:
        try:
            llm_config = resolve_llm_config(
                api_key=api_key,
                base_url=base_url,
                model=model,
                enable_thinking=enable_thinking,
            )
        except ValueError:
            skip_enrich = True
    result = run_full_pipeline(
        input_path,
        jobspec=jobspec,
        doc_id=doc_id,
        output_dir=output_dir,
        db_path=jobspec.db_path,
        skip_enrich=skip_enrich,
        llm_config=llm_config,
    )
    summary = result["ingest"]
    payload = {
        "doc_id": summary.doc_id,
        "db_path": result["db_path"],
        "pages_tree_path": result["parse"]["pages_tree_path"],
        "markdown_path": result["parse"]["markdown_path"],
        "patent_structure_path": result["patent_structure_path"],
        "patent_basic_info_path": result["patent_basic_info_path"],
        "n_compounds": summary.n_compounds,
        "n_unique_compounds": summary.n_unique_compounds,
        "n_markush": summary.n_markush,
        "n_invalid": summary.n_invalid,
        "n_with_activities": summary.n_with_activities,
        "n_enriched": summary.n_enriched,
        "skip_enrich": skip_enrich,
    }
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(f"Pages tree: {payload['pages_tree_path']}")
    typer.echo(f"Patent structure: {payload['patent_structure_path']}")
    typer.echo(f"Patent basic information: {payload['patent_basic_info_path']}")
    typer.echo(f"Database: {payload['db_path']}")
    _print_summary(payload)


@app.command("show")
def show_cmd(
    doc_id: str = typer.Argument(..., help="Document identifier."),
    db: Optional[str] = typer.Option(
        None,
        "--db",
        help="SQLite database path (must match the --db used by run/ingest).",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show ingest statistics for a document."""
    db_path = Path(db).expanduser().resolve() if db else default_db_path()
    with ChemistryStore(db_path) as store:
        try:
            stats = store.get_document_stats(doc_id)
        except KeyError:
            typer.secho(_missing_doc_message(doc_id, db_path, store), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
    if json_output:
        typer.echo(json.dumps(stats, ensure_ascii=False, indent=2))
        return
    typer.echo(f"Database: {db_path}")
    typer.echo(f"doc_id: {stats['doc_id']}")
    typer.echo(f"source: {stats['source']}")
    typer.echo(f"parsed_at: {stats['parsed_at']}")
    typer.echo(f"compounds: {stats['compounds']}")
    typer.echo(f"unique_compounds: {stats['unique_compounds']}")
    typer.echo(f"invalid: {stats['invalid']}")
    typer.echo(f"markush: {stats['markush']}")
    typer.echo(f"with_activities: {stats['with_activities']}")
    typer.echo(f"enriched: {stats['enriched']}")


@app.command("vqa")
def vqa_cmd(
    input_path: Optional[str] = typer.Argument(
        None,
        help="Local PDF/image path or public PDF URL. Omit when using --pages-tree.",
    ),
    output_dir: Optional[str] = typer.Option(
        None,
        "-o",
        "--output-dir",
        help="Preferred VQA output directory; a suffixed sibling is used if occupied.",
    ),
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
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help="LLM API key (overrides OPENAI_API_KEY).",
        envvar=[],
    ),
    base_url: Optional[str] = typer.Option(
        None,
        "--base-url",
        help="LLM base URL (overrides OPENAI_BASE_URL).",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="LLM model name (overrides OPENAI_MODEL).",
    ),
    enable_thinking: bool = typer.Option(
        False,
        "--enable-thinking/--no-enable-thinking",
        help="Pass chat_template_kwargs.enable_thinking for Qwen-compatible servers.",
    ),
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

    llm_config = _build_llm_config(
        api_key=api_key,
        base_url=base_url,
        model=model,
        enable_thinking=enable_thinking,
    )
    result = run_vqa_pipeline(
        input_path=input_path,
        answer_pdf=answer_pdf,
        pages_tree_path=pages_tree,
        output_dir=output_dir,
        llm_config=llm_config,
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
        help="Preferred translation output directory; a suffixed sibling is used if occupied.",
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
    debug_layout: bool = typer.Option(
        False,
        "--debug-layout",
        help="Also write layout_debug.pdf with unit bounding boxes.",
    ),
    api_key: Optional[str] = typer.Option(
        None,
        "--api-key",
        help="LLM API key (overrides OPENAI_API_KEY).",
        envvar=[],
    ),
    base_url: Optional[str] = typer.Option(
        None,
        "--base-url",
        help="LLM base URL (overrides OPENAI_BASE_URL).",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="LLM model name (overrides OPENAI_MODEL).",
    ),
    enable_thinking: bool = typer.Option(
        False,
        "--enable-thinking/--no-enable-thinking",
        help="Pass chat_template_kwargs.enable_thinking for Qwen-compatible servers.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Translate a PDF in place to zh-CN using UniParser layout + overlay rendering."""
    llm_config = _build_llm_config(
        api_key=api_key,
        base_url=base_url,
        model=model,
        enable_thinking=enable_thinking,
    )
    result = run_translate_pipeline(
        pdf_path,
        source_lang=source_lang,
        pages_tree_path=pages_tree,
        output_dir=output_dir,
        font=font,
        debug_layout=debug_layout,
        glossary_path=glossary,
        auto_glossary=auto_glossary,
        llm_config=llm_config,
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
    db: Optional[str] = typer.Option(
        None,
        "--db",
        help="SQLite database path (must match the --db used by run/ingest).",
    ),
    all_docs: bool = typer.Option(False, "--all", help="Export the full library across all documents."),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Export library data to CSV (one document or the full library)."""
    if all_docs and doc_id:
        raise typer.BadParameter("Use either DOC_ID or --all, not both.")
    if not all_docs and not doc_id:
        raise typer.BadParameter("Provide DOC_ID or pass --all to export the full library.")

    db_path = Path(db).expanduser().resolve() if db else default_db_path()
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
            if doc_id not in store.list_doc_ids():
                typer.secho(_missing_doc_message(doc_id, db_path, store), fg=typer.colors.RED, err=True)
                raise typer.Exit(code=1)
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
    else:
        typer.echo(f"Database: {payload['db_path']}")
    for name, path in paths.items():
        typer.echo(f"{name}: {path}")


def _build_llm_config(
    *,
    api_key: Optional[str],
    base_url: Optional[str],
    model: Optional[str],
    enable_thinking: bool,
) -> LLMConfig:
    try:
        return resolve_llm_config(
            api_key=api_key,
            base_url=base_url,
            model=model,
            enable_thinking=enable_thinking,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _print_summary(payload: dict) -> None:
    typer.echo(f"doc_id: {payload['doc_id']}")
    typer.echo(f"compounds: {payload['n_compounds']}")
    typer.echo(f"unique_compounds: {payload['n_unique_compounds']}")
    typer.echo(f"markush: {payload['n_markush']}")
    typer.echo(f"invalid: {payload['n_invalid']}")
    if "n_with_activities" in payload:
        typer.echo(f"with_activities: {payload['n_with_activities']}")
    if "n_enriched" in payload:
        typer.echo(f"enriched: {payload['n_enriched']}")
    if "skip_enrich" in payload:
        typer.echo(f"skip_enrich: {payload['skip_enrich']}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
