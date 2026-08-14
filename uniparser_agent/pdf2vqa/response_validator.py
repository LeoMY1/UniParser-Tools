"""Validate agent-authored pdf2vqa XML-like responses."""

from __future__ import annotations

import re
from typing import Any, Sequence


_CHAPTER_RE = re.compile(r"<chapter>(.*?)</chapter>", flags=re.DOTALL)
_PAIR_RE = re.compile(r"<vqa_pair>(.*?)</vqa_pair>", flags=re.DOTALL)
_EMPTY_RE = re.compile(r"<empty>\s*</empty>", flags=re.DOTALL)
_ID_LIST_RE = re.compile(r"\d+(?:\s*,\s*\d+)*")


def _issue(response_index: int, code: str, message: str) -> dict[str, Any]:
    return {
        "response_index": response_index,
        "code": code,
        "message": message,
    }


def _tag_values(body: str, tag: str) -> list[str]:
    return re.findall(rf"<{tag}>(.*?)</{tag}>", body, flags=re.DOTALL)


def _validate_id_field(
    value: str,
    *,
    tag: str,
    response_index: int,
    allowed_ids: set[int],
    errors: list[dict[str, Any]],
) -> None:
    stripped = value.strip()
    if not stripped:
        return
    if _ID_LIST_RE.fullmatch(stripped) is None:
        errors.append(
            _issue(
                response_index,
                "invalid_id_list",
                f"<{tag}> must contain only comma-separated numeric content ids: {stripped!r}",
            )
        )
        return
    unknown = sorted({int(raw_id.strip()) for raw_id in stripped.split(",")} - allowed_ids)
    if unknown:
        errors.append(
            _issue(
                response_index,
                "unknown_content_id",
                f"<{tag}> references unknown content ids: {unknown}",
            )
        )


def validate_vqa_responses(
    responses: Sequence[str],
    content_list: list[dict[str, Any]],
    *,
    expected_count: int | None = None,
) -> dict[str, Any]:
    """Return a machine-readable validation report without modifying responses."""
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    allowed_ids = {
        int(item["id"]) for item in content_list if isinstance(item, dict) and isinstance(item.get("id"), int)
    }

    if expected_count is not None and len(responses) != expected_count:
        errors.append(
            _issue(
                0,
                "response_count_mismatch",
                f"Expected {expected_count} response files, found {len(responses)}.",
            )
        )

    for response_index, response in enumerate(responses, start=1):
        if not response.strip():
            errors.append(_issue(response_index, "empty_response", "Response file is empty."))
            continue
        if "```" in response:
            errors.append(
                _issue(
                    response_index,
                    "markdown_code_fence",
                    "Return raw XML-like tags without Markdown code fences.",
                )
            )

        chapters = _CHAPTER_RE.findall(response)
        empty_blocks = _EMPTY_RE.findall(response)
        if chapters and empty_blocks:
            errors.append(
                _issue(
                    response_index,
                    "mixed_empty_and_chapter",
                    "Do not combine <empty></empty> with <chapter> blocks.",
                )
            )
        if not chapters and not empty_blocks:
            errors.append(
                _issue(
                    response_index,
                    "missing_top_level_block",
                    "Response must contain <chapter>...</chapter> or <empty></empty>.",
                )
            )

        remainder = _CHAPTER_RE.sub("", response)
        remainder = _EMPTY_RE.sub("", remainder)
        if remainder.strip().replace("```xml", "").replace("```", "").strip():
            errors.append(
                _issue(
                    response_index,
                    "text_outside_top_level_block",
                    "Response contains text outside <chapter> or <empty> blocks.",
                )
            )

        for chapter in chapters:
            titles = _tag_values(chapter, "title")
            pairs = _PAIR_RE.findall(chapter)
            if len(titles) != 1:
                errors.append(
                    _issue(
                        response_index,
                        "invalid_title_count",
                        f"Each <chapter> must contain exactly one <title>; found {len(titles)}.",
                    )
                )
            elif titles:
                _validate_id_field(
                    titles[0],
                    tag="title",
                    response_index=response_index,
                    allowed_ids=allowed_ids,
                    errors=errors,
                )
            if not pairs:
                errors.append(
                    _issue(
                        response_index,
                        "missing_vqa_pair",
                        "Each <chapter> must contain at least one <vqa_pair>.",
                    )
                )

            chapter_remainder = re.sub(r"<title>.*?</title>", "", chapter, flags=re.DOTALL)
            chapter_remainder = _PAIR_RE.sub("", chapter_remainder)
            if chapter_remainder.strip():
                errors.append(
                    _issue(
                        response_index,
                        "text_outside_vqa_pair",
                        "A <chapter> contains text outside its <title> and <vqa_pair> blocks.",
                    )
                )

            for pair in pairs:
                for tag in ("label", "question", "answer", "solution"):
                    values = _tag_values(pair, tag)
                    if len(values) != 1:
                        errors.append(
                            _issue(
                                response_index,
                                f"invalid_{tag}_count",
                                f"Each <vqa_pair> must contain exactly one <{tag}>; found {len(values)}.",
                            )
                        )
                    if tag in {"question", "solution"} and len(values) == 1:
                        _validate_id_field(
                            values[0],
                            tag=tag,
                            response_index=response_index,
                            allowed_ids=allowed_ids,
                            errors=errors,
                        )

                pair_remainder = pair
                for tag in ("label", "question", "answer", "solution"):
                    pair_remainder = re.sub(rf"<{tag}>.*?</{tag}>", "", pair_remainder, flags=re.DOTALL)
                if pair_remainder.strip():
                    errors.append(
                        _issue(
                            response_index,
                            "text_outside_pair_fields",
                            "A <vqa_pair> contains text outside label/question/answer/solution fields.",
                        )
                    )

                question = _tag_values(pair, "question")
                answer = _tag_values(pair, "answer")
                solution = _tag_values(pair, "solution")
                if (
                    question
                    and answer
                    and solution
                    and not any(value.strip() for value in (question[0], answer[0], solution[0]))
                ):
                    warnings.append(
                        _issue(
                            response_index,
                            "empty_vqa_pair",
                            "The VQA pair has no question, answer, or solution content.",
                        )
                    )

    return {
        "valid": not errors,
        "response_count": len(responses),
        "expected_response_count": expected_count,
        "errors": errors,
        "warnings": warnings,
    }


__all__ = ["validate_vqa_responses"]
