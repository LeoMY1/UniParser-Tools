"""Tests for LLM response parsing and QA merge."""

from __future__ import annotations

from uniparser_agent.pdf2qa.output_parser import parse_llm_response
from uniparser_agent.pdf2qa.qa_merger import merge_qa_pairs


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
        "<qa_pair><label>1</label><question>1,2</question>"
        "<answer>B</answer><solution>3,4</solution></qa_pair>"
        "</chapter>"
    )
    extracted = parse_llm_response(response, content)
    assert len(extracted) == 1
    assert "What is 1+1?" in extracted[0]["question"]
    assert extracted[0]["answer"] == "B"
    merged = merge_qa_pairs(extracted)
    assert len(merged) == 1
    assert merged[0]["label"] == 1
    assert "1+1=2" in merged[0]["solution"]
