from __future__ import annotations

from typing import Optional

import requests

from uniparser_tools.api.transport import (
    DEFAULT_REQUEST_TIMEOUT,
    RequestTimeout,
    UniParserHTTPTransport,
)


class UniParserAccountClient:
    """Read-only account and billing API client."""

    def __init__(
        self,
        host: str,
        api_key: str,
        *,
        request_timeout: RequestTimeout = DEFAULT_REQUEST_TIMEOUT,
        session: Optional[requests.Session] = None,
    ):
        self._transport = UniParserHTTPTransport(
            host,
            api_key,
            request_timeout=request_timeout,
            session=session,
        )
        self._owns_transport = True
        self.host = self._transport.host
        self.api_key = api_key
        self.request_timeout = request_timeout

    @classmethod
    def from_transport(cls, transport: UniParserHTTPTransport) -> "UniParserAccountClient":
        """Create an account namespace sharing another client's transport."""
        client = cls.__new__(cls)
        client._transport = transport
        client._owns_transport = False
        client.host = transport.host
        client.api_key = transport.api_key
        client.request_timeout = transport.request_timeout
        return client

    def close(self) -> None:
        if self._owns_transport:
            self._transport.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    @property
    def current_user_endpoint(self):
        return f"{self.host}/users/me"

    @property
    def balance_endpoint(self):
        return f"{self.host}/balance"

    @property
    def usage_summary_endpoint(self):
        return f"{self.host}/billing/usage"

    @property
    def usage_records_endpoint(self):
        return f"{self.host}/billing/usage-records"

    @property
    def balance_transactions_endpoint(self):
        return f"{self.host}/balance/transactions"

    def get_current_user(self, *, http_timeout: Optional[RequestTimeout] = None):
        return self._transport.request(
            "GET",
            "/users/me",
            timeout=http_timeout,
            error_message="current user request failed",
        )

    def get_balance(self, *, http_timeout: Optional[RequestTimeout] = None):
        return self._transport.request(
            "GET",
            "/balance",
            timeout=http_timeout,
            error_message="balance request failed",
        )

    def get_usage_summary(
        self,
        period: str = "current_month",
        *,
        http_timeout: Optional[RequestTimeout] = None,
    ):
        return self._transport.request(
            "GET",
            "/billing/usage",
            params={"period": period},
            timeout=http_timeout,
            error_message="usage summary request failed",
        )

    def list_usage_records(
        self,
        page: int = 1,
        size: int = 20,
        *,
        http_timeout: Optional[RequestTimeout] = None,
    ):
        return self._transport.request(
            "GET",
            "/billing/usage-records",
            params={"page": page, "size": size},
            timeout=http_timeout,
            error_message="usage records request failed",
        )

    def list_balance_transactions(
        self,
        page: int = 1,
        size: int = 20,
        *,
        http_timeout: Optional[RequestTimeout] = None,
    ):
        return self._transport.request(
            "GET",
            "/balance/transactions",
            params={"page": page, "size": size},
            timeout=http_timeout,
            error_message="balance transactions request failed",
        )

    def get_balance_transactions(
        self,
        page: int = 1,
        size: int = 20,
        *,
        http_timeout: Optional[RequestTimeout] = None,
    ):
        """Alias for ``list_balance_transactions``."""
        return self.list_balance_transactions(page=page, size=size, http_timeout=http_timeout)
