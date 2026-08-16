"""Canonical question types used by pdf2vqa extraction and pairing."""

from __future__ import annotations


QUESTION_TYPES = (
    "true_false",
    "fill_in_the_blank",
    "multiple_choice",
    "calculation",
    "proof",
    "other",
)
QUESTION_TYPE_SET = frozenset(QUESTION_TYPES)


def normalize_question_type(value: object, *, default: str = "") -> str:
    question_type = str(value or "").strip()
    return question_type if question_type in QUESTION_TYPE_SET else default


__all__ = ["QUESTION_TYPES", "QUESTION_TYPE_SET", "normalize_question_type"]
