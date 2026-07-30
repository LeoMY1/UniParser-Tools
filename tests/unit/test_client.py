"""Unit tests for ``UniParserClient`` that do not hit the network.

The real HTTP calls are covered in ``tests/integration`` and are skipped
unless credentials are provided.
"""

from __future__ import annotations

import json

import pytest
import requests

from uniparser_tools.api.clients import UniParserClient


class FakeResponse:
    def __init__(self, status_code: int = 200, payload=None, text: str = "", reason: str = "OK"):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.reason = reason

    def json(self):
        if self._payload is None:
            raise json.JSONDecodeError("invalid", self.text, 0)
        return self._payload


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response or FakeResponse(payload={"status": "success"})
        self.error = error
        self.calls = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.error:
            raise self.error
        return self.response

    def close(self):
        self.closed = True


class TestClientConstruction:
    def test_rejects_empty_api_key(self) -> None:
        with pytest.raises(AssertionError):
            UniParserClient(host="https://example.com", api_key="")

    def test_rejects_non_http_host(self) -> None:
        with pytest.raises(AssertionError):
            UniParserClient(host="example.com", api_key="k")

    def test_endpoints_compose_correctly(self) -> None:
        c = UniParserClient(host="https://example.com/", api_key="k")
        assert c.host == "https://example.com"
        assert c.trigger_file_endpoint.endswith("/trigger-file-async")
        assert c.trigger_url_endpoint.endswith("/trigger-url-async")
        assert c.trigger_snip_endpoint.endswith("/trigger-snip-async")
        assert c.get_result_endpoint.endswith("/get-result")
        assert c.get_formatted_endpoint.endswith("/get-formatted")


class TestTokenHelpers:
    def test_to_token_is_deterministic(self) -> None:
        c = UniParserClient(host="https://e.com", api_key="secret")
        t1 = c.to_token("/abs/path/file.pdf")
        t2 = c.to_token("/abs/path/file.pdf")
        assert t1 == t2

    def test_to_token_varies_across_keys(self) -> None:
        c1 = UniParserClient(host="https://e.com", api_key="secret-A")
        c2 = UniParserClient(host="https://e.com", api_key="secret-B")
        assert c1.to_token("same.pdf") != c2.to_token("same.pdf")

    def test_validate_token_accepts_hex(self) -> None:
        c = UniParserClient(host="https://e.com", api_key="k")
        c.validate_token(c.to_token("x.pdf"))

    def test_validate_token_rejects_illegal_chars(self) -> None:
        c = UniParserClient(host="https://e.com", api_key="k")
        with pytest.raises(AssertionError):
            c.validate_token("has spaces!")

    def test_validate_token_rejects_empty(self) -> None:
        c = UniParserClient(host="https://e.com", api_key="k")
        with pytest.raises(AssertionError):
            c.validate_token("")


class TestClientErrorShapes:
    """When the underlying request raises, we expect structured error dicts."""

    def test_health_returns_error_dict_on_request_failure(self) -> None:
        session = FakeSession(error=requests.ConnectionError("simulated"))
        c = UniParserClient(host="https://example.com", api_key="k", session=session)
        result = c.health()
        assert isinstance(result, dict)
        assert result.get("status") == "error"
        assert "description" in result

    def test_version_returns_error_dict_on_request_failure(self) -> None:
        session = FakeSession(error=requests.ConnectionError("simulated"))
        c = UniParserClient(host="https://example.com", api_key="k", session=session)
        result = c.version()
        assert isinstance(result, dict)
        assert result.get("status") == "error"
        assert "description" in result

    def test_trigger_file_returns_error_dict_on_request_failure(self, tmp_path) -> None:
        p = tmp_path / "dummy.pdf"
        p.write_bytes(b"%PDF-1.4 tiny")
        session = FakeSession(error=requests.ConnectionError("simulated"))
        c = UniParserClient(host="https://example.com", api_key="k", session=session)
        result = c.trigger_file(file_path=str(p))
        assert isinstance(result, dict)
        assert result.get("status") == "error"
        assert "token" in result


class TestHTTPTransport:
    def test_uses_short_timeout_for_async_trigger(self, tmp_path) -> None:
        p = tmp_path / "dummy.pdf"
        p.write_bytes(b"%PDF-1.4 tiny")
        session = FakeSession()
        c = UniParserClient(
            host="https://example.com",
            api_key="k",
            request_timeout=(1, 2),
            sync_request_timeout=(3, 4),
            session=session,
        )

        c.trigger_file(file_path=str(p), sync=False)

        assert session.calls[0][2]["timeout"] == (1, 2)

    def test_uses_sync_timeout_for_sync_trigger(self, tmp_path) -> None:
        p = tmp_path / "dummy.pdf"
        p.write_bytes(b"%PDF-1.4 tiny")
        session = FakeSession()
        c = UniParserClient(
            host="https://example.com",
            api_key="k",
            request_timeout=(1, 2),
            sync_request_timeout=(3, 4),
            session=session,
        )

        c.trigger_file(file_path=str(p), sync=True)

        assert session.calls[0][2]["timeout"] == (3, 4)

    def test_http_error_preserves_json_body(self) -> None:
        session = FakeSession(
            response=FakeResponse(
                status_code=429,
                payload={"status": "error", "description": "rate limited"},
                reason="Too Many Requests",
            )
        )
        c = UniParserClient(host="https://example.com", api_key="k", session=session)

        result = c.health()

        assert result["description"] == "rate limited"
        assert result["http_status"] == 429

    def test_client_context_closes_owned_session(self, monkeypatch) -> None:
        session = FakeSession()
        monkeypatch.setattr("uniparser_tools.api.transport.requests.Session", lambda: session)
        c = UniParserClient(host="https://example.com", api_key="k")

        with c:
            pass

        assert session.closed is True
