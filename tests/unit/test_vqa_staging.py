from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from uniparser_agent.cli import app
from uniparser_agent.pdf2vqa.pipeline import run_vqa_pipeline
from uniparser_agent.pdf2vqa.response_validator import validate_vqa_responses
from uniparser_agent.pdf2vqa.staging import (
    finalize_vqa_pipeline,
    load_agent_request,
    prepare_vqa_pipeline,
    validate_prepared_vqa_responses,
)


class _StaticLLM:
    def __init__(self, response: str) -> None:
        self.response = response

    def chat(self, *, system_prompt: str, user_content: str) -> str:
        assert system_prompt == "You are a helpful assistant"
        assert "Please now process the provided json" in user_content
        return self.response

    def meta(self) -> dict[str, str]:
        return {"model": "static-test"}


def _write_pages_tree(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "pages_tree": [
                    [
                        {"type": "paragraph", "page": 1, "block": 1, "text": "1. What is 1+1?"},
                        {"type": "paragraph", "page": 1, "block": 2, "text": "Answer: 2 because 1+1=2."},
                    ]
                ]
            }
        ),
        encoding="utf-8",
    )


def _response() -> str:
    return (
        "<chapter><title></title><vqa_pair><label>1</label>"
        "<question>0</question><answer>2</answer><solution>1</solution>"
        "</vqa_pair></chapter>"
    )


def test_staged_and_one_shot_flows_share_final_outputs(tmp_path: Path) -> None:
    pages_tree = tmp_path / "pages_tree.json"
    _write_pages_tree(pages_tree)

    prepared = prepare_vqa_pipeline(
        pages_tree_path=str(pages_tree),
        output_dir=str(tmp_path / "staged"),
    )
    assert prepared["llm_chunk_count"] == 1
    request = prepared["requests"][0]
    system_prompt, user_content = load_agent_request(request["request_path"])
    assert system_prompt == "You are a helpful assistant"
    assert user_content.endswith(
        json.dumps(json.loads((Path(prepared["paths"]["llm_content_list"])).read_text()), ensure_ascii=False)
    )

    Path(request["response_path"]).write_text(_response(), encoding="utf-8")
    report = validate_prepared_vqa_responses(prepared["paths"]["output_dir"])
    assert report["valid"] is True

    staged = finalize_vqa_pipeline(prepared["paths"]["output_dir"])
    one_shot = run_vqa_pipeline(
        pages_tree_path=str(pages_tree),
        output_dir=str(tmp_path / "one-shot"),
        llm_client=_StaticLLM(_response()),  # type: ignore[arg-type]
    )

    assert Path(staged["paths"]["merged_vqa_pairs_jsonl"]).read_text(encoding="utf-8") == Path(
        one_shot["paths"]["merged_vqa_pairs_jsonl"]
    ).read_text(encoding="utf-8")
    assert Path(staged["paths"]["llm_raw_response"]).read_text(encoding="utf-8") == _response()
    assert staged["llm"]["mode"] == "agent_native"
    assert one_shot["llm"]["model"] == "static-test"


def test_response_validator_rejects_wrapped_and_unknown_ids() -> None:
    response = (
        "```xml\n<chapter><title></title><vqa_pair><label>1</label>"
        "<question>0,<img>1</img></question><answer>A</answer><solution>99</solution>"
        "</vqa_pair></chapter>\n```"
    )

    report = validate_vqa_responses(
        [response],
        [{"id": 0, "type": "text", "text": "question"}, {"id": 1, "type": "image"}],
        expected_count=1,
    )

    assert report["valid"] is False
    codes = {error["code"] for error in report["errors"]}
    assert "markdown_code_fence" in codes
    assert "invalid_id_list" in codes
    assert "unknown_content_id" in codes


def test_prepare_validate_finalize_cli_needs_no_llm_configuration(tmp_path: Path) -> None:
    pages_tree = tmp_path / "pages_tree.json"
    _write_pages_tree(pages_tree)
    runner = CliRunner()

    prepared_result = runner.invoke(
        app,
        ["vqa-prepare", "--pages-tree", str(pages_tree), "-o", str(tmp_path / "cli"), "--json"],
        env={"OPENAI_API_KEY": "", "OPENAI_BASE_URL": "", "OPENAI_MODEL": ""},
    )
    assert prepared_result.exit_code == 0, prepared_result.output
    prepared = json.loads(prepared_result.output)
    Path(prepared["requests"][0]["response_path"]).write_text(_response(), encoding="utf-8")

    validation_result = runner.invoke(
        app,
        ["vqa-validate", prepared["paths"]["output_dir"], "--json"],
        env={"OPENAI_API_KEY": "", "OPENAI_BASE_URL": "", "OPENAI_MODEL": ""},
    )
    assert validation_result.exit_code == 0, validation_result.output
    assert json.loads(validation_result.output)["valid"] is True

    finalized_result = runner.invoke(
        app,
        ["vqa-finalize", prepared["paths"]["output_dir"], "--json"],
        env={"OPENAI_API_KEY": "", "OPENAI_BASE_URL": "", "OPENAI_MODEL": ""},
    )
    assert finalized_result.exit_code == 0, finalized_result.output
    assert json.loads(finalized_result.output)["n_merged_vqa"] == 1


def test_prepared_manifest_cannot_redirect_response_writes(tmp_path: Path) -> None:
    pages_tree = tmp_path / "pages_tree.json"
    _write_pages_tree(pages_tree)
    prepared = prepare_vqa_pipeline(
        pages_tree_path=str(pages_tree),
        output_dir=str(tmp_path / "safe"),
    )
    meta_path = Path(prepared["paths"]["prepare_meta"])
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["requests"][0]["response_path"] = str(tmp_path / "outside.txt")
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    try:
        finalize_vqa_pipeline(prepared["paths"]["output_dir"], responses=[_response()])
    except ValueError as exc:
        assert "escapes the run directory" in str(exc)
    else:
        raise AssertionError("tampered response path must be rejected")
