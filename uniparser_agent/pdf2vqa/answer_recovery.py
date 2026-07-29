"""Recover exact answer text from LLM-selected source blocks."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher


_COMMAND_RE = re.compile(r"\\[A-Za-z]+|\\.")
_TRANSPARENT_COMMANDS = frozenset(
    {
        r"\left",
        r"\mathbb",
        r"\mathbf",
        r"\mathrm",
        r"\mathit",
        r"\operatorname",
        r"\right",
        r"\text",
        r"\textrm",
    }
)
_IGNORED_COMMANDS = frozenset({r"\!", r"\,", r"\:", r"\;", r"\ ", r"\(", r"\)", r"\[", r"\]"})
_OPERATOR_MAP = {
    "−": "-",
    "–": "-",
    "—": "-",
    "×": "*",
    "÷": "/",
}
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_OPERATOR_RE = re.compile(r"<=|>=|!=|[=+\-*/^_<>]")
_WRAPPER_RE = re.compile(r"\\(?:mathbb|mathbf|mathrm|mathit|operatorname|text|textrm)\s*\{([^{}]*)\}")


def _canonicalize_with_map(text: str) -> tuple[str, list[tuple[int, int]]]:
    canonical: list[str] = []
    positions: list[tuple[int, int]] = []
    index = 0

    while index < len(text):
        char = text[index]
        if char == "\\":
            match = _COMMAND_RE.match(text, index)
            if match:
                command = match.group()
                if command in _TRANSPARENT_COMMANDS or command in _IGNORED_COMMANDS:
                    index = match.end()
                    continue
                for command_char in command:
                    canonical.append(command_char)
                    positions.append((index, match.end()))
                index = match.end()
                continue

        if char.isspace() or char in "{}$":
            index += 1
            continue

        normalized = unicodedata.normalize("NFKC", _OPERATOR_MAP.get(char, char))
        for normalized_char in normalized:
            canonical.append(normalized_char)
            positions.append((index, index + 1))
        index += 1

    return "".join(canonical), positions


def _semantic_signature(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return tuple(_NUMBER_RE.findall(text)), tuple(_OPERATOR_RE.findall(text))


def _original_slice(
    source: str,
    positions: list[tuple[int, int]],
    start: int,
    end: int,
) -> str:
    original_start = positions[start][0]
    original_end = positions[end - 1][1]
    selected = source[original_start:original_end]

    for wrapper in _WRAPPER_RE.finditer(source):
        if wrapper.start(1) <= original_start and original_end <= wrapper.end(1):
            selected_canonical, _ = _canonicalize_with_map(selected)
            wrapper_canonical, _ = _canonicalize_with_map(wrapper.group(1))
            if selected_canonical == wrapper_canonical:
                original_start = wrapper.start()
                original_end = wrapper.end()
                break

    brace_balance = source[original_start:original_end].count("{") - source[original_start:original_end].count("}")
    while brace_balance > 0 and original_end < len(source):
        char = source[original_end]
        if char.isspace():
            original_end += 1
            continue
        if char != "}":
            break
        original_end += 1
        brace_balance -= 1

    return source[original_start:original_end].strip()


def _exact_canonical_match(
    answer: str,
    source: str,
) -> str | None:
    canonical_answer, _ = _canonicalize_with_map(answer)
    canonical_source, positions = _canonicalize_with_map(source)
    if not canonical_answer or not canonical_source:
        return None

    starts: list[int] = []
    offset = 0
    while True:
        start = canonical_source.find(canonical_answer, offset)
        if start < 0:
            break
        starts.append(start)
        offset = start + 1

    if not starts:
        return None
    recovered = {_original_slice(source, positions, start, start + len(canonical_answer)) for start in starts}
    if len(recovered) == 1:
        return recovered.pop()
    return None


def _fuzzy_canonical_match(
    answer: str,
    source: str,
    *,
    threshold: float,
    uniqueness_margin: float,
) -> str | None:
    canonical_answer, _ = _canonicalize_with_map(answer)
    canonical_source, positions = _canonicalize_with_map(source)
    if not canonical_answer or not canonical_source:
        return None
    if len(canonical_answer) > 2048 or len(canonical_source) > 50000:
        return None

    matcher = SequenceMatcher(None, canonical_answer, canonical_source, autojunk=False)
    starts = {
        max(0, source_start - answer_start)
        for answer_start, source_start, size in matcher.get_matching_blocks()
        if size
    }
    if not starts:
        return None

    target_length = len(canonical_answer)
    delta = max(4, min(20, target_length // 10))
    answer_signature = _semantic_signature(canonical_answer)
    scored: list[tuple[float, int, int]] = []
    for start in starts:
        for length in range(max(1, target_length - delta), target_length + delta + 1):
            end = min(len(canonical_source), start + length)
            if end <= start:
                continue
            candidate = canonical_source[start:end]
            if _semantic_signature(candidate) != answer_signature:
                continue
            score = SequenceMatcher(None, canonical_answer, candidate, autojunk=False).ratio()
            scored.append((score, start, end))

    if not scored:
        return None
    scored.sort(reverse=True)
    best_score, best_start, best_end = scored[0]
    if best_score < threshold:
        return None

    best_text = _original_slice(source, positions, best_start, best_end)
    competing_scores = [
        score for score, start, end in scored[1:] if _original_slice(source, positions, start, end) != best_text
    ]
    if competing_scores and best_score - competing_scores[0] < uniqueness_margin:
        return None
    return best_text


def recover_answer(
    answer: str,
    source: str,
    *,
    fuzzy_threshold: float = 0.95,
    uniqueness_margin: float = 0.03,
) -> str | None:
    """Return an exact source slice matching an LLM-extracted short answer."""
    answer = answer.strip()
    source = source.strip()
    if not answer or not source:
        return None

    exact = _exact_canonical_match(answer, source)
    if exact is not None:
        return exact
    return _fuzzy_canonical_match(
        answer,
        source,
        threshold=fuzzy_threshold,
        uniqueness_margin=uniqueness_margin,
    )
