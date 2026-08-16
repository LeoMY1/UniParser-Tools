"""Tests for staged pdf2vqa response validation."""

from __future__ import annotations

from uniparser_agent.pdf2vqa.response_validator import validate_vqa_responses


CONTENT = [
    {"id": 0, "type": "text", "text": "Chapter"},
    {"id": 1, "type": "text", "text": "Question"},
    {"id": 2, "type": "text", "text": "Solution"},
]


def test_validator_accepts_canonical_question_type():
    response = (
        "<chapter><title>0</title><vqa_pair><label>1</label>"
        "<question_type>multiple_choice</question_type><question>1</question>"
        "<answer>B</answer><solution>2</solution></vqa_pair></chapter>"
    )

    report = validate_vqa_responses([response], CONTENT, expected_count=1)

    assert report["valid"]


def test_validator_rejects_missing_type_for_separated_pair():
    response = (
        "<chapter><title>0</title><vqa_pair><label>1</label>"
        "<question>1</question><answer></answer><solution></solution>"
        "</vqa_pair></chapter>"
    )

    report = validate_vqa_responses([response], CONTENT, expected_count=1)

    assert not report["valid"]
    assert any(error["code"] == "invalid_question_type_count" for error in report["errors"])


def test_validator_allows_legacy_complete_pair_with_warning():
    response = (
        "<chapter><title>0</title><vqa_pair><label>1</label>"
        "<question>1</question><answer>B</answer><solution>2</solution>"
        "</vqa_pair></chapter>"
    )

    report = validate_vqa_responses([response], CONTENT, expected_count=1)

    assert report["valid"]
    assert any(warning["code"] == "invalid_question_type_count" for warning in report["warnings"])
