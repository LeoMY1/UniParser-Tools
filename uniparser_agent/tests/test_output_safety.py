"""Regression tests for safe output replacement."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from uniparser_agent.output_dir import default_parse_output_dir, replace_output_dir
from uniparser_agent.parse import service as parse_service
from uniparser_agent.pdf2vqa.pipeline import run_vqa_pipeline


class _TriggerFailureClient:
    def trigger_url(self, _url: str) -> dict[str, str]:
        return {"status": "error", "message": "trigger failed"}


class _LLMFailureClient:
    def chat(self, *, system_prompt: str, user_content: str) -> str:
        raise RuntimeError("LLM failed")


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


@pytest.mark.parametrize("source_stem", ["", ".", "..", "../escape", r"..\escape"])
def test_default_parse_output_rejects_unsafe_source_stem(source_stem: str) -> None:
    with pytest.raises(ValueError, match="Unsafe source name"):
        default_parse_output_dir(source_stem)


def test_default_parse_output_is_contained_in_managed_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    output = default_parse_output_dir("exam")

    assert output == (tmp_path / "Uni-Parser-Skill" / "exam").resolve()


def test_parse_url_traversal_is_rejected_before_client_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_client() -> None:
        raise AssertionError("client must not be created")

    monkeypatch.setattr(parse_service, "make_client", unexpected_client)
    with pytest.raises(ValueError, match="Unsafe source name"):
        parse_service.parse_document("https://example.com/..")


def test_output_replacement_does_not_restore_previous_directory_on_failure(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    (output / "previous.txt").write_text("previous", encoding="utf-8")

    with pytest.raises(RuntimeError, match="failed"):
        with replace_output_dir(output, overwrite=True) as work_dir:
            (work_dir / "partial.txt").write_text("partial", encoding="utf-8")
            raise RuntimeError("failed")

    assert not (output / "previous.txt").exists()
    assert (output / "partial.txt").read_text(encoding="utf-8") == "partial"
    assert not list(tmp_path.glob(".output.backup-*"))


def test_output_replacement_commits_successful_run(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    (output / "previous.txt").write_text("previous", encoding="utf-8")

    with replace_output_dir(output, overwrite=True) as work_dir:
        (work_dir / "current.txt").write_text("current", encoding="utf-8")

    assert not (output / "previous.txt").exists()
    assert (output / "current.txt").read_text(encoding="utf-8") == "current"
    assert not list(tmp_path.glob(".output.backup-*"))


def test_failed_new_output_is_left_for_diagnostics(tmp_path: Path) -> None:
    output = tmp_path / "output"

    with pytest.raises(RuntimeError, match="failed"):
        with replace_output_dir(output, overwrite=False) as work_dir:
            (work_dir / "partial.txt").write_text("partial", encoding="utf-8")
            raise RuntimeError("failed")

    assert (output / "partial.txt").read_text(encoding="utf-8") == "partial"


def test_parse_failure_keeps_partial_output_without_restoring_previous(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "parse"
    output.mkdir()
    (output / "previous.txt").write_text("previous", encoding="utf-8")
    monkeypatch.setattr(parse_service, "make_client", _TriggerFailureClient)

    with pytest.raises(RuntimeError, match="trigger failed"):
        parse_service.parse_document(
            "https://example.com/exam.pdf",
            output_dir=str(output),
            overwrite=True,
        )

    assert not (output / "previous.txt").exists()
    assert (output / "trigger_error.json").is_file()
    assert not list(tmp_path.glob(".parse.backup-*"))


def test_vqa_validates_pages_tree_before_replacing_output(tmp_path: Path) -> None:
    output = tmp_path / "vqa"
    output.mkdir()
    (output / "previous.txt").write_text("previous", encoding="utf-8")
    invalid_tree = tmp_path / "invalid.json"
    invalid_tree.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="missing pages_tree key"):
        run_vqa_pipeline(
            pages_tree_path=str(invalid_tree),
            output_dir=str(output),
            overwrite=True,
            llm_client=_LLMFailureClient(),  # type: ignore[arg-type]
        )

    assert (output / "previous.txt").read_text(encoding="utf-8") == "previous"


def test_vqa_failure_keeps_partial_output_without_restoring_previous(tmp_path: Path) -> None:
    output = tmp_path / "vqa"
    output.mkdir()
    (output / "previous.txt").write_text("previous", encoding="utf-8")
    pages_tree = tmp_path / "pages_tree.json"
    _write_pages_tree(pages_tree)

    with pytest.raises(RuntimeError, match="LLM failed"):
        run_vqa_pipeline(
            pages_tree_path=str(pages_tree),
            output_dir=str(output),
            overwrite=True,
            llm_client=_LLMFailureClient(),  # type: ignore[arg-type]
        )

    assert not (output / "previous.txt").exists()
    assert (output / "parse" / "pages_tree.json").is_file()
    assert (output / "llm_content_list.json").is_file()
    assert not list(tmp_path.glob(".vqa.backup-*"))
