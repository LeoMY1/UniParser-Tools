"""Keep the standalone Agent parse workflow aligned with the main CLI contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from uniparser_agent.parse import service as parse_service
from uniparser_agent.parse import storage as parse_storage
from uniparser_agent.parse.transport import DIRECT_SYNC_UPLOAD_REQUEST_TIMEOUT


class _TriggerClient:
    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.result = result or {"status": "success", "token": "server-token"}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.closed = False

    def trigger_file(self, source: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("file", source, kwargs))
        return dict(self.result)

    def trigger_snip(self, source: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("image", source, kwargs))
        return dict(self.result)

    def trigger_url(self, source: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("url", source, kwargs))
        return dict(self.result)

    def close(self) -> None:
        self.closed = True


def _complete_parse_job(
    _client: object,
    token: str,
    *,
    out_dir: Path,
    source_stem: str,
) -> dict[str, str]:
    return {
        "output_dir": str(out_dir),
        "pages_tree_path": str(out_dir / "pages_tree.json"),
        "markdown_path": str(out_dir / f"{source_stem}.md"),
        "token": token,
    }


def test_local_pdf_uses_server_token_and_direct_upload_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "patent.pdf"
    source.write_bytes(b"%PDF-1.4")
    client = _TriggerClient()
    monkeypatch.setattr(parse_service, "make_client", lambda: client)
    monkeypatch.setattr(parse_service, "complete_parse_job", _complete_parse_job)

    result = parse_service.parse_document(str(source), output_dir=str(tmp_path / "output"))

    assert client.calls == [
        (
            "file",
            str(source),
            {
                "server_generated_token": True,
                "http_timeout": DIRECT_SYNC_UPLOAD_REQUEST_TIMEOUT,
            },
        )
    ]
    meta = json.loads(Path(result["trigger_meta_path"]).read_text(encoding="utf-8"))
    assert meta["token"] == "server-token"
    assert client.closed is True


@pytest.mark.parametrize("source_kind", ["image", "url"])
def test_image_and_url_use_server_generated_tokens(
    source_kind: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if source_kind == "image":
        source = tmp_path / "page.png"
        source.write_bytes(b"image")
        input_value = str(source)
    else:
        input_value = "https://example.com/document.pdf"

    client = _TriggerClient()
    monkeypatch.setattr(parse_service, "make_client", lambda: client)
    monkeypatch.setattr(parse_service, "complete_parse_job", _complete_parse_job)

    parse_service.parse_document(input_value, output_dir=str(tmp_path / "output"))

    assert client.calls[0][0] == source_kind
    assert client.calls[0][2] == {"server_generated_token": True}
    assert client.closed is True


def test_upload_failure_keeps_diagnostic_token_without_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "patent.pdf"
    source.write_bytes(b"%PDF-1.4")
    client = _TriggerClient(
        {
            "status": "error",
            "token": "diagnostic-token",
            "description": "The write operation timed out",
            "error_type": "WriteTimeout",
        }
    )
    monkeypatch.setattr(parse_service, "make_client", lambda: client)

    with pytest.raises(RuntimeError, match="write operation timed out"):
        parse_service.parse_document(str(source), output_dir=str(tmp_path / "output"))

    error = json.loads((tmp_path / "output" / "trigger_error.json").read_text(encoding="utf-8"))
    assert error["error_code"] == "UPLOAD_ERROR"
    assert error["token"] == "diagnostic-token"
    assert not (tmp_path / "output" / "trigger_meta.json").exists()
    assert client.closed is True


class _PollClient:
    def __init__(self, results: list[dict[str, Any]]) -> None:
        self.results = list(results)
        self.calls = 0

    def get_result(self, _token: str, *, pages_tree: bool = False) -> dict[str, Any]:
        assert pages_tree is False
        self.calls += 1
        return self.results.pop(0)


def test_undefined_token_stops_after_three_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _PollClient([{"status": "undefined"}] * 3)
    monkeypatch.setattr(parse_storage.time, "sleep", lambda _: None)

    result = parse_storage.poll_until_success(client, "missing-token")  # type: ignore[arg-type]

    assert result["status"] == "error"
    assert result["error_code"] == "TOKEN_NOT_FOUND"
    assert result["token"] == "missing-token"
    assert result["attempts"] == 3
    assert client.calls == 3


def test_pending_status_resets_undefined_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _PollClient(
        [
            {"status": "undefined"},
            {"status": "waiting"},
            {"status": "undefined"},
            {"status": "undefined"},
            {"status": "success"},
        ]
    )
    monkeypatch.setattr(parse_storage.time, "sleep", lambda _: None)

    result = parse_storage.poll_until_success(client, "server-token")  # type: ignore[arg-type]

    assert result == {"status": "success"}
    assert client.calls == 5
