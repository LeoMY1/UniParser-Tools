"""Live integration tests for release/v1.3 client contracts."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from uniparser_tools.common.constant import FormatFlag, ParseMode, ParseModeTextual
from uniparser_tools.utils.convert import dict2obj


TEST_TEXT = "UNIPARSER LIVE OCR TEST 2026"
TEST_URL = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"


def _make_text_image(path: Path) -> Image.Image:
    image = Image.new("RGB", (1200, 360), "white")
    font = ImageFont.load_default(size=64)
    draw = ImageDraw.Draw(image)
    draw.text((60, 90), TEST_TEXT, fill="black", font=font)
    image.save(path)
    return image


def _assert_formatted_text(live_client, token: str, expected_text: str) -> dict:
    formatted = live_client.get_formatted(
        token,
        content=True,
        textual=FormatFlag.Markdown,
        table=FormatFlag.Markdown,
    )
    assert formatted.get("status") == "success", formatted
    content = formatted.get("content")
    assert isinstance(content, str) and content, formatted
    normalized_content = re.sub(r"[^a-z0-9]", "", content.lower())
    normalized_expected = re.sub(r"[^a-z0-9]", "", expected_text.lower())
    assert normalized_expected in normalized_content, formatted
    return formatted


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
        image_path = tmp_path / "release-v1.3-file-live-test.png"
        page = _make_text_image(image_path)
        document_path = tmp_path / "release-v1.3-live-test.pdf"
        page.save(document_path, "PDF", resolution=150.0)
        page.close()

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

        _assert_formatted_text(live_client, token, "uniparser")

        third_party = live_client.get_third_party_output(token)
        assert third_party.get("status") == "success", third_party

    def test_trigger_url_and_fetch_text(self, live_client) -> None:
        version = live_client.version()
        trigger = live_client.trigger_url(
            TEST_URL,
            token=uuid.uuid4().hex,
            textual=ParseModeTextual.DigitalExported,
            table=ParseMode.Disable,
            model_version=version.get("default_version"),
        )
        assert trigger.get("status") == "success", trigger
        _assert_formatted_text(live_client, trigger["token"], "dummy pdf file")

    def test_trigger_snip_and_fetch_text(self, live_client, tmp_path: Path) -> None:
        image_path = tmp_path / "release-v1.3-snip-live-test.png"
        image = _make_text_image(image_path)
        image.close()

        trigger = live_client.trigger_snip(
            snip_path=str(image_path),
            token=uuid.uuid4().hex,
            textual=ParseModeTextual.OCRFast,
            table=ParseMode.Disable,
        )
        assert trigger.get("status") == "success", trigger
        _assert_formatted_text(live_client, trigger["token"], "uniparser")
