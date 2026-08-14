"""End-to-end VQA pipeline: prepare → LLM extract → finalize."""

from __future__ import annotations

import time
from typing import Any

from uniparser_agent.llm import LLMConfig
from uniparser_agent.pdf2vqa.chunking import split_text_by_tokens
from uniparser_agent.pdf2vqa.llm_client import VQALLMClient
from uniparser_agent.pdf2vqa.staging import finalize_vqa_pipeline, load_agent_request, prepare_vqa_pipeline


def run_vqa_pipeline(
    input_path: str | None = None,
    *,
    answer_pdf: str | None = None,
    pages_tree_path: str | None = None,
    output_dir: str | None = None,
    strict_title_match: bool = False,
    llm_config: LLMConfig | None = None,
    llm_client: VQALLMClient | None = None,
) -> dict[str, Any]:
    """Run the original one-shot pdf2vqa flow with staged internals."""
    prepared = prepare_vqa_pipeline(
        input_path=input_path,
        answer_pdf=answer_pdf,
        pages_tree_path=pages_tree_path,
        output_dir=output_dir,
        strict_title_match=strict_title_match,
        chunker=split_text_by_tokens,
    )

    llm = llm_client or VQALLMClient(config=llm_config, temperature=0.0)
    llm_started = time.time()
    responses: list[str] = []
    chunk_elapsed: list[float] = []
    for request in prepared["requests"]:
        system_prompt, user_content = load_agent_request(request["request_path"])
        chunk_started = time.time()
        responses.append(llm.chat(system_prompt=system_prompt, user_content=user_content))
        chunk_elapsed.append(time.time() - chunk_started)

    return finalize_vqa_pipeline(
        prepared["paths"]["output_dir"],
        responses=responses,
        llm_meta=llm.meta(),
        llm_chunk_elapsed_sec=chunk_elapsed,
        llm_elapsed_sec=time.time() - llm_started,
        validate=False,
    )


__all__ = ["run_vqa_pipeline"]
