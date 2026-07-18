"""End-to-end QA pipeline: UniParser parse → adapt → LLM extract → merge."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from uniparser_agent.parse.service import load_pages_tree, parse_document
from uniparser_agent.pdf2qa.layout_adapter import adapt_pages_tree_file
from uniparser_agent.pdf2qa.llm_client import QALLMClient
from uniparser_agent.pdf2qa.output_parser import parse_llm_response, write_qa_jsonl
from uniparser_agent.pdf2qa.prompts import build_qa_extract_prompt
from uniparser_agent.pdf2qa.qa_merger import jsonl_to_md, merge_qa_pairs, write_merged_jsonl


def _resolve_output_dir(output_dir: str | Path | None, overwrite: bool) -> Path:
    if output_dir:
        out = Path(output_dir).expanduser().resolve()
    else:
        out = (Path.cwd() / "qa_out").resolve()
    if out.exists():
        if not overwrite:
            raise FileExistsError(
                f"Output directory already exists: {out}. Pass overwrite=True or --overwrite."
            )
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    return out


def run_qa_pipeline(
    input_path: str | None = None,
    *,
    pages_tree_path: str | None = None,
    output_dir: str | None = None,
    overwrite: bool = False,
    strict_title_match: bool = False,
) -> dict[str, Any]:
    """Run pdf2qa extraction.

    Primary path: ``input_path`` (pdf/url/image) → UniParser parse → extract.
    Bypass: ``pages_tree_path`` skips UniParser parse.
    """
    if not input_path and not pages_tree_path:
        raise ValueError("Provide input_path (pdf/url/image) or pages_tree_path.")

    started = time.time()
    out = _resolve_output_dir(output_dir, overwrite=overwrite)
    parse_dir = out / "parse"
    parse_meta: dict[str, Any] = {}

    if pages_tree_path:
        src_tree = Path(pages_tree_path).expanduser().resolve()
        if not src_tree.is_file():
            raise FileNotFoundError(f"pages_tree not found: {src_tree}")
        parse_dir.mkdir(parents=True, exist_ok=True)
        dest_tree = parse_dir / "pages_tree.json"
        shutil.copy2(src_tree, dest_tree)
        tree_path = dest_tree
        parse_meta = {"mode": "pages_tree", "pages_tree_path": str(tree_path)}
    else:
        assert input_path is not None
        parse_result = parse_document(input_path, output_dir=str(parse_dir), overwrite=True)
        tree_path = Path(parse_result["pages_tree_path"])
        parse_meta = {
            "mode": "parse",
            "source": input_path,
            "token": parse_result.get("token", ""),
            "pages_tree_path": parse_result["pages_tree_path"],
            "markdown_path": parse_result.get("markdown_path", ""),
        }

    load_pages_tree(tree_path)

    content_list_path = out / "llm_content_list.json"
    content_list = adapt_pages_tree_file(tree_path, content_list_path)

    llm = QALLMClient()
    system_prompt = build_qa_extract_prompt()
    user_content = json.dumps(content_list, ensure_ascii=False)
    llm_started = time.time()
    raw_response = llm.chat(system_prompt=system_prompt, user_content=user_content)
    llm_elapsed = time.time() - llm_started

    raw_path = out / "llm_raw_response.txt"
    raw_path.write_text(raw_response, encoding="utf-8")

    extracted = parse_llm_response(raw_response, content_list)
    extracted_path = out / "extracted_qa.jsonl"
    write_qa_jsonl(extracted, extracted_path)

    merged = merge_qa_pairs(extracted, strict_title_match=strict_title_match)
    merged_jsonl = out / "merged_qa_pairs.jsonl"
    merged_md = out / "merged_qa_pairs.md"
    write_merged_jsonl(merged, merged_jsonl)
    jsonl_to_md(merged_jsonl, merged_md)

    meta = {
        "parse": parse_meta,
        "llm": llm.meta(),
        "n_content_items": len(content_list),
        "n_extracted": len(extracted),
        "n_merged_qa": len(merged),
        "llm_elapsed_sec": round(llm_elapsed, 2),
        "total_elapsed_sec": round(time.time() - started, 2),
        "paths": {
            "output_dir": str(out),
            "pages_tree": str(tree_path),
            "llm_content_list": str(content_list_path),
            "llm_raw_response": str(raw_path),
            "extracted_qa": str(extracted_path),
            "merged_qa_pairs_jsonl": str(merged_jsonl),
            "merged_qa_pairs_md": str(merged_md),
        },
    }
    meta_path = out / "run_meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    meta["paths"]["run_meta"] = str(meta_path)
    return meta


run_vqa_pipeline = run_qa_pipeline
