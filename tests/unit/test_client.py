"""Unit tests for ``UniParserClient`` that do not hit the network.

The real HTTP calls are covered in ``tests/integration`` and are skipped
unless credentials are provided.
"""

from __future__ import annotations

import json

import pytest
import requests
from PIL import Image

from uniparser_tools.api.clients import TOSUploadFile, UniParserClient
from uniparser_tools.common.constant import ThirdPartyFormatter


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
    def __init__(self, response=None, responses=None, error=None):
        self.response = response or FakeResponse(payload={"status": "success"})
        self.responses = list(responses or [])
        self.error = error
        self.calls = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.error:
            raise self.error
        if self.responses:
            return self.responses.pop(0)
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
        assert c.request_tos_upload_links_endpoint.endswith("/request-tos-upload-links")
        assert c.health_endpoint.endswith("/health")
        assert c.version_endpoint.endswith("/version")
        assert c.get_constants_endpoint.endswith("/get-constants")
        assert c.get_result_endpoint.endswith("/get-result")
        assert c.get_formatted_endpoint.endswith("/get-formatted")
        assert c.get_third_party_output_endpoint.endswith("/get-third-party-output")


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


class TestResultAPIs:
    def test_get_result_accepts_per_call_http_timeout(self) -> None:
        session = FakeSession()
        client = UniParserClient(host="https://example.com", api_key="k", session=session)

        client.get_result("task-token", objects=True, http_timeout=(4, 5))

        assert session.calls[0][2]["timeout"] == (4, 5)
        assert session.calls[0][2]["json"]["objects"] is True

    def test_get_formatted_accepts_per_call_http_timeout(self) -> None:
        session = FakeSession()
        client = UniParserClient(host="https://example.com", api_key="k", session=session)

        client.get_formatted("task-token", content=True, http_timeout=(6, 7))

        assert session.calls[0][2]["timeout"] == (6, 7)
        assert session.calls[0][2]["json"]["content"] is True

    def test_get_third_party_output_sends_formatter(self) -> None:
        session = FakeSession(response=FakeResponse(payload={"status": "success", "content": {}}))
        client = UniParserClient(host="https://example.com", api_key="k", session=session)

        result = client.get_third_party_output(
            "task-token",
            formatter=ThirdPartyFormatter.MinerU,
            http_timeout=(8, 9),
        )

        assert result["status"] == "success"
        assert session.calls[0][2]["json"] == {
            "token": "task-token",
            "formatter": "mineru",
        }
        assert session.calls[0][2]["timeout"] == (8, 9)


class TestServiceDiscovery:
    def test_health_accepts_per_call_timeout(self) -> None:
        session = FakeSession(response=FakeResponse(payload={"status": "Healthy"}))
        client = UniParserClient(host="https://example.com", api_key="k", session=session)

        result = client.health(http_timeout=(1, 2))

        assert result["status"] == "Healthy"
        assert session.calls[0][2]["timeout"] == (1, 2)

    def test_version_preserves_model_backend_metadata(self) -> None:
        payload = {
            "version": "frontend-1.3",
            "default_version": "v1.3",
            "backend_versions": {
                "v1.3": {
                    "available": True,
                    "capabilities": {"preset_layout_reparse": True},
                }
            },
        }
        session = FakeSession(response=FakeResponse(payload=payload))
        client = UniParserClient(host="https://example.com", api_key="k", session=session)

        result = client.version()

        assert result == payload
        assert result["default_version"] == "v1.3"
        assert result["backend_versions"]["v1.3"]["available"] is True

    def test_get_constants_returns_service_contract(self) -> None:
        payload = {
            "LayoutType": {"paragraph": "paragraph"},
            "TokenRegEx": r"^[-\\._?=&a-zA-Z0-9]{1,128}$",
        }
        session = FakeSession(response=FakeResponse(payload=payload))
        client = UniParserClient(host="https://example.com", api_key="k", session=session)

        result = client.get_constants(http_timeout=(3, 4))

        assert result == payload
        assert session.calls[0][1].endswith("/get-constants")
        assert session.calls[0][2]["timeout"] == (3, 4)


class TestSubmissionPayloads:
    @staticmethod
    def _preset_layout():
        return [[{"type": "textual", "bbox": [0, 0, 20, 20]}]]

    def test_trigger_file_sends_latest_form_fields(self, tmp_path) -> None:
        path = tmp_path / "document.pdf"
        path.write_bytes(b"%PDF-1.4 tiny")
        session = FakeSession()
        client = UniParserClient(host="https://example.com", api_key="k", session=session)

        client.trigger_file(
            str(path),
            timeout=321,
            padding_snip=False,
            inplace_update=True,
            preset_layout=self._preset_layout(),
            model_version="v1.3",
            http_timeout=(2, 3),
        )

        payload = session.calls[0][2]["data"]
        assert payload["timeout"] == 321
        assert payload["padding_snip"] is False
        assert payload["inplace_update"] is True
        assert json.loads(payload["preset_layout"]) == self._preset_layout()
        assert payload["model_version"] == "v1.3"
        assert session.calls[0][2]["timeout"] == (2, 3)

    def test_empty_token_preserves_deterministic_token_compatibility(self, tmp_path) -> None:
        path = tmp_path / "document.pdf"
        path.write_bytes(b"%PDF-1.4 tiny")
        session = FakeSession()
        client = UniParserClient(host="https://example.com", api_key="k", session=session)

        client.trigger_file(str(path), token="", sync=False)

        assert session.calls[0][2]["data"]["token"] == client.to_token(str(path))

    def test_trigger_snip_sends_latest_form_fields(self, tmp_path) -> None:
        path = tmp_path / "snip.png"
        Image.new("RGB", (2, 2), "white").save(path)
        session = FakeSession()
        client = UniParserClient(host="https://example.com", api_key="k", session=session)

        client.trigger_snip(
            str(path),
            timeout=123,
            padding_snip=False,
            inplace_update=True,
            preset_layout=self._preset_layout(),
            model_version="v1.3",
        )

        payload = session.calls[0][2]["data"]
        assert payload["timeout"] == 123
        assert payload["padding_snip"] is False
        assert payload["inplace_update"] is True
        assert json.loads(payload["preset_layout"]) == self._preset_layout()
        assert payload["model_version"] == "v1.3"
        assert payload["img"]

    def test_trigger_url_serializes_preset_layout_inside_json_body(self) -> None:
        session = FakeSession()
        client = UniParserClient(host="https://example.com", api_key="k", session=session)

        client.trigger_url(
            "tos://bucket/document.pdf",
            timeout=456,
            inplace_update=True,
            preset_layout=self._preset_layout(),
            model_version="v1.3",
        )

        payload = session.calls[0][2]["json"]
        assert payload["timeout"] == 456
        assert payload["inplace_update"] is True
        assert isinstance(payload["preset_layout"], str)
        assert json.loads(payload["preset_layout"]) == self._preset_layout()
        assert payload["model_version"] == "v1.3"
        assert "padding_snip" not in payload

    def test_server_generated_token_omits_deterministic_token(self, tmp_path) -> None:
        path = tmp_path / "document.pdf"
        path.write_bytes(b"%PDF-1.4 tiny")
        session = FakeSession(response=FakeResponse(payload={"status": "waiting", "token": "server-token"}))
        client = UniParserClient(host="https://example.com", api_key="k", session=session)

        result = client.trigger_file(str(path), sync=False, server_generated_token=True)

        assert session.calls[0][2]["data"]["token"] is None
        assert result["token"] == "server-token"


class TestTOSUpload:
    def test_requests_upload_links_for_names_and_explicit_tokens(self) -> None:
        session = FakeSession(response=FakeResponse(payload={"files": []}))
        client = UniParserClient(host="https://example.com", api_key="k", session=session)

        client.request_tos_upload_links(
            [
                "first.pdf",
                TOSUploadFile(filename="second.png", token="explicit-token"),
            ]
        )

        assert session.calls[0][2]["json"] == {
            "files": [
                {"filename": "first.pdf", "token": None},
                {"filename": "second.png", "token": "explicit-token"},
            ]
        }

    def test_upload_helper_puts_without_api_key(self, tmp_path) -> None:
        path = tmp_path / "document.pdf"
        path.write_bytes(b"%PDF-1.4 tiny")
        link = {
            "filename": "document.pdf",
            "token": "server-token",
            "upload_url": "https://tos.example.com/upload?signature=secret",
            "source_url": "tos://bucket/document.pdf",
        }
        session = FakeSession(
            responses=[
                FakeResponse(payload={"files": [link]}),
                FakeResponse(status_code=200, payload=None),
            ]
        )
        client = UniParserClient(host="https://example.com", api_key="k", session=session)

        result = client.upload_files_to_tos([str(path)])

        assert result["status"] == "success"
        assert result["files"][0]["source_url"] == "tos://bucket/document.pdf"
        assert result["files"][0]["uploaded"] is True
        assert "upload_url" not in result["files"][0]
        assert session.calls[1][0] == "PUT"
        assert session.calls[1][1] == link["upload_url"]
        assert "X-API-Key" not in session.calls[1][2]["headers"]
        assert session.calls[1][2]["timeout"] == (60.0, 300.0)

    def test_transport_redacts_presigned_url_from_request_errors(self) -> None:
        session = FakeSession(
            error=requests.ConnectionError("failed for https://tos.example.com/upload?X-Tos-Signature=FAKE_BEARER")
        )
        client = UniParserClient(host="https://example.com", api_key="k", session=session)

        result = client._transport.request(
            "PUT",
            "https://tos.example.com/upload?X-Tos-Signature=FAKE_BEARER",
            authenticated=False,
            expect_json=False,
        )

        assert "FAKE_BEARER" not in result["description"]
        assert "?<redacted>" in result["description"]

    def test_transport_redacts_presigned_url_from_json_errors(self) -> None:
        session = FakeSession(
            response=FakeResponse(
                status_code=403,
                payload={
                    "status": "error",
                    "description": ("upload denied for https://tos.example.com/upload?X-Tos-Signature=FAKE_BEARER"),
                },
                reason="Forbidden",
            )
        )
        client = UniParserClient(host="https://example.com", api_key="k", session=session)

        result = client.health()

        assert "FAKE_BEARER" not in result["description"]
        assert "?<redacted>" in result["description"]

    def test_upload_http_error_is_not_misclassified_as_success(self, tmp_path) -> None:
        path = tmp_path / "document.pdf"
        path.write_bytes(b"%PDF-1.4 tiny")
        link = {
            "filename": "document.pdf",
            "upload_url": "https://tos.example.com/upload?X-Tos-Signature=FAKE_BEARER",
            "source_url": "tos://bucket/document.pdf",
        }
        session = FakeSession(
            responses=[
                FakeResponse(payload={"files": [link]}),
                FakeResponse(status_code=503, payload=None, text="non-JSON TOS error", reason="Service Unavailable"),
            ]
        )
        client = UniParserClient(host="https://example.com", api_key="k", session=session)

        result = client.upload_files_to_tos([str(path)])

        assert result["status"] == "error"
        assert result["upload"]["http_status"] == 503
        assert result["files"] == []

    def test_upload_count_mismatch_does_not_return_presigned_urls(self, tmp_path) -> None:
        path = tmp_path / "document.pdf"
        path.write_bytes(b"%PDF-1.4 tiny")
        session = FakeSession(
            response=FakeResponse(
                payload={
                    "files": [
                        {
                            "filename": "document.pdf",
                            "upload_url": "https://tos.example.com/upload?X-Tos-Signature=FAKE_BEARER",
                            "source_url": "tos://bucket/document.pdf",
                        },
                        {
                            "filename": "unexpected.pdf",
                            "upload_url": "https://tos.example.com/upload?X-Tos-Signature=OTHER_FAKE_BEARER",
                            "source_url": "tos://bucket/unexpected.pdf",
                        },
                    ]
                }
            )
        )
        client = UniParserClient(host="https://example.com", api_key="k", session=session)

        result = client.upload_files_to_tos([str(path)])

        assert result["status"] == "error"
        assert all("upload_url" not in item for item in result["files"])

    def test_upload_helper_rejects_token_count_mismatch(self, tmp_path) -> None:
        path = tmp_path / "document.pdf"
        path.write_bytes(b"%PDF-1.4 tiny")
        client = UniParserClient(host="https://example.com", api_key="k", session=FakeSession())

        result = client.upload_files_to_tos([str(path)], tokens=[])

        assert result["status"] == "error"
