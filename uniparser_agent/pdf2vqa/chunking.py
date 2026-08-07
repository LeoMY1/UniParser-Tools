"""Token-based input chunking compatible with DataFlow-VQA."""

from __future__ import annotations

import tiktoken


MAX_CHUNK_TOKENS = 32000
_ENCODING = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Count tokens using the same encoding as DataFlow-VQA."""
    return len(_ENCODING.encode(text))


def split_text_by_tokens(text: str, *, max_tokens: int = MAX_CHUNK_TOKENS) -> list[str]:
    """Recursively bisect raw text until every chunk fits the token limit."""
    if max_tokens <= 0:
        raise ValueError("max_tokens must be greater than zero")
    if count_tokens(text) <= max_tokens or len(text) <= 1:
        return [text]

    midpoint = len(text) // 2
    return split_text_by_tokens(text[:midpoint], max_tokens=max_tokens) + split_text_by_tokens(
        text[midpoint:], max_tokens=max_tokens
    )
