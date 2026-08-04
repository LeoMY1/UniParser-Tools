"""Regression tests for pdf2vqa LLM configuration forwarding."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

import uniparser_agent.cli as cli_module
from uniparser_agent.cli import app
from uniparser_agent.llm import LLMConfig
from uniparser_agent.pdf2vqa.llm_client import VQALLMClient


def _config(*, enable_thinking: bool) -> LLMConfig:
    return LLMConfig(
        api_key="sk-test",
        base_url="http://localhost:8000/v1",
        model="test-model",
        enable_thinking=enable_thinking,
    )


def test_preserves_enable_thinking_from_pipeline_config() -> None:
    client = VQALLMClient(config=_config(enable_thinking=True))

    assert client.enable_thinking is True
    assert client.meta()["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": True},
    }


def test_explicit_enable_thinking_override_still_wins() -> None:
    client = VQALLMClient(
        config=_config(enable_thinking=True),
        enable_thinking=False,
    )

    assert client.enable_thinking is False


def test_vqa_cli_enable_thinking_reaches_pipeline_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run_vqa_pipeline(**kwargs: object) -> dict[str, bool]:
        config = kwargs["llm_config"]
        assert isinstance(config, LLMConfig)
        client = VQALLMClient(config=config)
        return {"enable_thinking": client.enable_thinking}

    monkeypatch.setattr(cli_module, "run_vqa_pipeline", fake_run_vqa_pipeline)

    result = CliRunner().invoke(
        app,
        [
            "vqa",
            "--pages-tree",
            "unused.json",
            "--api-key",
            "sk-test",
            "--base-url",
            "http://localhost:8000/v1",
            "--model",
            "test-model",
            "--enable-thinking",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["enable_thinking"] is True
