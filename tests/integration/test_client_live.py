"""Live integration tests for ``UniParserClient``.

Skipped automatically unless ``UNIPARSER_TEST_API_KEY`` and
``UNIPARSER_TEST_HOST`` are set.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from uniparser_tools.common.constant import FormatFlag, ParseMode, ParseModeTextual


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

    def test_trigger_file_and_fetch_markdown(self, live_client, demo_pdf_path: Path) -> None:
        trigger = live_client.trigger_file(
            file_path=str(demo_pdf_path),
            textual=ParseModeTextual.DigitalExported,
            table=ParseMode.OCRFast,
        )
        assert trigger.get("status") == "success", trigger
        token = trigger["token"]

        formatted = live_client.get_formatted(
            token,
            content=True,
            textual=FormatFlag.Markdown,
            table=FormatFlag.Markdown,
        )
        assert formatted.get("status") == "success", formatted
        assert "content" in formatted
        assert isinstance(formatted["content"], str) and len(formatted["content"]) > 0

    def test_trigger_snip(self, live_client, demo_img_path: Path) -> None:
        trigger = live_client.trigger_snip(
            snip_path=str(demo_img_path),
            textual=ParseModeTextual.OCRFast,
        )
        assert trigger.get("status") == "success", trigger
        assert "token" in trigger
