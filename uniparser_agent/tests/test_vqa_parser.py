"""Tests for LLM response parsing and VQA merge."""

from __future__ import annotations

from uniparser_agent.pdf2vqa.output_parser import parse_llm_response
from uniparser_agent.pdf2vqa.vqa_merger import merge_vqa_pairs


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
        "<vqa_pair><label>1</label><question_type>multiple_choice</question_type><question>1,2</question>"
        "<answer>B</answer><solution>3,4</solution></vqa_pair>"
        "</chapter>"
    )
    extracted = parse_llm_response(response, content)
    assert len(extracted) == 1
    assert "What is 1+1?" in extracted[0]["question"]
    assert extracted[0]["answer"] == "B"
    assert extracted[0]["question_type"] == "multiple_choice"
    merged = merge_vqa_pairs(extracted)
    assert len(merged) == 1
    assert merged[0]["label"] == 1
    assert "1+1=2" in merged[0]["solution"]


def test_merge_question_only_and_answer_only_rows():
    extracted = [
        {
            "label": "1",
            "question_type": "calculation",
            "chapter_title": "1.1",
            "question": "What is 2+2?",
            "answer": "",
            "solution": "",
        },
        {
            "label": "2",
            "question_type": "calculation",
            "chapter_title": "1.1",
            "question": "What is 3+3?",
            "answer": "",
            "solution": "",
        },
        {
            "label": "1",
            "question_type": "calculation",
            "chapter_title": "1.1",
            "question": "",
            "answer": "4",
            "solution": "2+2=4",
        },
        {
            "label": "2",
            "question_type": "calculation",
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


def test_merge_preserves_same_label_across_question_types():
    extracted = []
    for question_type, question, answer in (
        ("true_false", "Statement 1", "True"),
        ("fill_in_the_blank", "Blank 1", "value"),
        ("multiple_choice", "Choice 1", "B"),
    ):
        extracted.extend(
            [
                {
                    "label": "1",
                    "question_type": question_type,
                    "chapter_title": "Chapter 1",
                    "question": question,
                    "answer": "",
                    "solution": "",
                },
                {
                    "label": "1",
                    "question_type": question_type,
                    "chapter_title": "Chapter 1",
                    "question": "",
                    "answer": answer,
                    "solution": "",
                },
            ]
        )

    merged = merge_vqa_pairs(extracted)

    assert len(merged) == 3
    by_type = {item["question_type"]: item for item in merged}
    assert by_type["true_false"]["answer"] == "True"
    assert by_type["fill_in_the_blank"]["answer"] == "value"
    assert by_type["multiple_choice"]["answer"] == "B"
