"""Live integration tests for release/v1.3 client contracts."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from uniparser_tools.common.constant import FormatFlag, ParseMode, ParseModeTextual
from uniparser_tools.utils.convert import dict2obj


@pytest.mark.live
class TestClientLive:
    def test_health(self, live_client) -> None:
        result = live_client.health()
        assert isinstance(result, dict)
        # Contract: /health only guarantees HTTP 200 when healthy; the body
        # shape is not part of the contract. UniParserClient.health surfaces
        # non-2xx responses via an ``http_status`` key and request-level
        # failures via a ``description`` key -- assert neither is present.
        assert "http_status" not in result, result
        assert "description" not in result, result

    def test_version(self, live_client) -> None:
        result = live_client.version()
        assert isinstance(result, dict)
        assert "http_status" not in result, result
        assert "description" not in result, result
        assert "version" in result, result

    def test_constants(self, live_client) -> None:
        result = live_client.get_constants()
        assert isinstance(result, dict)
        assert "LayoutType" in result, result
        assert "TokenRegEx" in result, result

    def test_read_only_account_endpoints(self, live_client) -> None:
        profile = live_client.account.get_current_user()
        balance = live_client.account.get_balance()
        usage = live_client.account.get_usage_summary(period="current_month")
        usage_records = live_client.account.list_usage_records(page=1, size=1, http_timeout=(10, 120))
        transactions = live_client.account.list_balance_transactions(page=1, size=1, http_timeout=(10, 120))

        assert profile.get("id"), profile
        assert "balance" in balance, balance
        assert "total_requests" in usage, usage
        assert isinstance(usage_records.get("items"), list), usage_records
        assert isinstance(transactions.get("items"), list), transactions

    def test_trigger_file_and_fetch_release_results(self, live_client, tmp_path: Path) -> None:
        page = Image.new("RGB", (320, 120), "white")
        ImageDraw.Draw(page).text((20, 40), "UniParser release v1.3 live test", fill="black")
        document_path = tmp_path / "release-v1.3-live-test.pdf"
        page.save(document_path, "PDF", resolution=72.0)

        version = live_client.version()
        trigger = live_client.trigger_file(
            file_path=str(document_path),
            textual=ParseModeTextual.OCRFast,
            table=ParseMode.Disable,
            model_version=version.get("default_version"),
            server_generated_token=True,
        )
        if trigger.get("http_status") == 400 and trigger.get("description") == "Token is required":
            # Backward-compatible fallback for deployments that have not yet
            # rolled out release/v1.3's optional-token contract.
            trigger = live_client.trigger_file(
                file_path=str(document_path),
                textual=ParseModeTextual.OCRFast,
                table=ParseMode.Disable,
                model_version=version.get("default_version"),
                token=uuid.uuid4().hex,
            )
        assert trigger.get("status") == "success", trigger
        token = trigger["token"]

        raw = live_client.get_result(token, pages_dict=True)
        assert raw.get("status") == "success", raw
        assert isinstance(raw.get("pages_dict"), list), raw
        converted_pages = dict2obj(raw["pages_dict"])
        assert isinstance(converted_pages, list)

        formatted = live_client.get_formatted(
            token,
            content=True,
            textual=FormatFlag.Markdown,
            table=FormatFlag.Markdown,
        )
        assert formatted.get("status") == "success", formatted
        assert "content" in formatted
        assert isinstance(formatted["content"], str) and len(formatted["content"]) > 0

        third_party = live_client.get_third_party_output(token)
        assert third_party.get("status") == "success", third_party

    def test_trigger_snip(self, live_client, demo_img_path: Path) -> None:
        if os.environ.get("UNIPARSER_RUN_EXTRA_LIVE_PARSE") != "1":
            pytest.skip("set UNIPARSER_RUN_EXTRA_LIVE_PARSE=1 to run the additional billable snip parse")
        trigger = live_client.trigger_snip(
            snip_path=str(demo_img_path),
            textual=ParseModeTextual.OCRFast,
            server_generated_token=True,
        )
        assert trigger.get("status") == "success", trigger
        assert "token" in trigger
