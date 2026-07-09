import asyncio
from pathlib import Path
from unittest.mock import MagicMock

from uniparser_mcp.pipeline.parse import run_parse
from uniparser_mcp.schemas import ParseRequest


def test_duplicate_triggers_internal_complete(tmp_path: Path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    client = MagicMock()
    client.to_token.return_value = "tok123"
    client.trigger_file.return_value = {
        "status": "error",
        "message": "Token is duplicated",
        "token": "tok123",
    }
    client.get_result.side_effect = [
        {"status": "success"},
        {"status": "success", "pages_tree": True},
    ]
    client.get_formatted.return_value = {
        "status": "success",
        "content": "# Hello",
    }

    req = ParseRequest(file_path=str(pdf), output_dir=str(tmp_path / "out"))
    result = asyncio.run(run_parse(client, req))

    assert result.ok is True
    assert result.token == "tok123"
    assert result.trigger_meta_path is None
    assert Path(result.markdown_path).is_file()
    client.trigger_file.assert_called_once()


def test_success_parse_writes_trigger_meta(tmp_path: Path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    client = MagicMock()
    client.trigger_file.return_value = {"status": "success", "token": "tok456"}
    client.get_result.side_effect = [
        {"status": "success"},
        {"status": "success"},
    ]
    client.get_formatted.return_value = {
        "status": "success",
        "content": "# Title",
    }

    out = tmp_path / "out"
    req = ParseRequest(file_path=str(pdf), output_dir=str(out))
    result = asyncio.run(run_parse(client, req))

    assert result.ok is True
    assert result.trigger_meta_path is not None
    assert Path(result.trigger_meta_path).is_file()
