"""OpenAI-compatible LLM client for VQA extraction (Volcengine Ark by default)."""

from __future__ import annotations

import os
from typing import Any

from openai import OpenAI

# Default: Volcengine Ark (intranet Qwen can override via env).
DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_MODEL = "glm-5-2-260617"
DEFAULT_TIMEOUT = 3600.0
DEFAULT_MAX_TOKENS = 81920


def get_llm_api_key() -> str:
    key = (
        os.environ.get("VQA_LLM_API_KEY")
        or os.environ.get("ARK_API_KEY")
        or ""
    ).strip()
    if not key:
        raise ValueError("VQA_LLM_API_KEY or ARK_API_KEY is not set.")
    return key


def get_llm_base_url() -> str:
    return (os.environ.get("VQA_LLM_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")


def get_llm_model() -> str:
    return (os.environ.get("VQA_LLM_MODEL") or DEFAULT_MODEL).strip()


def _use_qwen_thinking_kwargs(base_url: str) -> bool:
    """Only send Qwen chat_template_kwargs for non-Ark / explicitly enabled setups."""
    flag = (os.environ.get("VQA_LLM_ENABLE_THINKING_KWARGS") or "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return True
    if flag in {"0", "false", "no"}:
        return False
    return "192.168." in base_url or "qwen" in (os.environ.get("VQA_LLM_MODEL") or "").lower()


class VQALLMClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        enable_thinking: bool = False,
    ) -> None:
        self.api_key = api_key if api_key is not None else get_llm_api_key()
        self.base_url = (base_url or get_llm_base_url()).rstrip("/")
        self.model = model or get_llm_model()
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.enable_thinking = enable_thinking
        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=timeout)

    def chat(self, *, system_prompt: str, user_content: str) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": self.max_tokens,
        }
        if _use_qwen_thinking_kwargs(self.base_url):
            kwargs["extra_body"] = {
                "chat_template_kwargs": {"enable_thinking": self.enable_thinking},
            }
        response = self._client.chat.completions.create(**kwargs)
        message = response.choices[0].message
        content = message.content
        if content is None:
            raise RuntimeError("LLM returned empty content")
        return content

    def meta(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "model": self.model,
            "timeout": self.timeout,
            "max_tokens": self.max_tokens,
            "enable_thinking": self.enable_thinking,
        }
