from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import typer

from uniparser_agent.chemistry.general_formula import write_general_formula_outputs
from uniparser_agent.chemistry.patent_basic_info import write_patent_basic_info
from uniparser_agent.chemistry.patent_structure import BlockResolver, build_patent_structure, write_patent_structure
from uniparser_agent.chemistry.pipeline import ingest_pages_tree, run_full_pipeline
from uniparser_agent.llm import LLMConfig, resolve_llm_config
from uniparser_agent.parse.service import load_pages_tree, parse_document
from uniparser_agent.pdf2translate.pipeline import run_translate_pipeline
from uniparser_agent.pdf2vqa.pipeline import run_vqa_pipeline
from uniparser_agent.pdf2vqa.staging import (
    finalize_vqa_pipeline,
    prepare_vqa_pipeline,
    validate_prepared_vqa_responses,
)


app = typer.Typer(
    name="uniparser-agent",
    help="UniParser agent: CN chemistry patents, exam VQA, and PDF translation.",
    no_args_is_help=True,
)


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


@app.command("patent-general-formulas")
def patent_general_formulas_cmd(
    pages_tree_path: str = typer.Argument(..., help="Path to pages_tree.json."),
    doc_id: Optional[str] = typer.Option(None, "--doc-id", help="Patent document identifier."),
    output_dir: Optional[str] = typer.Option(
        None,
        "-o",
        "--output-dir",
        help="Output directory; defaults to the pages_tree.json directory.",
    ),
    skip_llm: bool = typer.Option(
        False,
        "--skip-llm",
        help="Build the Markush inventory/images/Excel without LLM text analysis.",
    ),
    api_key: Optional[str] = typer.Option(None, "--api-key", help="LLM API key.", envvar=[]),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="LLM base URL."),
    model: Optional[str] = typer.Option(None, "--model", help="LLM model name."),
    enable_thinking: bool = typer.Option(
        False,
        "--enable-thinking/--no-enable-thinking",
        help="Pass chat_template_kwargs.enable_thinking for Qwen-compatible servers.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Build the V2 CN-patent Markush general-formula analysis table."""
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

    llm_config = None
    if not skip_llm:
        try:
            llm_config = resolve_llm_config(
                api_key=api_key,
                base_url=base_url,
                model=model,
                enable_thinking=enable_thinking,
            )
        except ValueError:
            skip_llm = True
    outputs = write_general_formula_outputs(
        resolver,
        resolved_doc_id,
        target_dir,
        llm_config=llm_config,
        skip_llm=skip_llm,
    )
    payload = {
        "doc_id": resolved_doc_id,
        "formula_count": outputs.formula_count,
        "occurrence_count": outputs.occurrence_count,
        "image_count": outputs.image_count,
        "chunk_count": outputs.chunk_count,
        "llm_call_count": outputs.llm_call_count,
        "inventory_path": str(outputs.inventory_path),
        "context_chunks_path": str(outputs.context_chunks_path),
        "analysis_path": str(outputs.analysis_path),
        "excel_path": str(outputs.excel_path),
        "summary_path": str(outputs.summary_path),
        "skip_llm": skip_llm,
    }
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    typer.echo(f"General formula analysis: {outputs.analysis_path}")
    typer.echo(f"General formula Excel: {outputs.excel_path}")
    typer.echo(
        f"Markush formulas: {outputs.formula_count}; occurrences: {outputs.occurrence_count}; "
        f"images: {outputs.image_count}; chunks: {outputs.chunk_count}; LLM calls: {outputs.llm_call_count}"
    )


@app.command("ingest")
def ingest_cmd(
    pages_tree_path: str = typer.Argument(..., help="Path to pages_tree.json."),
    doc_id: Optional[str] = typer.Option(None, "--doc-id", help="Patent document identifier."),
    output_dir: Optional[str] = typer.Option(
        None,
        "-o",
        "--output-dir",
        help="Artifact directory; defaults to the pages_tree.json directory.",
    ),
    skip_llm: bool = typer.Option(
        False,
        "--skip-llm",
        help="Build the Markush inventory/images/Excel without LLM text analysis.",
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
    """Create the supported V2 CN-patent artifacts from pages_tree.json."""
    llm_config = None
    if not skip_llm:
        try:
            llm_config = resolve_llm_config(
                api_key=api_key,
                base_url=base_url,
                model=model,
                enable_thinking=enable_thinking,
            )
        except ValueError:
            skip_llm = True
    payload = ingest_pages_tree(
        pages_tree_path,
        doc_id=doc_id,
        output_dir=output_dir,
        skip_llm=skip_llm,
        llm_config=llm_config,
    )
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    _print_patent_summary(payload)


@app.command("run")
def run_cmd(
    input_path: str = typer.Argument(..., help="Local PDF/image path or public PDF URL."),
    doc_id: Optional[str] = typer.Option(None, "--doc-id", help="Patent document identifier."),
    output_dir: Optional[str] = typer.Option(
        None,
        "-o",
        "--output-dir",
        help="Preferred parse output directory; a suffixed sibling is used if occupied.",
    ),
    skip_llm: bool = typer.Option(
        False,
        "--skip-llm",
        help="Build the Markush inventory/images/Excel without LLM text analysis.",
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
    """Parse a document and create the supported V2 CN-patent artifacts."""
    llm_config = None
    if not skip_llm:
        try:
            llm_config = resolve_llm_config(
                api_key=api_key,
                base_url=base_url,
                model=model,
                enable_thinking=enable_thinking,
            )
        except ValueError:
            skip_llm = True
    payload = run_full_pipeline(
        input_path,
        doc_id=doc_id,
        output_dir=output_dir,
        skip_llm=skip_llm,
        llm_config=llm_config,
    )
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    _print_patent_summary(payload)


def _validate_vqa_source_options(
    *,
    input_path: Optional[str],
    answer_pdf: Optional[str],
    pages_tree: Optional[str],
) -> None:
    if answer_pdf and pages_tree:
        raise typer.BadParameter("Use either --answer-pdf or --pages-tree, not both.")
    if answer_pdf and not input_path:
        raise typer.BadParameter("--answer-pdf requires the question booklet as INPUT.")
    if not input_path and not pages_tree:
        raise typer.BadParameter("Provide INPUT (pdf/url/image) or --pages-tree.")
    if input_path and pages_tree:
        raise typer.BadParameter("Use either INPUT or --pages-tree, not both.")


@app.command("vqa-prepare")
def vqa_prepare_cmd(
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
    strict_title_match: bool = typer.Option(
        False,
        "--strict-title-match/--no-strict-title-match",
        help="Require matching chapter titles when question and answer rows are merged.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Parse and stage pdf2vqa requests without invoking an LLM."""
    _validate_vqa_source_options(
        input_path=input_path,
        answer_pdf=answer_pdf,
        pages_tree=pages_tree,
    )
    result = prepare_vqa_pipeline(
        input_path=input_path,
        answer_pdf=answer_pdf,
        pages_tree_path=pages_tree,
        output_dir=output_dir,
        strict_title_match=strict_title_match,
    )
    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    typer.echo(f"Pages tree: {result['paths']['pages_tree']}")
    typer.echo(f"Content list items: {result['n_content_items']}")
    typer.echo(f"VQA images: {result['n_vqa_images']} -> {result['paths']['vqa_images']}")
    typer.echo(f"Agent requests: {result['llm_chunk_count']} -> {result['paths']['agent_requests']}")
    typer.echo(f"Write responses to: {result['paths']['agent_responses']}")
    typer.echo(f"Output directory: {result['paths']['output_dir']}")


@app.command("vqa-validate")
def vqa_validate_cmd(
    run_dir: str = typer.Argument(..., help="Prepared pdf2vqa output directory."),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Validate staged agent responses without producing final VQA files."""
    try:
        report = validate_prepared_vqa_responses(run_dir)
    except (FileNotFoundError, ValueError) as exc:
        if json_output:
            typer.echo(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False, indent=2))
        else:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        status = "valid" if report["valid"] else "invalid"
        typer.echo(f"Response validation: {status}")
        typer.echo(f"Responses: {report['response_count']}/{report['expected_response_count']}")
        for error in report["errors"]:
            typer.echo(f"- chunk {error['response_index']}: {error['message']}")
    if not report["valid"]:
        raise typer.Exit(code=1)


@app.command("vqa-finalize")
def vqa_finalize_cmd(
    run_dir: str = typer.Argument(..., help="Prepared pdf2vqa output directory."),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Validate agent responses and export merged pdf2vqa results."""
    try:
        result = finalize_vqa_pipeline(run_dir)
    except (FileNotFoundError, ValueError) as exc:
        if json_output:
            typer.echo(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False, indent=2))
        else:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    paths = result["paths"]
    typer.echo(f"Merged VQA pairs: {result['n_merged_vqa']}")
    typer.echo(f"JSONL: {paths['merged_vqa_pairs_jsonl']}")
    typer.echo(f"Markdown: {paths['merged_vqa_pairs_md']}")
    typer.echo(f"ShareGPT: {paths['vqa_sharegpt']}")
    typer.echo(f"Output directory: {paths['output_dir']}")


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
    _validate_vqa_source_options(
        input_path=input_path,
        answer_pdf=answer_pdf,
        pages_tree=pages_tree,
    )

    llm_config = _build_llm_config(
        api_key=api_key,
        base_url=base_url,
        model=model,
        enable_thinking=enable_thinking,
        temperature=0.0,
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


def _build_llm_config(
    *,
    api_key: Optional[str],
    base_url: Optional[str],
    model: Optional[str],
    enable_thinking: bool,
    temperature: Optional[float] = None,
) -> LLMConfig:
    try:
        return resolve_llm_config(
            api_key=api_key,
            base_url=base_url,
            model=model,
            enable_thinking=enable_thinking,
            temperature=temperature,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _print_patent_summary(payload: dict[str, Any]) -> None:
    typer.echo(f"doc_id: {payload['doc_id']}")
    typer.echo(f"Pages tree: {payload['pages_tree_path']}")
    if payload.get("markdown_path"):
        typer.echo(f"Markdown: {payload['markdown_path']}")
    typer.echo(f"Patent structure: {payload['patent_structure_path']}")
    typer.echo(f"Patent basic information: {payload['patent_basic_info_path']}")
    typer.echo(f"General formula analysis: {payload['general_formula_analysis_path']}")
    typer.echo(f"General formula Excel: {payload['general_formula_excel_path']}")
    typer.echo(
        "General formulas: "
        f"{payload['formula_count']}; occurrences: {payload['formula_occurrence_count']}; "
        f"images: {payload['formula_image_count']}; chunks: {payload['formula_context_chunk_count']}; "
        f"LLM calls: {payload['formula_llm_call_count']}"
    )
    typer.echo(f"skip_llm: {payload['skip_llm']}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
