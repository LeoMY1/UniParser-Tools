"""Prepare and finalize pdf2vqa runs around an agent-native inference stage."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from uniparser_agent.output_dir import create_unique_output_dir, resolve_output_dir
from uniparser_agent.parse.api_client import resolve_input
from uniparser_agent.parse.service import load_pages_tree, parse_document
from uniparser_agent.pdf2vqa.chunking import MAX_CHUNK_TOKENS, count_tokens, split_text_by_tokens
from uniparser_agent.pdf2vqa.layout_adapter import adapt_pages_tree_file
from uniparser_agent.pdf2vqa.output_parser import parse_llm_response, write_vqa_jsonl
from uniparser_agent.pdf2vqa.pdf_merger import merge_pdfs
from uniparser_agent.pdf2vqa.prompts import build_vqa_extract_prompt
from uniparser_agent.pdf2vqa.response_validator import validate_vqa_responses
from uniparser_agent.pdf2vqa.vqa_formatter import write_sharegpt
from uniparser_agent.pdf2vqa.vqa_merger import jsonl_to_md, merge_vqa_pairs, write_merged_jsonl


PREPARE_SCHEMA_VERSION = 1
SYSTEM_PROMPT = "You are a helpful assistant"
_SYSTEM_MARKER = "<!-- PDF2VQA_SYSTEM_PROMPT -->"
_USER_MARKER = "<!-- PDF2VQA_USER_PROMPT -->"


def _resolve_output_dir(output_dir: str | Path | None) -> Path:
    return resolve_output_dir(output_dir, default=Path.cwd() / "vqa_out")


def _require_local_pdf(path: str | Path, *, label: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"{label} not found: {resolved}")
    if resolved.suffix.lower() != ".pdf":
        raise ValueError(f"{label} must be a local PDF file: {resolved}")
    return resolved


def _write_agent_request(path: Path, *, system_prompt: str, user_content: str) -> None:
    request = f"{_SYSTEM_MARKER}\n{system_prompt}\n{_USER_MARKER}\n{user_content}"
    path.write_text(request, encoding="utf-8")


def load_agent_request(path: str | Path) -> tuple[str, str]:
    """Read one staged request without changing its original prompt text."""
    request_path = Path(path).expanduser().resolve()
    payload = request_path.read_text(encoding="utf-8")
    system_prefix = f"{_SYSTEM_MARKER}\n"
    user_separator = f"\n{_USER_MARKER}\n"
    if not payload.startswith(system_prefix) or user_separator not in payload:
        raise ValueError(f"Invalid pdf2vqa agent request: {request_path}")
    system_prompt, user_content = payload[len(system_prefix) :].split(user_separator, maxsplit=1)
    return system_prompt, user_content


def _load_prepare_meta(run_dir: str | Path) -> tuple[Path, dict[str, Any]]:
    resolved_run_dir = Path(run_dir).expanduser().resolve()
    meta_path = resolved_run_dir / "prepare_meta.json"
    if not meta_path.is_file():
        raise FileNotFoundError(f"prepare_meta.json not found: {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("schema_version") != PREPARE_SCHEMA_VERSION:
        raise ValueError(f"Unsupported pdf2vqa prepare schema: {meta.get('schema_version')!r}")
    if Path(meta.get("paths", {}).get("output_dir", "")).resolve() != resolved_run_dir:
        raise ValueError(f"prepare_meta.json does not belong to run directory: {resolved_run_dir}")
    for key, raw_path in meta.get("paths", {}).items():
        candidate = Path(raw_path).expanduser().resolve()
        if not candidate.is_relative_to(resolved_run_dir):
            raise ValueError(f"Prepared path {key!r} escapes the run directory: {candidate}")
    requests = meta.get("requests")
    if not isinstance(requests, list):
        raise ValueError("prepare_meta.json is missing its requests list")
    expected_indices = list(range(1, len(requests) + 1))
    actual_indices = [request.get("index") for request in requests if isinstance(request, dict)]
    if actual_indices != expected_indices:
        raise ValueError(f"Prepared request indices are not consecutive: {actual_indices}")
    for request in requests:
        for key in ("request_path", "response_path"):
            candidate = Path(request[key]).expanduser().resolve()
            if not candidate.is_relative_to(resolved_run_dir):
                raise ValueError(f"Prepared request path {key!r} escapes the run directory: {candidate}")
    return resolved_run_dir, meta


def prepare_vqa_pipeline(
    input_path: str | None = None,
    *,
    answer_pdf: str | None = None,
    pages_tree_path: str | None = None,
    output_dir: str | None = None,
    strict_title_match: bool = False,
    chunker: Callable[..., list[str]] = split_text_by_tokens,
) -> dict[str, Any]:
    """Parse and stage requests without invoking an LLM."""
    if answer_pdf and pages_tree_path:
        raise ValueError("Use either answer_pdf or pages_tree_path, not both.")
    if answer_pdf and not input_path:
        raise ValueError("answer_pdf requires input_path (question booklet PDF).")
    if not input_path and not pages_tree_path:
        raise ValueError("Provide input_path (pdf/url/image) or pages_tree_path.")
    if input_path and pages_tree_path:
        raise ValueError("Use either input_path or pages_tree_path, not both.")

    started = time.time()
    pages_tree_bytes: bytes | None = None
    question_pdf: Path | None = None
    answer_path: Path | None = None
    if pages_tree_path:
        src_tree = Path(pages_tree_path).expanduser().resolve()
        if not src_tree.is_file():
            raise FileNotFoundError(f"pages_tree not found: {src_tree}")
        load_pages_tree(src_tree)
        pages_tree_bytes = src_tree.read_bytes()
    elif answer_pdf:
        assert input_path is not None
        question_pdf = _require_local_pdf(input_path, label="question PDF")
        answer_path = _require_local_pdf(answer_pdf, label="answer PDF")
    else:
        assert input_path is not None
        resolve_input(input_path)

    out = create_unique_output_dir(_resolve_output_dir(output_dir))
    parse_dir = out / "parse"
    parse_meta: dict[str, Any]
    merged_pdf_path: Path | None = None

    if pages_tree_bytes is not None:
        parse_dir.mkdir(parents=True, exist_ok=True)
        tree_path = parse_dir / "pages_tree.json"
        tree_path.write_bytes(pages_tree_bytes)
        parse_meta = {"mode": "pages_tree", "pages_tree_path": str(tree_path)}
    else:
        assert input_path is not None
        parse_source = input_path
        if answer_path is not None:
            assert question_pdf is not None
            merge_dir = out / "merge"
            merge_dir.mkdir(parents=True, exist_ok=True)
            merged_pdf_path = merge_pdfs([question_pdf, answer_path], merge_dir / "merged.pdf")
            parse_source = str(merged_pdf_path)

        parse_result = parse_document(parse_source, output_dir=str(parse_dir))
        tree_path = Path(parse_result["pages_tree_path"])
        if answer_path is not None:
            assert question_pdf is not None and merged_pdf_path is not None
            parse_meta = {
                "mode": "dual_pdf",
                "question_pdf": str(question_pdf),
                "answer_pdf": str(answer_path),
                "merged_pdf": str(merged_pdf_path),
                "token": parse_result.get("token", ""),
                "pages_tree_path": parse_result["pages_tree_path"],
                "markdown_path": parse_result.get("markdown_path", ""),
            }
        else:
            parse_meta = {
                "mode": "parse",
                "source": input_path,
                "token": parse_result.get("token", ""),
                "pages_tree_path": parse_result["pages_tree_path"],
                "markdown_path": parse_result.get("markdown_path", ""),
            }

    load_pages_tree(tree_path)
    images_dir = out / "vqa_images"
    content_list_path = out / "llm_content_list.json"
    content_list = adapt_pages_tree_file(tree_path, content_list_path, images_dir=images_dir)
    n_images = len(list(images_dir.glob("*"))) if images_dir.is_dir() else 0

    extract_prompt = build_vqa_extract_prompt()
    user_content = json.dumps(content_list, ensure_ascii=False)
    chunks = chunker(user_content, max_tokens=MAX_CHUNK_TOKENS)
    requests_dir = out / "agent_requests"
    responses_dir = out / "agent_responses"
    requests_dir.mkdir(parents=True, exist_ok=True)
    responses_dir.mkdir(parents=True, exist_ok=True)

    requests: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        request_path = requests_dir / f"chunk_{index:04d}.md"
        response_path = responses_dir / f"chunk_{index:04d}.txt"
        chunk_user_content = f"{extract_prompt}\n{chunk}"
        _write_agent_request(
            request_path,
            system_prompt=SYSTEM_PROMPT,
            user_content=chunk_user_content,
        )
        requests.append(
            {
                "index": index,
                "request_path": str(request_path),
                "response_path": str(response_path),
                "input_token_count": count_tokens(chunk),
            }
        )

    paths: dict[str, str] = {
        "output_dir": str(out),
        "pages_tree": str(tree_path),
        "llm_content_list": str(content_list_path),
        "vqa_images": str(images_dir),
        "agent_requests": str(requests_dir),
        "agent_responses": str(responses_dir),
        "llm_raw_response": str(out / "llm_raw_response.txt"),
    }
    if merged_pdf_path is not None:
        paths["merged_pdf"] = str(merged_pdf_path)

    meta_path = out / "prepare_meta.json"
    paths["prepare_meta"] = str(meta_path)
    meta: dict[str, Any] = {
        "schema_version": PREPARE_SCHEMA_VERSION,
        "status": "prepared",
        "started_at_epoch": started,
        "strict_title_match": strict_title_match,
        "parse": parse_meta,
        "n_content_items": len(content_list),
        "n_vqa_images": n_images,
        "llm_chunk_count": len(chunks),
        "llm_chunk_max_tokens": MAX_CHUNK_TOKENS,
        "prepare_elapsed_sec": round(time.time() - started, 2),
        "requests": requests,
        "paths": paths,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def _read_response_files(meta: dict[str, Any]) -> list[str]:
    responses: list[str] = []
    for request in meta.get("requests", []):
        response_path = Path(request["response_path"])
        if not response_path.is_file():
            raise FileNotFoundError(f"Agent response not found: {response_path}")
        responses.append(response_path.read_text(encoding="utf-8"))
    return responses


def validate_prepared_vqa_responses(run_dir: str | Path) -> dict[str, Any]:
    """Validate all response files expected by a prepared run."""
    _, meta = _load_prepare_meta(run_dir)
    content_list_path = Path(meta["paths"]["llm_content_list"])
    content_list = json.loads(content_list_path.read_text(encoding="utf-8"))
    missing = [
        request["response_path"] for request in meta.get("requests", []) if not Path(request["response_path"]).is_file()
    ]
    if missing:
        return {
            "valid": False,
            "response_count": len(meta.get("requests", [])) - len(missing),
            "expected_response_count": len(meta.get("requests", [])),
            "errors": [
                {
                    "response_index": 0,
                    "code": "missing_response_files",
                    "message": f"Missing agent response files: {missing}",
                }
            ],
            "warnings": [],
        }
    responses = _read_response_files(meta)
    return validate_vqa_responses(
        responses,
        content_list,
        expected_count=len(meta.get("requests", [])),
    )


def finalize_vqa_pipeline(
    run_dir: str | Path,
    *,
    responses: Sequence[str] | None = None,
    llm_meta: dict[str, Any] | None = None,
    llm_chunk_elapsed_sec: Sequence[float] | None = None,
    llm_elapsed_sec: float | None = None,
    validate: bool = True,
) -> dict[str, Any]:
    """Validate agent responses and run the existing VQA parse/merge/export stages."""
    out, prepare_meta = _load_prepare_meta(run_dir)
    content_list_path = Path(prepare_meta["paths"]["llm_content_list"])
    content_list = json.loads(content_list_path.read_text(encoding="utf-8"))
    resolved_responses = list(responses) if responses is not None else _read_response_files(prepare_meta)
    expected_count = len(prepare_meta.get("requests", []))

    if len(resolved_responses) != expected_count:
        raise ValueError(f"Expected {expected_count} responses, received {len(resolved_responses)}.")

    for request, response in zip(prepare_meta["requests"], resolved_responses, strict=True):
        Path(request["response_path"]).write_text(response, encoding="utf-8")

    raw_response = "\n".join(resolved_responses)
    raw_path = Path(prepare_meta["paths"]["llm_raw_response"])
    raw_path.write_text(raw_response, encoding="utf-8")

    validation = validate_vqa_responses(
        resolved_responses,
        content_list,
        expected_count=expected_count,
    )
    validation_path = out / "response_validation.json"
    validation_path.write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    if validate and not validation["valid"]:
        messages = "; ".join(error["message"] for error in validation["errors"][:5])
        raise ValueError(f"Invalid pdf2vqa agent response: {messages}")

    extracted = parse_llm_response(raw_response, content_list, image_prefix="vqa_images")
    extracted_path = out / "extracted_vqa.jsonl"
    write_vqa_jsonl(extracted, extracted_path)

    merged = merge_vqa_pairs(extracted, strict_title_match=bool(prepare_meta.get("strict_title_match")))
    merged_jsonl = out / "merged_vqa_pairs.jsonl"
    merged_md = out / "merged_vqa_pairs.md"
    write_merged_jsonl(merged, merged_jsonl)
    jsonl_to_md(merged_jsonl, merged_md)

    images_dir = Path(prepare_meta["paths"]["vqa_images"])
    sharegpt_path = out / "vqa_sharegpt.json"
    write_sharegpt(merged, images_dir, sharegpt_path, base_dir=out)

    paths = dict(prepare_meta["paths"])
    paths.update(
        {
            "response_validation": str(validation_path),
            "extracted_vqa": str(extracted_path),
            "merged_vqa_pairs_jsonl": str(merged_jsonl),
            "merged_vqa_pairs_md": str(merged_md),
            "vqa_images": str(images_dir),
            "vqa_sharegpt": str(sharegpt_path),
            "run_meta": str(out / "run_meta.json"),
        }
    )
    meta = {
        "parse": prepare_meta["parse"],
        "llm": llm_meta or {"mode": "agent_native"},
        "n_content_items": prepare_meta["n_content_items"],
        "n_vqa_images": prepare_meta["n_vqa_images"],
        "n_extracted": len(extracted),
        "n_merged_vqa": len(merged),
        "llm_chunk_count": expected_count,
        "llm_chunk_max_tokens": prepare_meta["llm_chunk_max_tokens"],
        "llm_chunk_elapsed_sec": [round(float(value), 2) for value in (llm_chunk_elapsed_sec or [])],
        "llm_elapsed_sec": round(llm_elapsed_sec, 2) if llm_elapsed_sec is not None else None,
        "total_elapsed_sec": round(time.time() - float(prepare_meta["started_at_epoch"]), 2),
        "response_validation": validation,
        "paths": paths,
    }
    Path(paths["run_meta"]).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


__all__ = [
    "PREPARE_SCHEMA_VERSION",
    "SYSTEM_PROMPT",
    "finalize_vqa_pipeline",
    "load_agent_request",
    "prepare_vqa_pipeline",
    "validate_prepared_vqa_responses",
]
