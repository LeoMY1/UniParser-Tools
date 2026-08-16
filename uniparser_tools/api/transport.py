from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple, Union
from urllib.parse import urlparse

import requests

from uniparser_tools.common.constant import StatusFlag


RequestTimeout = Union[float, Tuple[float, Optional[float]]]

DEFAULT_REQUEST_TIMEOUT: RequestTimeout = (10.0, 60.0)
DEFAULT_SYNC_REQUEST_TIMEOUT: RequestTimeout = (10.0, 1860.0)
DEFAULT_UPLOAD_REQUEST_TIMEOUT: RequestTimeout = (60.0, 300.0)


def _redact_url_queries(value: str) -> str:
    """Remove bearer-style query strings from URLs included in diagnostics."""
    return re.sub(r"(?P<url>(?:https?://|/)[^\s?]+)\?[^\s]+", r"\g<url>?<redacted>", value)


def _redact_diagnostic_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_diagnostic_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_diagnostic_value(item) for item in value]
    if isinstance(value, str):
        return _redact_url_queries(value)
    return value


class UniParserHTTPTransport:
    """Shared HTTP transport for UniParser API clients."""

    def __init__(
        self,
        host: str,
        api_key: str,
        *,
        request_timeout: RequestTimeout = DEFAULT_REQUEST_TIMEOUT,
        session: Optional[requests.Session] = None,
    ):
        parsed = urlparse(host)
        assert parsed.scheme in {"http", "https"} and parsed.netloc, "host must be a valid http or https URL"
        assert api_key, "api_key can not be empty"

        self.host = host.rstrip("/")
        self.api_key = api_key
        self.request_timeout = request_timeout
        self.session = session or requests.Session()
        self._owns_session = session is None

    def endpoint(self, path: str) -> str:
        return f"{self.host}/{path.lstrip('/')}"

    def request(
        self,
        method: str,
        path: str,
        *,
        timeout: Optional[RequestTimeout] = None,
        authenticated: bool = True,
        expect_json: bool = True,
        error_message: str = "request failed",
        token: Optional[str] = None,
        candidate_token: Optional[str] = None,
        **kwargs,
    ) -> Any:
        headers = dict(kwargs.pop("headers", {}) or {})
        if authenticated:
            headers.setdefault("X-API-Key", self.api_key)

        url = path if path.startswith(("http://", "https://")) else self.endpoint(path)
        try:
            response = self.session.request(
                method,
                url,
                headers=headers,
                timeout=self.request_timeout if timeout is None else timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            payload: Dict[str, Any] = {
                "status": StatusFlag.Error,
                "message": error_message,
                "description": _redact_url_queries(str(exc)),
                "error_type": type(exc).__name__,
            }
            if token is not None:
                payload["token"] = token
            if candidate_token is not None:
                payload["candidate_token"] = candidate_token
                payload["candidate_token_recoverable"] = False
            return payload

        try:
            payload = response.json()
        except ValueError:
            payload = None

        if response.status_code >= 400:
            if isinstance(payload, dict):
                result = _redact_diagnostic_value(payload)
                result.setdefault("status", StatusFlag.Error)
                result.setdefault("description", response.reason or error_message)
            else:
                result = {
                    "status": StatusFlag.Error,
                    "description": response.reason or error_message,
                    "body": _redact_url_queries(response.text),
                }
            result["http_status"] = response.status_code
            if token is not None:
                result.setdefault("token", token)
            if candidate_token is not None:
                result.setdefault("candidate_token", candidate_token)
                result.setdefault("candidate_token_recoverable", False)
            return result

        if not expect_json:
            return {
                "status": "success",
                "http_status": response.status_code,
            }

        if isinstance(payload, dict) and payload.get("status") == StatusFlag.Error and candidate_token is not None:
            payload.setdefault("candidate_token", candidate_token)
            payload.setdefault("candidate_token_recoverable", False)

        if payload is not None:
            return payload

        result = {
            "status": StatusFlag.Error,
            "message": error_message,
            "description": "response body is not valid JSON",
            "body": _redact_url_queries(response.text),
        }
        if token is not None:
            result["token"] = token
        if candidate_token is not None:
            result["candidate_token"] = candidate_token
            result["candidate_token_recoverable"] = False
        return result

    def close(self) -> None:
        if self._owns_session:
            self.session.close()
