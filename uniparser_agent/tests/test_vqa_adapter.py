"""Unit tests for UniParser → LLM content-list adapter."""

from __future__ import annotations

import json
from pathlib import Path

from uniparser_agent.pdf2qa.layout_adapter import pages_tree_to_content_list

KIRA_TREE = Path("/Users/jiangyutong/Desktop/DP/test_pdf/kira/pages_tree.json")
FIXTURE = Path(__file__).parent / "fixtures" / "minimal_pages_tree.json"


def test_adapter_skips_noise_and_numbers_ids():
    data = {
        "pages_tree": [
            [
                {"type": "hline", "order": 0, "text": ""},
                {"type": "pageheader", "order": 1, "text": "header"},
                {"type": "paragraph", "order": 2, "text": "Q1 text"},
                {
                    "type": "equation",
                    "order": 3,
                    "latex_repr": "x^2=1",
                    "text": "",
                },
                {"type": "pagenumber", "order": 4, "text": "1"},
            ]
        ]
    }
    content = pages_tree_to_content_list(data)
    assert [c["id"] for c in content] == [0, 1]
    assert content[0]["type"] == "text"
    assert content[0]["text"] == "Q1 text"
    assert content[1]["type"] == "equation"
    assert "x^2=1" in content[1]["text"]


def test_adapter_on_kira_pages_tree():
    if not KIRA_TREE.is_file():
        # Keep CI green when local fixture path is absent.
        assert FIXTURE.is_file()
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        content = pages_tree_to_content_list(data)
        assert isinstance(content, list)
        return

    data = json.loads(KIRA_TREE.read_text(encoding="utf-8"))
    content = pages_tree_to_content_list(data)
    assert len(content) > 20
    assert all("id" in item for item in content)
    texts = "\n".join(item.get("text", "") for item in content)
    assert "切平面" in texts or "选择题" in texts
