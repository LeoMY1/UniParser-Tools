from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from uniparser_tools.cli.core import pipeline
from uniparser_tools.cli.core.input import InputKind, ResolvedInput
from uniparser_tools.cli.core.pipeline import poll_until_success, run_parse, trigger_input


def _local_pdf(path: Path) -> ResolvedInput:
    return ResolvedInput(
        kind=InputKind.FILE,
        source_stem=path.stem,
        raw=str(path),
        path=path,
    )


def test_local_pdf_uses_direct_upload_with_server_token(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    client = MagicMock()
    client.trigger_file.return_value = {"status": "success", "token": "server-token"}

    result, stage = trigger_input(client, _local_pdf(pdf), trigger_kwargs={"sync": True})

    assert result == {"status": "success", "token": "server-token"}
    assert stage == "trigger_file"
    client.trigger_file.assert_called_once_with(
        file_path=str(pdf),
        token=None,
        server_generated_token=True,
        http_timeout=(60.0, 1860.0),
        sync=True,
    )
    client.trigger_url.assert_not_called()


def test_async_local_pdf_uses_direct_upload_timeout(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    client = MagicMock()
    client.trigger_file.return_value = {"status": "success", "token": "server-token"}

    result, stage = trigger_input(client, _local_pdf(pdf), trigger_kwargs={"sync": False})

    assert result == {"status": "success", "token": "server-token"}
    assert stage == "trigger_file"
    client.trigger_file.assert_called_once_with(
        file_path=str(pdf),
        token=None,
        server_generated_token=True,
        http_timeout=(60.0, 60.0),
        sync=False,
    )
    client.trigger_url.assert_not_called()


def test_undefined_waits_past_three_checks_until_deadline(monkeypatch, capsys) -> None:
    client = MagicMock()
    client.get_result.return_value = {"status": "undefined"}
    elapsed = [0]
    monkeypatch.setattr(pipeline.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(pipeline.time, "sleep", lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds))
    monkeypatch.setattr(pipeline, "POLL_TIMEOUT_SEC", 15)

    result = poll_until_success(client, "missing-token")

    assert result == 1
    assert client.get_result.call_count == 5
    assert elapsed[0] == 15
    payload = json.loads(capsys.readouterr().err)
    assert payload["error"]["code"] == "PARSE_ERROR"
    assert "Timed out" in payload["error"]["message"]
    assert payload["token"] == "missing-token"


def test_pending_statuses_still_reach_success(monkeypatch) -> None:
    client = MagicMock()
    client.get_result.side_effect = [
        {"status": "waiting"},
        {"status": "processing"},
        {"status": "success"},
    ]
    monkeypatch.setattr("uniparser_tools.cli.core.pipeline.time.sleep", lambda _: None)

    result = poll_until_success(client, "valid-token")

    assert result == {"status": "success"}
    assert client.get_result.call_count == 3


@pytest.mark.parametrize("trigger_status", ["undefined", "waiting", "processing", "success"])
@pytest.mark.parametrize("kind", list(InputKind))
def test_async_submit_once_polls_same_token_and_saves_one_result(tmp_path, monkeypatch, trigger_status, kind):
    client = MagicMock()
    trigger = {"status": trigger_status, "token": "same-token"}
    for method in (client.trigger_file, client.trigger_snip, client.trigger_url):
        method.return_value = trigger
    client.get_result.side_effect = [
        *[{"status": "undefined"}] * 4,
        {"status": "processing"},
        {"status": "success"},
        {"status": "success", "pages_tree": [[]]},
    ]
    client.get_formatted.return_value = {"status": "success", "content": "# Done"}
    sleeps = []
    monkeypatch.setattr(pipeline.time, "sleep", sleeps.append)
    out = tmp_path / "parse"
    resolved = ResolvedInput(kind, "paper", "paper.pdf", tmp_path / "paper.pdf")
    result = run_parse(client, resolved, out_dir=out, trigger_kwargs={"sync": False})

    assert result["token"] == "same-token"
    assert sum(m.call_count for m in (client.trigger_file, client.trigger_snip, client.trigger_url)) == 1
    assert client.get_result.call_count == 7
    assert all(call.args[0] == "same-token" for call in client.get_result.call_args_list)
    assert client.get_formatted.call_args.args[0] == "same-token"
    assert sleeps == [3] * 5
    assert list(tmp_path.iterdir()) == [out]
    assert {p.name for p in out.iterdir()} == {
        "trigger_meta.json",
        "pages_tree.json",
        "paper.md",
        "formatted_meta.json",
    }
    assert json.loads((out / "trigger_meta.json").read_text())["trigger_kwargs"]["sync"] is False


@pytest.mark.parametrize("failure", ["error", "timeout", "unexpected"])
def test_async_terminal_failure_never_resubmits(tmp_path, monkeypatch, capsys, failure):
    client = MagicMock()
    client.trigger_file.return_value = {"status": "undefined", "token": "same-token"}
    client.get_result.return_value = {"status": "undefined" if failure == "timeout" else failure}
    elapsed = [0]
    monkeypatch.setattr(pipeline.time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(pipeline.time, "sleep", lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds))
    monkeypatch.setattr(pipeline, "POLL_TIMEOUT_SEC", 15)
    out = tmp_path / "parse"
    result = run_parse(client, _local_pdf(tmp_path / "paper.pdf"), out_dir=out, trigger_kwargs={"sync": False})

    assert result == 1
    client.trigger_file.assert_called_once()
    client.trigger_url.assert_not_called()
    client.get_formatted.assert_not_called()
    assert all(c.args[0] == "same-token" for c in client.get_result.call_args_list)
    assert {p.name for p in out.iterdir()} == {"trigger_meta.json"}
    assert json.loads(capsys.readouterr().err.splitlines()[-1])["error"]["stage"] == "get_result_poll"


@pytest.mark.parametrize(
    "response",
    [
        {"status": "undefined"},
        {"status": "undefined", "token": " "},
        {"status": "undefined", "token": 42},
        {"status": "error", "token": "diagnostic"},
        {"status": "undefined", "token": "diagnostic", "http_status": 503},
        {"status": "undefined", "token": "diagnostic", "error_type": "ReadTimeout"},
        {"status": "unrecognized", "token": "diagnostic"},
    ],
)
def test_invalid_trigger_never_polls_or_resubmits(tmp_path, response):
    client = MagicMock()
    client.trigger_file.return_value = response
    result = run_parse(
        client, _local_pdf(tmp_path / "paper.pdf"), out_dir=tmp_path / "parse", trigger_kwargs={"sync": False}
    )
    assert result == 1
    client.trigger_file.assert_called_once()
    client.get_result.assert_not_called()
    assert not (tmp_path / "parse" / "trigger_meta.json").exists()


def test_sync_pending_trigger_remains_an_error(tmp_path):
    client = MagicMock()
    client.trigger_file.return_value = {"status": "undefined", "token": "diagnostic"}
    assert (
        run_parse(client, _local_pdf(tmp_path / "paper.pdf"), out_dir=tmp_path / "parse", trigger_kwargs={"sync": True})
        == 1
    )
    client.trigger_file.assert_called_once()
    client.get_result.assert_not_called()
