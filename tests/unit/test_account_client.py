from __future__ import annotations

import json

from uniparser_tools.api.account import UniParserAccountClient
from uniparser_tools.api.clients import UniParserClient


class FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload
        self.text = ""
        self.reason = "OK"

    def json(self):
        if self._payload is None:
            raise json.JSONDecodeError("invalid", "", 0)
        return self._payload


class FakeSession:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0) if self.responses else FakeResponse({"status": "success"})

    def close(self):
        self.closed = True


class TestAccountClient:
    def test_endpoints_compose_correctly(self) -> None:
        client = UniParserAccountClient(host="https://example.com/", api_key="k")

        assert client.current_user_endpoint == "https://example.com/users/me"
        assert client.balance_endpoint == "https://example.com/balance"
        assert client.usage_summary_endpoint == "https://example.com/billing/usage"
        assert client.usage_records_endpoint == "https://example.com/billing/usage-records"
        assert client.balance_transactions_endpoint == "https://example.com/balance/transactions"

    def test_profile_and_balance_are_read_only_gets(self) -> None:
        session = FakeSession(
            responses=[
                FakeResponse({"username": "customer"}),
                FakeResponse({"balance": "10.00", "currency": "CNY"}),
            ]
        )
        client = UniParserAccountClient(host="https://example.com", api_key="k", session=session)

        assert client.get_current_user()["username"] == "customer"
        assert client.get_balance(http_timeout=(1, 2))["balance"] == "10.00"
        assert [call[0] for call in session.calls] == ["GET", "GET"]
        assert session.calls[1][2]["timeout"] == (1, 2)

    def test_usage_summary_sends_period(self) -> None:
        session = FakeSession(responses=[FakeResponse({"total_requests": 3})])
        client = UniParserAccountClient(host="https://example.com", api_key="k", session=session)

        result = client.get_usage_summary("last_month")

        assert result["total_requests"] == 3
        assert session.calls[0][2]["params"] == {"period": "last_month"}

    def test_paginated_read_methods_send_page_and_size(self) -> None:
        session = FakeSession(
            responses=[
                FakeResponse({"items": [], "page": 2, "size": 5}),
                FakeResponse({"items": [], "page": 3, "size": 10}),
            ]
        )
        client = UniParserAccountClient(host="https://example.com", api_key="k", session=session)

        client.list_usage_records(page=2, size=5)
        client.list_balance_transactions(page=3, size=10)

        assert session.calls[0][2]["params"] == {"page": 2, "size": 5}
        assert session.calls[1][2]["params"] == {"page": 3, "size": 10}

    def test_main_client_account_namespace_shares_transport(self) -> None:
        session = FakeSession(responses=[FakeResponse({"balance": "8.50"})])
        client = UniParserClient(host="https://example.com", api_key="k", session=session)

        result = client.account.get_balance()

        assert result["balance"] == "8.50"
        assert session.calls[0][1] == "https://example.com/balance"
        assert session.calls[0][2]["headers"]["X-API-Key"] == "k"

    def test_standalone_context_closes_owned_session(self, monkeypatch) -> None:
        session = FakeSession()
        monkeypatch.setattr("uniparser_tools.api.transport.requests.Session", lambda: session)

        with UniParserAccountClient(host="https://example.com", api_key="k"):
            pass

        assert session.closed is True
