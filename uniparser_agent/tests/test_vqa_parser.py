"""Tests for LLM response parsing and VQA merge."""

from __future__ import annotations

import json
from pathlib import Path

from uniparser_agent.pdf2vqa.output_parser import parse_llm_response
from uniparser_agent.pdf2vqa.vqa_merger import jsonl_to_md, merge_vqa_pairs


def test_parse_and_merge_contiguous_qa():
    content = [
        {"id": 0, "type": "text", "text": "Chapter Title"},
        {"id": 1, "type": "text", "text": "1. What is 1+1?"},
        {"id": 2, "type": "text", "text": "A. 1 B. 2"},
        {"id": 3, "type": "text", "text": "【答案】B"},
        {"id": 4, "type": "text", "text": "【解析】1+1=2"},
    ]
    response = (
        "<chapter><title>0</title>"
        "<vqa_pair><label>1</label><question>1,2</question>"
        "<answer>B</answer><solution>3,4</solution></vqa_pair>"
        "</chapter>"
    )
    extracted = parse_llm_response(response, content)
    assert len(extracted) == 1
    assert "What is 1+1?" in extracted[0]["question"]
    assert extracted[0]["answer"] == "B"
    merged = merge_vqa_pairs(extracted)
    assert len(merged) == 1
    assert merged[0]["label"] == 1
    assert "1+1=2" in merged[0]["solution"]


def test_merge_question_only_and_answer_only_rows():
    extracted = [
        {
            "label": "1",
            "chapter_title": "1.1",
            "question": "What is 2+2?",
            "answer": "",
            "solution": "",
        },
        {
            "label": "2",
            "chapter_title": "1.1",
            "question": "What is 3+3?",
            "answer": "",
            "solution": "",
        },
        {
            "label": "1",
            "chapter_title": "1.1",
            "question": "",
            "answer": "4",
            "solution": "2+2=4",
        },
        {
            "label": "2",
            "chapter_title": "1.1",
            "question": "",
            "answer": "6",
            "solution": "3+3=6",
        },
    ]
    merged = merge_vqa_pairs(extracted)
    assert len(merged) == 2
    by_label = {item["label"]: item for item in merged}
    assert by_label[1]["question"] == "What is 2+2?"
    assert by_label[1]["answer"] == "4"
    assert "2+2=4" in by_label[1]["solution"]
    assert by_label[2]["answer"] == "6"
    assert "3+3=6" in by_label[2]["solution"]


def test_markdown_formats_formula_answers_as_inline_latex(tmp_path: Path) -> None:
    items = [
        {
            "label": 1,
            "question": "Formula",
            "answer": r"A = -E_{\text{电子}}^{0}(d^{0})^{12}",
            "solution": "",
        },
        {
            "label": 2,
            "question": "Already formatted",
            "answer": r"$\frac{1}{2}$",
            "solution": "",
        },
        {
            "label": 3,
            "question": "Plain text",
            "answer": "Yes",
            "solution": "",
        },
    ]
    jsonl_path = tmp_path / "merged.jsonl"
    jsonl_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items),
        encoding="utf-8",
    )

    md_path = jsonl_to_md(jsonl_path, tmp_path / "merged.md")
    markdown = md_path.read_text(encoding="utf-8")

    assert r"**Answer:** $A = -E_{\text{电子}}^{0}(d^{0})^{12}$" in markdown
    assert r"**Answer:** $\frac{1}{2}$" in markdown
    assert "**Answer:** Yes" in markdown
