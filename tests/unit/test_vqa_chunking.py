from __future__ import annotations

import json
from pathlib import Path

import pytest

from uniparser_agent.pdf2vqa.chunking import count_tokens, split_text_by_tokens
from uniparser_agent.pdf2vqa.pipeline import run_vqa_pipeline


def test_small_input_remains_one_chunk() -> None:
    assert split_text_by_tokens("short input") == ["short input"]


def test_long_input_is_losslessly_bisected_within_limit() -> None:
    text = "alpha beta gamma delta " * 20

    chunks = split_text_by_tokens(text, max_tokens=10)

    assert len(chunks) > 1
    assert "".join(chunks) == text
    assert all(count_tokens(chunk) <= 10 for chunk in chunks)


def test_invalid_chunk_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        split_text_by_tokens("text", max_tokens=0)


class _ChunkLLM:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def chat(self, *, system_prompt: str, user_content: str) -> str:
        self.calls.append((system_prompt, user_content))
        return "<empty></empty>"

    def meta(self) -> dict[str, object]:
        return {"model": "fake"}


def _write_pages_tree(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "pages_tree": [
                    [
                        {
                            "type": "paragraph",
                            "page": 1,
                            "block": 1,
                            "text": "Question 1",
                        }
                    ]
                ]
            }
        ),
        encoding="utf-8",
    )


def test_pipeline_combines_chunk_responses_in_single_raw_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pages_tree = tmp_path / "pages_tree.json"
    _write_pages_tree(pages_tree)
    client = _ChunkLLM()
    monkeypatch.setattr(
        "uniparser_agent.pdf2vqa.pipeline.split_text_by_tokens",
        lambda text, *, max_tokens: ["chunk-one", "chunk-two"],
    )

    result = run_vqa_pipeline(
        pages_tree_path=str(pages_tree),
        output_dir=str(tmp_path / "vqa"),
        llm_client=client,  # type: ignore[arg-type]
    )

    assert len(client.calls) == 2
    assert all(system == "You are a helpful assistant" for system, _ in client.calls)
    assert client.calls[0][1].endswith("\nchunk-one")
    assert client.calls[1][1].endswith("\nchunk-two")
    raw_path = Path(result["paths"]["llm_raw_response"])
    assert raw_path.read_text(encoding="utf-8") == "<empty></empty>\n<empty></empty>"
    assert result["llm_chunk_count"] == 2
    assert result["llm_chunk_max_tokens"] == 32000
    assert len(result["llm_chunk_elapsed_sec"]) == 2
    assert not (Path(result["paths"]["output_dir"]) / "llm_chunks").exists()
