"""Unit tests for the ``uniparser`` CLI (no network)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from cli.core.input import InputKind, resolve_input
from cli.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def env_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UNIPARSER_API_KEY", raising=False)


class TestCliConfig:
    def test_parse_without_api_key(self, runner: CliRunner, env_without_api_key: None) -> None:
        result = runner.invoke(cli, ["parse", "/tmp/paper.pdf"])
        assert result.exit_code == 1
        payload = json.loads(result.stderr.strip())
        assert payload["ok"] is False
        assert payload["error"]["code"] == "CONFIG_ERROR"
        assert "uniparser auth" in payload["error"]["message"]

    def test_parse_with_config_file_api_key(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.delenv("UNIPARSER_API_KEY", raising=False)
        config_dir = tmp_path / ".uniparser"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        config_path.write_text("api_key: file-key\n", encoding="utf-8")
        monkeypatch.setattr("cli.core.credentials.CONFIG_DIR", config_dir)
        monkeypatch.setattr("cli.core.credentials.CONFIG_PATH", config_path)

        mock_client = MagicMock()
        mock_client.trigger_file.return_value = {"status": "error", "description": "stop early"}
        monkeypatch.setattr("cli.commands.parse.make_client", lambda ctx: (mock_client, None))

        pdf = tmp_path / "paper.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        result = runner.invoke(cli, ["parse", str(pdf)])
        assert result.exit_code == 1
        mock_client.trigger_file.assert_called_once()

    def test_fetch_without_api_key(self, runner: CliRunner, env_without_api_key: None) -> None:
        result = runner.invoke(cli, ["fetch", "--token", "abc123"])
        assert result.exit_code == 1
        payload = json.loads(result.stderr.strip())
        assert payload["error"]["code"] == "CONFIG_ERROR"

    def test_fetch_requires_token_flag(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIPARSER_API_KEY", "test-key")
        result = runner.invoke(cli, ["fetch"])
        assert result.exit_code != 0


class TestInputResolve:
    def test_url_input(self) -> None:
        resolved = resolve_input("https://example.com/paper.pdf")
        assert not isinstance(resolved, str)
        assert resolved.kind is InputKind.URL
        assert resolved.source_stem == "paper"

    def test_missing_file(self) -> None:
        assert isinstance(resolve_input("/nonexistent/file.pdf"), str)


class TestParseCommand:
    def test_parse_success_writes_trigger_meta_and_json_token(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("UNIPARSER_API_KEY", "test-key")
        pdf = tmp_path / "paper.pdf"
        pdf.write_bytes(b"%PDF-1.4")

        mock_client = MagicMock()
        mock_client.trigger_file.return_value = {"status": "success", "token": "tok-parse-1"}
        mock_client.get_result.side_effect = [
            {"status": "processing"},
            {"status": "success", "pages_tree": {}},
            {"status": "success", "pages_tree": {"tree": []}},
        ]
        mock_client.get_formatted.return_value = {"status": "success", "content": "# Hi"}

        monkeypatch.setattr("cli.commands.parse.make_client", lambda ctx: (mock_client, None))

        out = tmp_path / "out"
        result = runner.invoke(
            cli,
            ["--json", "parse", str(pdf), "-o", str(out)],
            env={**os.environ, "UNIPARSER_API_KEY": "test-key"},
        )
        assert result.exit_code == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["token"] == "tok-parse-1"
        assert (out / "trigger_meta.json").is_file()
        meta = json.loads((out / "trigger_meta.json").read_text(encoding="utf-8"))
        assert meta["token"] == "tok-parse-1"
        assert (out / "paper.md").is_file()


class TestFetchCommand:
    def test_fetch_success(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("UNIPARSER_API_KEY", "test-key")

        mock_client = MagicMock()
        mock_client.get_result.side_effect = [
            {"status": "success"},
            {"status": "success", "pages_tree": {"tree": []}},
        ]
        mock_client.get_formatted.return_value = {"status": "success", "content": "body"}

        monkeypatch.setattr("cli.commands.fetch.make_client", lambda ctx: (mock_client, None))

        out = tmp_path / "fetch-out"
        result = runner.invoke(
            cli,
            ["--json", "fetch", "--token", "abcdef123456", "-o", str(out)],
            env={**os.environ, "UNIPARSER_API_KEY": "test-key"},
        )
        assert result.exit_code == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["token"] == "abcdef123456"
        assert payload["fetched_by_token"] is True
        assert (out / "token_abcdef12.md").is_file()


class TestHealthVersion:
    def test_health_json(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIPARSER_API_KEY", "test-key")
        mock_client = MagicMock()
        mock_client.health.return_value = {"status": "success"}
        monkeypatch.setattr("cli.commands.health.make_client", lambda ctx: (mock_client, None))

        result = runner.invoke(cli, ["--json", "health"], env={**os.environ, "UNIPARSER_API_KEY": "test-key"})
        assert result.exit_code == 0
        assert json.loads(result.stdout)["status"] == "success"

    def test_version_human(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNIPARSER_API_KEY", "test-key")
        mock_client = MagicMock()
        mock_client.version.return_value = {"status": "success", "version": "1.0"}
        monkeypatch.setattr("cli.commands.version.make_client", lambda ctx: (mock_client, None))

        result = runner.invoke(cli, ["version"], env={**os.environ, "UNIPARSER_API_KEY": "test-key"})
        assert result.exit_code == 0
        assert "uniparser-tools:" in result.stdout


class TestHelp:
    def test_parse_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["parse", "--help"])
        assert result.exit_code == 0
        assert "--output-dir" in result.stdout
        assert "--async" in result.stdout

    def test_fetch_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["fetch", "--help"])
        assert result.exit_code == 0
        assert "--token" in result.stdout


class TestAuthCommand:
    def test_auth_saves_api_key(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        config_dir = tmp_path / ".uniparser"
        config_path = config_dir / "config.yaml"
        monkeypatch.setattr("cli.core.credentials.CONFIG_DIR", config_dir)
        monkeypatch.setattr("cli.core.credentials.CONFIG_PATH", config_path)

        result = runner.invoke(cli, ["auth"], input="my-secret-key\n")
        assert result.exit_code == 0, result.stderr
        assert "API key saved successfully" in result.stdout
        assert config_path.is_file()
        assert "my-secret-key" in config_path.read_text(encoding="utf-8")

    def test_auth_show_masked(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        config_dir = tmp_path / ".uniparser"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        config_path.write_text("api_key: abcdefghijklmnop\n", encoding="utf-8")
        monkeypatch.setattr("cli.core.credentials.CONFIG_DIR", config_dir)
        monkeypatch.setattr("cli.core.credentials.CONFIG_PATH", config_path)

        result = runner.invoke(cli, ["auth", "--show"])
        assert result.exit_code == 0
        assert "abcd...mnop" in result.stdout

    def test_auth_show_without_config(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        config_dir = Path("/nonexistent/uniparser-config-test")
        monkeypatch.setattr("cli.core.credentials.CONFIG_PATH", config_dir / "config.yaml")

        result = runner.invoke(cli, ["auth", "--show"])
        assert result.exit_code == 1
        assert "No API key configured" in result.stdout

    def test_auth_verify_success(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        config_dir = tmp_path / ".uniparser"
        config_dir.mkdir()
        config_path = config_dir / "config.yaml"
        config_path.write_text("api_key: configured\n", encoding="utf-8")
        monkeypatch.setattr("cli.core.credentials.CONFIG_DIR", config_dir)
        monkeypatch.setattr("cli.core.credentials.CONFIG_PATH", config_path)

        result = runner.invoke(cli, ["auth", "--verify"])
        assert result.exit_code == 0
        assert "API key is configured" in result.stdout
