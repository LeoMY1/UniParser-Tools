from __future__ import annotations

import json
from typing import Optional

import typer

from uniparser_agent.llm import LLMConfig, resolve_llm_config
from uniparser_agent.parse.service import parse_document
from uniparser_agent.pdf2vqa.pipeline import run_vqa_pipeline
from uniparser_agent.pdf2vqa.staging import (
    finalize_vqa_pipeline,
    prepare_vqa_pipeline,
    validate_prepared_vqa_responses,
)


app = typer.Typer(
    name="uniparser-agent",
    help="UniParser document parsing and exam VQA extraction.",
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
