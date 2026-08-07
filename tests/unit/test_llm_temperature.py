from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import uniparser_agent.llm.client as client_module
from uniparser_agent.llm.client import OpenAICompatLLM


class _Completions:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.kwargs = kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])


class _OpenAI:
    instance: "_OpenAI | None" = None

    def __init__(self, **kwargs: Any) -> None:
        self.init_kwargs = kwargs
        self.completions = _Completions()
        self.chat = SimpleNamespace(completions=self.completions)
        _OpenAI.instance = self


@pytest.fixture
def fake_openai(monkeypatch: pytest.MonkeyPatch) -> type[_OpenAI]:
    monkeypatch.setattr(client_module, "OpenAI", _OpenAI)
    return _OpenAI


def test_temperature_is_sent_when_configured(fake_openai: type[_OpenAI]) -> None:
    llm = OpenAICompatLLM(
        api_key="sk-test",
        base_url="http://localhost:8000/v1",
        model="test-model",
        temperature=0.0,
    )

    assert llm.chat(system_prompt="system", user_content="user") == "ok"
    assert fake_openai.instance is not None
    assert fake_openai.instance.completions.kwargs is not None
    assert fake_openai.instance.completions.kwargs["temperature"] == 0.0


def test_temperature_is_omitted_when_unconfigured(fake_openai: type[_OpenAI]) -> None:
    llm = OpenAICompatLLM(
        api_key="sk-test",
        base_url="http://localhost:8000/v1",
        model="test-model",
    )

    llm.chat(system_prompt="system", user_content="user")

    assert fake_openai.instance is not None
    assert fake_openai.instance.completions.kwargs is not None
    assert "temperature" not in fake_openai.instance.completions.kwargs
